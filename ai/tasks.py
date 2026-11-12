"""The AI jobs of the app: describe a document, find its budget lines, tag them, score budgets.

Every job takes the model chosen by the user (a constants.MODELS id); None means the default model.

Everything here is provider-neutral. It talks to the model only through ai.client.ask_json.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any

import constants as C
from tagging.models import Verdict
from utils.documents import Chunk, Document, make_chunks, split_chunk

from . import client, prompt
from .schemas import DESCRIBE_SCHEMA, EXTRACT_SCHEMA, SCORE_SCHEMA, TAG_SCHEMA
from .types import (AIConfigError, AIError, AIQuotaError, AIResponseError, AIServerError, Attachment, Cancelled,
                    DocInfo)

ProgressFn = Callable[..., None]
FATAL = (AIConfigError, AIQuotaError, Cancelled)
MAX_SPLIT_DEPTH = 3


def _text(v: Any, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit]


def _workers() -> int:
    return C.env_int(C.ENV_AI_WORKERS, C.DEFAULT_AI_WORKERS)


# ── 1. describe ─────────────────────────────────────────────────────────────
def describe_document(doc: Document, cancelled: Callable[[], bool] | None = None, model: str | None = None) -> DocInfo:
    fallback = DocInfo(name=Path(doc.filename).stem.replace("_", " ").strip()[:120])
    try:
        data = client.ask_json(prompt.DESCRIBE_SYSTEM, prompt.describe_prompt(doc.sample_text(), doc.filename),
                               DESCRIBE_SCHEMA, max_output_tokens=1024, cancelled=cancelled, model=model)
    except FATAL:
        raise
    except AIError:
        return fallback
    if not isinstance(data, dict):
        return fallback
    try:
        year = int(data.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    unit = data.get("unit") if data.get("unit") in ("units", "thousands", "millions", "billions") else "units"
    return DocInfo(name=_text(data.get("name"), 120) or fallback.name, country=_text(data.get("country"), 60),
                   year=year if 1900 <= year <= 2100 else 0, currency=_text(data.get("currency"), 20), unit=unit,
                   document_type=_text(data.get("document_type"), 40))


# ── 2. find the budget lines ────────────────────────────────────────────────
@dataclass
class Extraction:
    records: list[dict[str, Any]] = field(default_factory=list)
    failed_sections: list[str] = field(default_factory=list)
    sections: int = 0


def _records(data: Any, chunk: Chunk) -> list[dict[str, Any]]:
    rows = data.get("lines") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise AIResponseError("The answer had no list of lines")
    out = []
    for r in rows:
        if isinstance(r, dict):
            r = dict(r)
            if not r.get("page"):
                r["page"] = chunk.first_page
            out.append(r)
    return out


def _extract_chunk(chunk: Chunk, doc: Document, info: DocInfo, cancelled, depth: int = 0,
                   model: str | None = None) -> list[dict[str, Any]]:
    attachments = [Attachment("application/pdf", chunk.pdf_slice)] if chunk.pdf_slice else []
    spreadsheet = doc.kind == "xlsx"
    text = prompt.extract_prompt(chunk.text, info, chunk.label, bool(attachments), spreadsheet)
    try:
        data = client.ask_json(prompt.extract_system(spreadsheet), text, EXTRACT_SCHEMA, attachments, max_output_tokens=32768,
                               cancelled=cancelled, model=model)
        return _records(data, chunk)
    except AIResponseError as exc:
        if depth >= MAX_SPLIT_DEPTH:
            raise
        parts = []
        if exc.truncated or exc.too_long or "JSON" in str(exc):
            # a one-page section that is too large because of its page image is better sent as text than halved
            if not (exc.too_long and attachments and chunk.first_page == chunk.last_page):
                parts = split_chunk(chunk, doc)
        if parts:
            return [r for p in parts for r in _extract_chunk(p, doc, info, cancelled, depth + 1, model)]
        if attachments and (exc.blocked or exc.too_long):   # try again with the text alone
            plain = Chunk(chunk.index, chunk.first_page, chunk.last_page, chunk.text, None)
            return _extract_chunk(plain, doc, info, cancelled, depth + 1, model)
        raise


def extract_budget_lines(doc: Document, info: DocInfo, progress: ProgressFn,
                         cancelled: Callable[[], bool] | None = None, model: str | None = None) -> Extraction:
    chunks = make_chunks(doc)
    abort = threading.Event()

    def stop() -> bool:
        return abort.is_set() or bool(cancelled and cancelled())

    results: dict[int, list[dict[str, Any]]] = {}
    failed: list[str] = []
    done = 0
    progress(C.STAGE_FIND, "Section 0 of %d" % len(chunks))
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        futures = {pool.submit(_extract_chunk, c, doc, info, stop, 0, model): c for c in chunks}
        try:
            for fut in as_completed(futures):
                chunk = futures[fut]
                try:
                    results[chunk.index] = fut.result()
                except FATAL:
                    raise
                except AIError:
                    results[chunk.index] = []
                    failed.append(chunk.label)
                done += 1
                progress(C.STAGE_FIND, "Section %d of %d" % (done, len(chunks)))
        except BaseException:
            abort.set()
            for f in futures:
                f.cancel()
            raise
    if cancelled and cancelled():
        raise Cancelled()
    records = [r for idx in sorted(results) for r in results[idx]]
    if failed and len(failed) == len(chunks):
        raise AIServerError("Every section failed")
    return Extraction(records, failed, len(chunks))


# ── 3. tag the lines ────────────────────────────────────────────────────────
def _flag(v: Any) -> bool:
    return v.strip().lower() in ("true", "yes", "1") if isinstance(v, str) else bool(v)


def snap_level(v: Any) -> int:
    """The nearest of 0, 20, 40, 70 and 100 to the number the model wrote (a tie goes to the lower level)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(v if v is not None else ""))]
    if not nums:
        return 0
    x = min(max(sum(nums) / len(nums), 0.0), 100.0)
    return min((0,) + C.LEVELS, key=lambda level: (abs(level - x), level))


