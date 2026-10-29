"""The AI jobs of the app: describe a document, find its budget lines, tag them, score budgets.

Everything here is provider-neutral. It talks to the model only through ai.client.ask_json.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tagging.models import AIVerdict
from utils import constants as C
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
def describe_document(doc: Document, cancelled: Optional[Callable[[], bool]] = None) -> DocInfo:
    fallback = DocInfo(name=Path(doc.filename).stem.replace("_", " ").strip()[:120])
    try:
        data = client.ask_json(prompt.DESCRIBE_SYSTEM, prompt.describe_prompt(doc.sample_text(), doc.filename),
                               DESCRIBE_SCHEMA, max_output_tokens=1024, cancelled=cancelled)
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
    records: List[Dict[str, Any]] = field(default_factory=list)
    failed_sections: List[str] = field(default_factory=list)
    sections: int = 0


def _records(data: Any, chunk: Chunk) -> List[Dict[str, Any]]:
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


def _extract_chunk(chunk: Chunk, doc: Document, info: DocInfo, cancelled, depth: int = 0) -> List[Dict[str, Any]]:
    attachments = [Attachment("application/pdf", chunk.pdf_slice)] if chunk.pdf_slice else []
    text = prompt.extract_prompt(chunk.text, info, chunk.label, bool(attachments))
    try:
        data = client.ask_json(prompt.EXTRACT_SYSTEM, text, EXTRACT_SCHEMA, attachments, max_output_tokens=32768,
                               cancelled=cancelled)
        return _records(data, chunk)
    except AIResponseError as exc:
        if depth >= MAX_SPLIT_DEPTH:
            raise
        parts = split_chunk(chunk, doc) if exc.truncated or "JSON" in str(exc) else []
        if parts:
            return [r for p in parts for r in _extract_chunk(p, doc, info, cancelled, depth + 1)]
        if attachments and exc.blocked:               # try again with the text alone
            plain = Chunk(chunk.index, chunk.first_page, chunk.last_page, chunk.text, None)
            return _extract_chunk(plain, doc, info, cancelled, depth + 1)
        raise


def extract_budget_lines(doc: Document, info: DocInfo, progress: ProgressFn,
                         cancelled: Optional[Callable[[], bool]] = None) -> Extraction:
    chunks = make_chunks(doc)
    abort = threading.Event()

    def stop() -> bool:
        return abort.is_set() or bool(cancelled and cancelled())

    results: Dict[int, List[Dict[str, Any]]] = {}
    failed: List[str] = []
    done = 0
    progress(C.STAGE_FIND, "Section 0 of %d" % len(chunks))
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        futures = {pool.submit(_extract_chunk, c, doc, info, stop): c for c in chunks}
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
def _level(v: Any) -> int:
    try:
        return max(0, min(2, int(v)))
    except (TypeError, ValueError):
        return 0


def verdict_from_row(row: Dict[str, Any]) -> AIVerdict:
    objectives: List[str] = []
    for o in row.get("eu_objectives") or []:
        if o in C.EU_OBJECTIVES and o not in objectives:
            objectives.append(o)
    mit, ada = _level(row.get("rio_mitigation")), _level(row.get("rio_adaptation"))
    brown, admin = bool(row.get("brown")), bool(row.get("administrative"))
    if admin:
        mit = ada = 0
        objectives, brown = [], False
    elif brown:
        mit = ada = 0
        objectives = []
    conf = str(row.get("confidence") or "medium").upper()
    return AIVerdict(rio_mitigation=mit, rio_adaptation=ada, eu_objectives=objectives, brown=brown, administrative=admin,
                     confidence=conf if conf in (C.CONF_HIGH, C.CONF_MEDIUM, C.CONF_LOW) else C.CONF_MEDIUM,
                     rationale=_text(row.get("rationale"), 260))


def _tag_batch(batch: List[Dict[str, Any]], cancelled, depth: int = 0) -> Dict[int, AIVerdict]:
    try:
        data = client.ask_json(prompt.TAG_SYSTEM, prompt.tag_prompt(batch), TAG_SCHEMA, max_output_tokens=16384,
                               cancelled=cancelled)
    except AIResponseError as exc:
        if len(batch) > 1 and depth < MAX_SPLIT_DEPTH and (exc.truncated or "JSON" in str(exc)):
            mid = len(batch) // 2
            return {**_tag_batch(batch[:mid], cancelled, depth + 1), **_tag_batch(batch[mid:], cancelled, depth + 1)}
        raise
    rows = data.get("tags") if isinstance(data, dict) else data
    wanted = {int(b["id"]) for b in batch}
    out: Dict[int, AIVerdict] = {}
    for r in rows if isinstance(rows, list) else []:
        try:
            i = int(r.get("id"))
        except (AttributeError, TypeError, ValueError):
            continue
        if i in wanted:
            out[i] = verdict_from_row(r)
    return out


def _run_batches(batches: List[List[Dict[str, Any]]], progress: ProgressFn, cancelled, done_offset: int,
                 total: int) -> tuple:
    abort = threading.Event()

    def stop() -> bool:
        return abort.is_set() or bool(cancelled and cancelled())

    verdicts: Dict[int, AIVerdict] = {}
    last_error: Optional[AIError] = None
    done = done_offset
    with ThreadPoolExecutor(max_workers=_workers()) as pool:
        futures = {pool.submit(_tag_batch, b, stop): b for b in batches}
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


def tag_budget_lines(items: List[Dict[str, Any]], progress: ProgressFn,
                     cancelled: Optional[Callable[[], bool]] = None) -> Dict[int, AIVerdict]:
    """items: dicts with id, title, ministry, description, function_code. Returns id -> verdict (missing ids = AI failed)."""
    size = C.TAG_BATCH_SIZE
    total = len(items)
    progress(C.STAGE_TAG, "0 of %d lines" % total)
    verdicts, error = _run_batches([items[i:i + size] for i in range(0, total, size)], progress, cancelled, 0, total)
    missing = [it for it in items if int(it["id"]) not in verdicts]
    if missing and verdicts:                           # one more try for lines the AI skipped
        small = max(5, size // 3)
        extra, error = _run_batches([missing[i:i + small] for i in range(0, len(missing), small)], progress, cancelled,
                                    total, total + len(missing))
        verdicts.update(extra)
    if not verdicts and items:
        raise error or AIResponseError("The AI returned no tags")
    return verdicts


# ── 4. score ────────────────────────────────────────────────────────────────
def score_budgets(briefs: List[Dict[str, Any]], cancelled: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Returns {"scores": {"A": (score, reason), ...}, "summary": str}. Raises AIError if the answer is unusable."""
    data = client.ask_json(prompt.SCORE_SYSTEM, prompt.score_prompt(briefs), SCORE_SCHEMA, max_output_tokens=2048,
                           cancelled=cancelled)
    if not isinstance(data, dict):
        raise AIResponseError("The score answer was not an object")
    scores: Dict[str, Any] = {}
    for row in data.get("budgets") or []:
        try:
            scores[str(row["label"])] = (max(0, min(100, int(row["score"]))), _text(row.get("reason"), 300))
        except (KeyError, TypeError, ValueError):
            continue
    wanted = {b["label"] for b in briefs}
    if not wanted <= set(scores):
        raise AIResponseError("The score answer did not cover every budget")
    return {"scores": scores, "summary": _text(data.get("summary"), 500)}
