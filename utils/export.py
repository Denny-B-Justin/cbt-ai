"""Excel workbooks for download, and the readable tables shown on screen."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from tagging.pipeline import Analysis, Comparison

from . import constants as C
from .formatting import fmt_pct

NO_VALUE = "-"


def _amount_header(a: Analysis) -> str:
    unit = a.info.unit_text
    return "Amount (%s)" % unit if unit else "Amount"


def display_frame(a: Analysis) -> pd.DataFrame:
    """The tagged lines with plain column names, the way people read them."""
    df = a.lines
    out = pd.DataFrame({"Line": df["line"], "Page": df["page"], "Ministry": df["ministry"], "Budget line": df["programme"],
                        _amount_header(a): df["amount"]})
    out["CBT code"] = df["cbt_code"].map(lambda c: C.CODE_LABELS.get(c, C.NOT_TAGGED))
    out["Climate level"] = df["climate_level"].map(lambda lv: C.LEVEL_LABELS.get(int(lv), C.NOT_TAGGED))
    out["Climate part"] = df["climate_amount"]
    out["Mitigation part"] = df["mitigation_amount"]
    out["Adaptation part"] = df["adaptation_amount"]
    out["Sector"] = df["sector"]
    out["Function"] = df["function"]
    out["Confidence"] = df["confidence"].str.capitalize()
    out["Decided by"] = df["decided_by"]
    out["Why"] = df["rationale"]
    return out


def summary_rows(a: Analysis) -> list[list[Any]]:
    s = a.summary
    basis = "amount" if s["basis"] == "amount" else "number of lines"
    rows: list[list[Any]] = [
        ["General", "Budget lines assessed", s["lines"]], ["General", "Shares are based on", basis],
        ["Shares", "Climate share (each climate-tagged line counts at its level)", fmt_pct(s["climate_share"])],
        ["Shares", "Mitigation", fmt_pct(s["mitigation_share"])], ["Shares", "Adaptation", fmt_pct(s["adaptation_share"])],
        ["Lines", "Climate-tagged lines", s["tagged_lines"]]]
    rows += [["Lines", C.CODE_LABELS[c], s["code_lines"][c]] for c in C.CBT_CODES]
    rows += [["Levels", "%s, share of the climate spend" % C.LEVEL_LABELS[lv], fmt_pct(s["level_of_climate"][lv])] for lv in C.LEVELS]
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


def _about(a: Analysis) -> list[list[Any]]:
    return [["Document", a.name], ["Method", C.METHOD_SOURCE], ["Country", a.info.country or NO_VALUE], ["Year", a.info.year or NO_VALUE],
            ["Currency and unit", a.info.unit_text or NO_VALUE], ["Pages read", a.pages],
            ["Prepared on", datetime.now(timezone.utc).strftime("%d %b %Y")],
            ["Note", "Tags are produced with the help of AI and should be reviewed before they are used."]]


def evaluation_workbook(a: Analysis) -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        pd.DataFrame(_about(a), columns=["Item", "Value"]).to_excel(xl, sheet_name="About", index=False)
        pd.DataFrame(summary_rows(a), columns=["Method", "Measure", "Value"]).to_excel(xl, sheet_name="Summary", index=False)
        display_frame(a).to_excel(xl, sheet_name="Budget lines", index=False)
        _fit(xl)
    return out.getvalue()


def comparison_workbook(a: Analysis, b: Analysis, comparison: Comparison, rows: list[list[str]]) -> bytes:
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