def verdict_from_row(row: dict[str, Any]) -> Verdict:
    q1, q2 = _flag(row.get("q1_ghg_related")), _flag(row.get("q2_mitigation_measure"))
    q3, q4 = _flag(row.get("q3_climate_hazard_related")), _flag(row.get("q4_adaptation_measure"))
    service = _flag(row.get("service_oriented"))
    floor = _flag(row.get("livability_floor")) and not service
    mit, ada = q1 and q2 and not service, q3 and q4 and not service
    floor_only = floor and not (mit or ada)
    if floor_only:
        ada = True
    level = snap_level(row.get("climate_level"))
    if floor:
        level = max(level, C.FLOOR_LEVEL)
    # a climate-tagged line always sits in one of the four levels; any other line has none
    level = (level or C.LEVELS[-1]) if (mit or ada) else 0
    conf = str(row.get("confidence") or "medium").upper()
    sector, function = row.get("sector"), row.get("function")
    return Verdict(q1_ghg_related=q1, q2_mitigation_measure=q2, q3_climate_hazard_related=q3, q4_adaptation_measure=q4,
                   mitigation=mit, adaptation=ada, level=level, floor_only=floor_only, service_oriented=service,
                   sector=sector if sector in C.SECTORS else "None",
                   function=function if function in C.FUNCTIONS else "Not known",
                   confidence=conf if conf in (C.CONF_HIGH, C.CONF_MEDIUM, C.CONF_LOW) else C.CONF_MEDIUM,
                   rationale=_text(row.get("rationale"), 260))


