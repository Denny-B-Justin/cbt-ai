"""From an uploaded file to tagged budget lines and summary numbers, and the two-budget comparison."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

import constants as C
from ai import client, tasks
from ai.types import AIConfigError, AIError, AIQuotaError, Cancelled, DocInfo
from utils import documents

from . import lines as L
from .metrics import rubric_score, summarize
from .tags import tagged_frame

ProgressFn = Callable[..., None]
SCORE_GUARD = 15
BASE_COLUMNS = ["line", "page", "code", "ministry", "programme", "description", "function_code", "amount"]


class AnalysisError(Exception):
    """The analysis could not finish; the message is safe to show to the user."""


@dataclass
class Analysis:
    filename: str
    info: DocInfo
    pages: int
    lines: pd.DataFrame                 # one row per budget line: BASE_COLUMNS + tags + climate amounts + decided_by
    summary: dict[str, Any]             # metrics.summarize
    stats: dict[str, Any]
    issues: list[dict[str, str]] = field(default_factory=list)
    model: str = ""                     # the AI model that read and tagged the document (a constants.MODELS id)

    @property
    def name(self) -> str:
        return self.info.name or self.filename

    @property
    def model_label(self) -> str:
        return client.model_label(self.model)

    @property
    def subtitle(self) -> str:
        return " · ".join(p for p in (self.info.country, str(self.info.year) if self.info.year else "") if p)


def _key(line: L.Line) -> tuple:
    return tuple(" ".join(s.lower().split()) for s in (line.ministry, line.title, line.description, line.function_code))


def _unique_items(lines: list[L.Line]):
    """One entry per distinct classification, so identical lines are tagged once."""
    index: dict[tuple, int] = {}
    unique: list[L.Line] = []
    line_to_id: list[int] = []
    for ln in lines:
        k = _key(ln)
        if k not in index:
            index[k] = len(unique) + 1
            unique.append(ln)
        line_to_id.append(index[k])
    return unique, line_to_id


def _base_frame(lines: list[L.Line]) -> pd.DataFrame:
    return pd.DataFrame({
        "line": range(1, len(lines) + 1), "page": [ln.page or None for ln in lines], "code": [ln.code or None for ln in lines],
        "ministry": [ln.ministry or None for ln in lines], "programme": [ln.title for ln in lines],
        "description": [ln.description or None for ln in lines], "function_code": [ln.function_code or None for ln in lines],
        "amount": [ln.amount if ln.amount is not None else np.nan for ln in lines]})


def analyse_document(data: bytes, filename: str, progress: ProgressFn,
                     cancelled: Callable[[], bool] | None = None, model: str | None = None) -> Analysis:
    """model: the constants.MODELS id the user chose; None uses the default model."""
    started = time.time()
    model = model or client.default_model()
    try:
        progress(C.STAGE_READ)
        doc = documents.read_document(data, filename)
        info = tasks.describe_document(doc, cancelled, model)
        extraction = tasks.extract_budget_lines(doc, info, progress, cancelled, model)
        if cancelled and cancelled():
            raise Cancelled()

        selection = L.select_lines(extraction.records)
        lines = selection.lines
        if not lines:
            raise AnalysisError("We could not find any budget lines in this document. Please check that it is a budget "
                                "with programmes, projects or spending items.")
        issues = list(selection.issues)
        if len(lines) > C.MAX_UNIQUE_LINES:
            lines = sorted(lines, key=lambda ln: -(ln.amount if ln.amount is not None else -1))[:C.MAX_UNIQUE_LINES]
            lines.sort(key=lambda ln: (ln.page, ln.order))
            issues.append({"level": "warn", "message": "This document has a very large number of budget lines. The %d largest "
                           "were assessed." % C.MAX_UNIQUE_LINES})

        unique, line_to_id = _unique_items(lines)
        items = [{"id": i, "title": ln.title, "ministry": ln.ministry, "description": ln.description,
                  "function_code": ln.function_code} for i, ln in enumerate(unique, start=1)]
        progress(C.STAGE_TAG)
        verdicts = tasks.tag_budget_lines(items, progress, cancelled, model)

        progress(C.STAGE_CALC)
        df = tagged_frame(_base_frame(lines), verdicts, line_to_id)
    except documents.DocumentError as exc:
        raise AnalysisError(str(exc)) from exc
    except AIError as exc:
        raise AnalysisError(exc.user_message) from exc

    summary = summarize(df)
    not_assessed = sum(1 for i in range(1, len(unique) + 1) if i not in verdicts)

    for note in doc.notes:
        issues.append({"level": "info", "message": note})
    if extraction.failed_sections:
        issues.append({"level": "warn", "message": "Some parts of the document could not be read (%s). The results cover the "
                       "rest." % ", ".join(extraction.failed_sections[:6])})
    if not_assessed:
        issues.append({"level": "warn", "message": "%d line(s) could not be assessed. They are marked \"Not assessed\" in the "
                       "table and do not count as climate spending." % not_assessed})
    if not summary["has_amount"]:
        issues.append({"level": "warn", "message": "No amounts could be found, so shares are based on the number of budget lines."})
    elif summary["amount_lines"] < 0.6 * summary["lines"]:
        issues.append({"level": "info", "message": "Amounts were found for %d of %d lines. Shares are based on the lines that "
                       "have an amount." % (summary["amount_lines"], summary["lines"])})

    stats = {"lines": len(lines), "unique_classifications": len(unique), "seconds": round(time.time() - started, 1),
             "pages": doc.n_pages, "sections": extraction.sections, "not_assessed": not_assessed,
             **{"selection_" + k: v for k, v in selection.stats.items()}}
    return Analysis(filename, info, doc.n_pages, df, summary, stats, issues, model)


# ── comparing two analysed budgets ──────────────────────────────────────────
@dataclass
class Comparison:
    scores: dict[str, int]
    reasons: dict[str, str]
    summary: str
    rubric: dict[str, dict[str, Any]]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else "%.1f%%" % (v * 100)


def _top_lines(a: Analysis, n: int = 5) -> list[str]:
    key = "climate_amount" if a.summary["has_amount"] else "climate_level"
    df = a.lines[a.lines[key].fillna(0) > 0]
    return [str(t)[:90] for t in df.sort_values(key, ascending=False).head(n)["programme"]]


def brief(a: Analysis, label: str) -> dict[str, Any]:
    s = a.summary
    return {
        "label": label, "name": a.name + (" (%s)" % a.subtitle if a.subtitle else ""), "lines": s["lines"], "basis": s["basis"],
        "climate_share": _pct(s["climate_share"]), "mitigation_share": _pct(s["mitigation_share"]),
        "adaptation_share": _pct(s["adaptation_share"]), "high_level_share": _pct(s["high_level_share"]),
        "cm_lines": s["code_lines"][C.CM], "ca_lines": s["code_lines"][C.CA], "cb_lines": s["code_lines"][C.CB],
        "sectors": ", ".join(s["climate_sectors"]) or "none", "top_climate": _top_lines(a),
    }


def _fallback_reason(a: Analysis) -> str:
    return "About %s of the budget counts as climate spending." % _pct(a.summary["climate_share"])


def compare_budgets(a: Analysis, b: Analysis, cancelled: Callable[[], bool] | None = None) -> Comparison:
    """Scored by the model that tagged budget A (both budgets of a comparison are tagged by the same model)."""
    items = {"A": a, "B": b}
    rubric = {k: rubric_score(v.summary) for k, v in items.items()}
    scores = {k: rubric[k]["score"] for k in items}
    reasons = {k: _fallback_reason(v) for k, v in items.items()}
    summary = ""
    try:
        result = tasks.score_budgets([brief(a, "A"), brief(b, "B")], cancelled, a.model or None)
        for k in items:
            ai_score, reason = result["scores"][k]
            guard = rubric[k]["score"]
            scores[k] = max(guard - SCORE_GUARD, min(guard + SCORE_GUARD, ai_score))
            reasons[k] = reason or reasons[k]
        summary = result["summary"]
    except (AIConfigError, AIQuotaError, Cancelled):
        raise
    except AIError:
        pass                                           # keep the rubric scores
    if not summary:
        hi = max(scores, key=scores.get)
        summary = ("Budget %s scores higher overall." % hi) if scores["A"] != scores["B"] else "Both budgets score the same overall."
    return Comparison(scores, reasons, summary, rubric)
