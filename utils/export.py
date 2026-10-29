"""Excel workbooks for download, and the readable tables shown on screen."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, List

import pandas as pd

from tagging.pipeline import Analysis, Comparison

from . import constants as C
from .formatting import fmt_pct

NO_VALUE = "-"


def _amount_header(a: Analysis) -> str:
    unit = a.info.unit_text
    return "Amount (%s)" % unit if unit else "Amount"


def display_frame(a: Analysis, kind: str) -> pd.DataFrame:
    """The tagged lines with plain column names, the way people read them."""
    df = a.rio if kind == C.KIND_RIO else a.eu
    out = pd.DataFrame({"Line": df["line"], "Page": df["page"], "Ministry": df["ministry"], "Budget line": df["programme"],
                        _amount_header(a): df["amount"]})
    if kind == C.KIND_RIO:
        out["Rio marker"] = df["rio_marker"].map(lambda m: "%d · %s" % (m, C.RIO_LABELS[int(m)]))
        out["Mitigation"] = df["rio_mitigation"]
        out["Adaptation"] = df["rio_adaptation"]
    else:
        flags = [C.EU_FLAG_COLUMNS[k] for k in C.EU_OBJECTIVES]
        out["Climate tag"] = df["climate_tag"].map(lambda t: C.TAG_LABELS.get(t, t))
        out["Main objective"] = df["eu_primary_objective"].map(lambda k: C.EU_LABELS.get(k, ""))
        out["All objectives"] = df[flags].apply(lambda r: ", ".join(C.EU_LABELS[k] for k, f in zip(C.EU_OBJECTIVES, r) if f), axis=1)
    out["Confidence"] = df["confidence"].str.capitalize()
    out["Decided by"] = df["decided_by"]
    out["Why"] = df["rationale"]
    return out


def summary_rows(a: Analysis) -> List[List[Any]]:
    r, e = a.rio_summary, a.eu_summary
    basis = "amount" if r["basis"] == "amount" else "number of lines"
    rows: List[List[Any]] = [
        ["General", "Budget lines assessed", r["lines"]], ["General", "Shares are based on", basis],
        [C.KIND_LABELS[C.KIND_RIO], "Climate share (Principal counts 100%, Significant counts 40%)", fmt_pct(r["weighted_share"])],
        [C.KIND_LABELS[C.KIND_RIO], "Principal (2)", fmt_pct(r["principal_share"])],
        [C.KIND_LABELS[C.KIND_RIO], "Significant (1)", fmt_pct(r["significant_share"])],
        [C.KIND_LABELS[C.KIND_RIO], "Mitigation", fmt_pct(r["mitigation_share"])],
        [C.KIND_LABELS[C.KIND_RIO], "Adaptation", fmt_pct(r["adaptation_share"])],
        [C.KIND_LABELS[C.KIND_EU], "Green share", fmt_pct(e["green_share"])],
        [C.KIND_LABELS[C.KIND_EU], "Brown share", fmt_pct(e["brown_share"])]]
    rows += [[C.KIND_LABELS[C.KIND_EU], C.EU_LABELS[k], fmt_pct(e["objective_shares"].get(k))] for k in C.EU_OBJECTIVES]
    return rows


def _fit(writer: pd.ExcelWriter) -> None:
    for ws in writer.book.worksheets:
        ws.freeze_panes = "A2"
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":                                # text from a document must never run as a formula
                    cell.data_type = "s"
        for idx, col in enumerate(ws.iter_cols(min_row=1, max_row=min(ws.max_row, 200)), start=1):
            width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(max(10, width + 2), 60)


def _about(a: Analysis) -> List[List[Any]]:
    return [["Document", a.name], ["Country", a.info.country or NO_VALUE], ["Year", a.info.year or NO_VALUE],
            ["Currency and unit", a.info.unit_text or NO_VALUE], ["Pages read", a.pages],
            ["Prepared on", datetime.now(timezone.utc).strftime("%d %b %Y")],
            ["Note", "Tags are produced with the help of AI and should be reviewed before they are used."]]


def evaluation_workbook(a: Analysis) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        pd.DataFrame(_about(a), columns=["Item", "Value"]).to_excel(xl, sheet_name="About", index=False)
        pd.DataFrame(summary_rows(a), columns=["Method", "Measure", "Value"]).to_excel(xl, sheet_name="Summary", index=False)
        display_frame(a, C.KIND_RIO).to_excel(xl, sheet_name="Rio Markers", index=False)
        display_frame(a, C.KIND_EU).to_excel(xl, sheet_name="EU Taxonomy", index=False)
        _fit(xl)
    return out.getvalue()


def comparison_workbook(a: Analysis, b: Analysis, comparison: Comparison, rows: List[List[str]]) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        pd.DataFrame(rows, columns=["Measure", "Budget A: " + a.name, "Budget B: " + b.name]).to_excel(xl, sheet_name="Comparison", index=False)
        pd.DataFrame([["Budget A", comparison.scores["A"], comparison.reasons["A"]], ["Budget B", comparison.scores["B"], comparison.reasons["B"]],
                      ["Overall", "", comparison.summary]], columns=["Budget", "Score", "Why"]).to_excel(xl, sheet_name="Scores", index=False)
        _fit(xl)
    return out.getvalue()


def file_stem(name: str) -> str:
    stem = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in name).strip().replace(" ", "_")
    return stem[:60] or "budget"