def _tag_batch(batch: list[dict[str, Any]], cancelled, depth: int = 0, model: str | None = None) -> dict[int, Verdict]:
    try:
        data = client.ask_json(prompt.TAG_SYSTEM, prompt.tag_prompt(batch), TAG_SCHEMA, max_output_tokens=16384,
                               cancelled=cancelled, model=model)
    except AIResponseError as exc:
        if len(batch) > 1 and depth < MAX_SPLIT_DEPTH and (exc.truncated or exc.too_long or "JSON" in str(exc)):
            mid = len(batch) // 2
            return {**_tag_batch(batch[:mid], cancelled, depth + 1, model), **_tag_batch(batch[mid:], cancelled, depth + 1, model)}
        raise
    rows = data.get("tags") if isinstance(data, dict) else data
    wanted = {int(b["id"]) for b in batch}
    out: dict[int, Verdict] = {}
    for r in rows if isinstance(rows, list) else []:
        try:
            i = int(r.get("id"))
        except (AttributeError, TypeError, ValueError):
            continue
        if i in wanted:
            out[i] = verdict_from_row(r)
    return out


def _run_batches(batches: list[list[dict[str, Any]]], progress: ProgressFn, cancelled, done_offset: int,
                 total: int, model: str | None = None) -> tuple:
    abort = threading.Event()

    def stop() -> bool:
        return abort.is_set() or bool(cancelled and cancelled())

    verdicts: dict[int, Verdict] = {}
    last_error: AIError | None = None
    done = done_offset
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        futures = {pool.submit(_tag_batch, b, stop, 0, model): b for b in batches}
        try:
            for fut in as_completed(futures):
                try:
                    verdicts.update(fut.result())
                except FATAL:
                    raise
                except AIError as exc:
                    last_error = exc
                done += len(futures[fut])
                progress(C.STAGE_TAG, "%d of %d lines" % (min(done, total), total))
        except BaseException:
            abort.set()
            for f in futures:
                f.cancel()
            raise
    return verdicts, last_error


def tag_budget_lines(items: list[dict[str, Any]], progress: ProgressFn,
                     cancelled: Callable[[], bool] | None = None, model: str | None = None) -> dict[int, Verdict]:
    """items: dicts with id, title, ministry, description, function_code. Returns id -> verdict (missing ids = AI failed)."""
    size = C.TAG_BATCH_SIZE
    total = len(items)
    progress(C.STAGE_TAG, "0 of %d lines" % total)
    verdicts, error = _run_batches([items[i:i + size] for i in range(0, total, size)], progress, cancelled, 0, total, model)
    missing = [it for it in items if int(it["id"]) not in verdicts]
    if missing and verdicts:                           # one more try for lines the AI skipped
        small = max(5, size // 3)
        extra, error = _run_batches([missing[i:i + small] for i in range(0, len(missing), small)], progress, cancelled,
                                    total, total + len(missing), model)
        verdicts.update(extra)
    if not verdicts and items:
        raise error or AIResponseError("The AI returned no tags")
    return verdicts


# ── 4. score ────────────────────────────────────────────────────────────────
def score_budgets(briefs: list[dict[str, Any]], cancelled: Callable[[], bool] | None = None,
                  model: str | None = None) -> dict[str, Any]:
    """Returns {"scores": {"A": (score, reason), ...}, "summary": str}. Raises AIError if the answer is unusable."""
    data = client.ask_json(prompt.SCORE_SYSTEM, prompt.score_prompt(briefs), SCORE_SCHEMA, max_output_tokens=2048,
                           cancelled=cancelled, model=model)
    if not isinstance(data, dict):
        raise AIResponseError("The score answer was not an object")
    scores: dict[str, Any] = {}
    for row in data.get("budgets") or []:
        try:
            scores[str(row["label"])] = (max(0, min(100, int(row["score"]))), _text(row.get("reason"), 300))
        except (KeyError, TypeError, ValueError):
            continue
    wanted = {b["label"] for b in briefs}
    if not wanted <= set(scores):
        raise AIResponseError("The score answer did not cover every budget")
    return {"scores": scores, "summary": _text(data.get("summary"), 500)}
