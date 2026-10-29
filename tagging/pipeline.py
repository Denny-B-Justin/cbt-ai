"""From an uploaded file to tagged budget lines and summary numbers, and the two-budget comparison."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ai import tasks
from ai.types import AIConfigError, AIError, AIQuotaError, Cancelled, DocInfo
from utils import constants as C
from utils import documents

from . import lines as L
from .eu_tagger import EUTaxonomyTagger
from .metrics import rubric_score, summarize
from .models import AIVerdict, LineText
from .reconcile import combine_eu, combine_rio
from .rio_tagger import RioMarkerTagger

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
    rio: pd.DataFrame
    eu: pd.DataFrame
    rio_summary: Dict[str, Any]
    eu_summary: Dict[str, Any]
    stats: Dict[str, Any]
    issues: List[Dict[str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.info.name or self.filename

    @property
    def subtitle(self) -> str:
        return " · ".join(p for p in (self.info.country, str(self.info.year) if self.info.year else "") if p)


def _key(line: L.Line) -> tuple:
    return tuple(" ".join(s.lower().split()) for s in (line.ministry, line.title, line.description, line.function_code))


def _unique_items(lines: List[L.Line]):
    """One entry per distinct classification, so identical lines are tagged once."""
    index: Dict[tuple, int] = {}
    unique: List[L.Line] = []
    line_to_id: List[int] = []
    for ln in lines:
        k = _key(ln)
        if k not in index:
            index[k] = len(unique) + 1
            unique.append(ln)
        line_to_id.append(index[k])
    return unique, line_to_id


def _base_frame(lines: List[L.Line]) -> pd.DataFrame:
    return pd.DataFrame({
        "line": range(1, len(lines) + 1), "page": [ln.page or None for ln in lines], "code": [ln.code or None for ln in lines],
        "ministry": [ln.ministry or None for ln in lines], "programme": [ln.title for ln in lines],
        "description": [ln.description or None for ln in lines], "function_code": [ln.function_code or None for ln in lines],
        "amount": [ln.amount if ln.amount is not None else np.nan for ln in lines]})


def build_frames(lines: List[L.Line], verdicts: Dict[int, Optional[AIVerdict]], unique: List[L.Line],
                 line_to_id: List[int]) -> Dict[str, pd.DataFrame]:
    rio_tagger, eu_tagger = RioMarkerTagger(), EUTaxonomyTagger()
    rio_by_id: Dict[int, Dict[str, Any]] = {}
    eu_by_id: Dict[int, Dict[str, Any]] = {}
    for i, ln in enumerate(unique, start=1):
        text = LineText(ln.title, ln.description, ln.ministry, ln.function_code)
        ai = verdicts.get(i)
        rio_by_id[i] = combine_rio(ai, rio_tagger.tag(text))
        eu_by_id[i] = combine_eu(ai, eu_tagger.tag(text))

    out = {}
    for kind, by_id in ((C.KIND_RIO, rio_by_id), (C.KIND_EU, eu_by_id)):
        df = pd.concat([_base_frame(lines), pd.DataFrame([by_id[i] for i in line_to_id])], axis=1)
        df["decided_by"] = df["tag_method"].map(C.DECIDED_LABELS)
        out[kind] = df
    return out


def _method_counts(df: pd.DataFrame, line_to_id: List[int]) -> Dict[str, int]:
    """Count distinct classifications (not lines) per deciding rule, labelled for the chart."""
    first = pd.Series(line_to_id).drop_duplicates().index
    counts = df.iloc[first]["tag_method"].value_counts()
    return {C.DECIDED_LABELS[k]: int(v) for k, v in counts.items()}


def analyse_document(data: bytes, filename: str, progress: ProgressFn,
                     cancelled: Optional[Callable[[], bool]] = None) -> Analysis:
    started = time.time()
    try:
        progress(C.STAGE_READ)
        doc = documents.read_document(data, filename)
        info = tasks.describe_document(doc, cancelled)
        extraction = tasks.extract_budget_lines(doc, info, progress, cancelled)
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
        verdicts = tasks.tag_budget_lines(items, progress, cancelled)

        progress(C.STAGE_CALC)
        frames = build_frames(lines, verdicts, unique, line_to_id)
    except documents.DocumentError as exc:
        raise AnalysisError(str(exc)) from exc
    except AIError as exc:
        raise AnalysisError(exc.user_message) from exc

    rio, eu = frames[C.KIND_RIO], frames[C.KIND_EU]
    rio_summary, eu_summary = summarize(C.KIND_RIO, rio), summarize(C.KIND_EU, eu)
    n_rules_only = sum(1 for i in range(1, len(unique) + 1) if i not in verdicts)

    for note in doc.notes:
        issues.append({"level": "info", "message": note})
    if extraction.failed_sections:
        issues.append({"level": "warn", "message": "Some parts of the document could not be read (%s). The results cover the "
                       "rest." % ", ".join(extraction.failed_sections[:6])})
    if n_rules_only:
        issues.append({"level": "warn", "message": "%d line(s) could not be assessed by the AI and were checked with keywords "
                       "only. They are marked in the table." % n_rules_only})
    if not rio_summary["has_amount"]:
        issues.append({"level": "warn", "message": "No amounts could be found, so shares are based on the number of budget lines."})
    elif rio_summary["amount_lines"] < 0.6 * rio_summary["lines"]:
        issues.append({"level": "info", "message": "Amounts were found for %d of %d lines. Shares are based on the lines that "
                       "have an amount." % (rio_summary["amount_lines"], rio_summary["lines"])})

    stats = {"lines": len(lines), "unique_classifications": len(unique), "seconds": round(time.time() - started, 1),
             "pages": doc.n_pages, "sections": extraction.sections, "rules_only": n_rules_only,
             "rio_methods": _method_counts(rio, line_to_id),
             "eu_methods": _method_counts(eu, line_to_id), **{"selection_" + k: v for k, v in selection.stats.items()}}
    return Analysis(filename, info, doc.n_pages, rio, eu, rio_summary, eu_summary, stats, issues)


# ── comparing two analysed budgets ──────────────────────────────────────────
@dataclass
class Comparison:
    scores: Dict[str, int]
    reasons: Dict[str, str]
    summary: str
    rubric: Dict[str, Dict[str, Any]]


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else "%.1f%%" % (v * 100)


def _top_lines(a: Analysis, mask: pd.Series, n: int = 5) -> List[str]:
    df = a.rio[mask.values].copy()
    if df.empty:
        return []
    key = df["amount"].fillna(-1) if a.rio_summary["has_amount"] else pd.Series(0, index=df.index)
    top = df.assign(_k=key).sort_values("_k", ascending=False).head(n)
    return [str(t)[:90] for t in top["programme"]]


def brief(a: Analysis, label: str) -> Dict[str, Any]:
    r, e = a.rio_summary, a.eu_summary
    return {
        "label": label, "name": a.name + (" (%s)" % a.subtitle if a.subtitle else ""), "lines": r["lines"], "basis": r["basis"],
        "weighted_share": _pct(r["weighted_share"]), "principal_share": _pct(r["principal_share"]),
        "significant_share": _pct(r["significant_share"]), "mitigation_share": _pct(r["mitigation_share"]),
        "adaptation_share": _pct(r["adaptation_share"]), "green_share": _pct(e["green_share"]),
        "brown_share": _pct(e["brown_share"]),
        "objectives": ", ".join("%s %s" % (k.replace("_", " "), _pct(v)) for k, v in e["objective_shares"].items()),
        "top_green": _top_lines(a, a.rio["rio_marker"] > 0), "top_brown": _top_lines(a, a.eu["climate_tag"] == C.TAG_BROWN, 3),
    }


def _fallback_reason(a: Analysis) -> str:
    r, e = a.rio_summary, a.eu_summary
    text = "About %s of the budget supports climate goals" % _pct(r["weighted_share"])
    if (e["brown_share"] or 0) >= 0.01:
        text += ", and %s goes to fossil or polluting activities" % _pct(e["brown_share"])
    return text + "."


def compare_budgets(a: Analysis, b: Analysis, cancelled: Optional[Callable[[], bool]] = None) -> Comparison:
    items = {"A": a, "B": b}
    rubric = {k: rubric_score(v.rio_summary, v.eu_summary) for k, v in items.items()}
    scores = {k: rubric[k]["score"] for k in items}
    reasons = {k: _fallback_reason(v) for k, v in items.items()}
    summary = ""
    try:
        result = tasks.score_budgets([brief(a, "A"), brief(b, "B")], cancelled)
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
