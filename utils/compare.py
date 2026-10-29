"""Compare Budget page: two documents side by side, with an overall score on the last row."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from tagging.pipeline import Analysis, AnalysisError, Comparison, analyse_document, compare_budgets

from . import charts, components as ui, export, session
from . import constants as C
from .evaluate import job_notice, loader_for, money, not_ready_notice, read_upload
from .formatting import fmt_int, fmt_pct

log = logging.getLogger(__name__)

SLOT = "compare"
KEYS = ("A", "B")
STEPS = [("Add", "two budget documents"), ("Wait", "while we read and tag both"), ("Compare", "the results and scores")]


@dataclass
class Row:
    label: str
    a: str = ""
    b: str = ""
    better: str = ""
    sub_a: str = ""
    sub_b: str = ""
    group: bool = False


def _size_text(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024) if n >= 1024 * 1024 else "%d KB" % max(1, round(n / 1024))


def file_chip(name: str, size: int) -> html.Div:
    return html.Div(className="file-chip", children=[html.Strong(name), ui.chip("Ready", "ok"), html.Span(_size_text(size), className="muted"), ui.token()])


# ── layout ──────────────────────────────────────────────────────────────────
def _slot(key: str, sid: str) -> html.Div:
    k = key.lower()
    upload = session.get_upload(sid, key)
    return html.Div(className="slot", children=[
        html.Div(className="slot-title", children=[html.Span(key, className="slot-mark slot-" + k), "Budget " + key]),
        ui.dropzone("compare-upload-" + k, "Drop budget %s here" % key),
        ui.status_slot("compare-file-" + k, file_chip(upload.name, len(upload.data)) if upload else None)])


def layout(sid: str) -> html.Div:
    return html.Div([
        ui.page_intro("Compare Budget",
                      "Add two budget documents and see them side by side. The last row of the table gives each budget an overall climate score.",
                      eyebrow="Climate budget tagging"),
        ui.section([
            html.Ol(className="stepper", children=[html.Li([html.Span(str(i), className="step-n"), html.Div([html.Strong(a), html.Span(" " + b)])])
                                                    for i, (a, b) in enumerate(STEPS, start=1)]),
            html.Div(className="stack", children=[
                ui.step_card(1, "Add the two budgets", "PDF or Word documents. They can be project budgets or larger budgets; the two do not need to match.", [
                    html.Div(className="upload-row", children=[_slot(k, sid) for k in KEYS]),
                    html.Div(className="privacy-note", children=[ui.icon("lock"), html.Span(ui.PRIVACY_TEXT)]),
                    html.Div(className="actions", children=[
                        html.Button("Compare budgets", id="compare-run", n_clicks=0, className="btn btn-primary"),
                        html.Button("Stop", id="compare-cancel", n_clicks=0, className="btn btn-outline", style={"display": "none"})]),
                    html.Div(id="compare-message")]),
                html.Div(id="compare-progress"),
                html.Div(id="compare-results")])], "tight"),
        dcc.Store(id="compare-job"), dcc.Interval(id="compare-poll", interval=1000, disabled=True), dcc.Download(id="compare-download")])


# ── the table ───────────────────────────────────────────────────────────────
def _better(a: Optional[float], b: Optional[float], higher: bool = True) -> str:
    if a is None or b is None or round(a, 3) == round(b, 3):
        return ""
    return "A" if (a > b) == higher else "B"


def _objectives(s: Dict[str, Any]) -> tuple:
    shares = {k: v for k, v in (s.get("objective_shares") or {}).items() if (v or 0) >= 0.01}
    names = [C.EU_LABELS[k] for k in sorted(shares, key=shares.get, reverse=True)]
    return len(shares), ", ".join(names[:3]) + (" …" if len(names) > 3 else "")


def build_rows(a: Analysis, b: Analysis) -> List[Row]:
    ra, rb, ea, eb = a.rio_summary, b.rio_summary, a.eu_summary, b.eu_summary
    na, sa = _objectives(ea)
    nb, sb = _objectives(eb)

    def pct(label: str, key: str, x: Dict[str, Any], y: Dict[str, Any], higher: Optional[bool] = None) -> Row:
        return Row(label, fmt_pct(x[key]), fmt_pct(y[key]), _better(x[key], y[key], higher) if higher is not None else "")

    return [
        Row("The documents", group=True),
        Row("Country and year", a.subtitle or "-", b.subtitle or "-"),
        Row("Budget lines assessed", fmt_int(ra["lines"]), fmt_int(rb["lines"])),
        Row("Total amount (own currency)", money(a, ra["total_amount"]) if ra["has_amount"] else "-",
            money(b, rb["total_amount"]) if rb["has_amount"] else "-"),
        Row("Rio Markers", group=True),
        pct("Climate share (Rio-weighted)", "weighted_share", ra, rb, True),
        pct("Principal (2)", "principal_share", ra, rb, True),
        pct("Significant (1)", "significant_share", ra, rb),
        pct("Climate change mitigation", "mitigation_share", ra, rb),
        pct("Climate change adaptation", "adaptation_share", ra, rb),
        Row("EU Taxonomy", group=True),
        pct("Green share", "green_share", ea, eb, True),
        pct("Brown share (lower is better)", "brown_share", ea, eb, False),
        Row("Environmental objectives served", "%d of %d" % (na, len(C.EU_OBJECTIVES)), "%d of %d" % (nb, len(C.EU_OBJECTIVES)),
            _better(float(na), float(nb)), sa, sb)]


def _head(key: str, a: Analysis) -> html.Th:
    return html.Th(html.Div(className="head-name", children=[
        html.Span(key, className="slot-mark slot-" + key.lower()),
        html.Div([a.name, *[html.Span(t, className="head-sub") for t in (a.subtitle, a.filename) if t]])]))


def _cell(text: str, sub: str, better: bool) -> html.Td:
    return html.Td(className="is-better" if better else "", children=[text, html.Span(sub, className="cell-sub") if sub else None])


def compare_table(a: Analysis, b: Analysis, comparison: Comparison, rows: List[Row]) -> html.Div:
    body: List[Any] = []
    for r in rows:
        if r.group:
            body.append(html.Tr(className="group", children=html.Th(r.label, colSpan=3)))
        else:
            body.append(html.Tr([html.Th(r.label, scope="row"), _cell(r.a, r.sub_a, r.better == "A"), _cell(r.b, r.sub_b, r.better == "B")]))
    sa, sb = comparison.scores["A"], comparison.scores["B"]

    def score(value: int, other: int) -> html.Td:
        return html.Td(className="is-better" if value > other else "", children=[str(value), html.Small(" / 100")])

    body.append(html.Tr(className="score", children=[html.Th("Overall climate score", scope="row"), score(sa, sb), score(sb, sa)]))
    return html.Div(className="compare-wrap", children=html.Table(className="compare-table", children=[
        html.Thead(html.Tr([html.Th("Measure"), _head("A", a), _head("B", b)])), html.Tbody(body)]))


def text_rows(rows: List[Row], comparison: Comparison) -> List[List[str]]:
    out = [[r.label, r.a, r.b] for r in rows if not r.group]
    out.append(["Overall climate score (out of 100)", str(comparison.scores["A"]), str(comparison.scores["B"])])
    return out


# ── results ─────────────────────────────────────────────────────────────────
def results_view(result: Dict[str, Any]) -> html.Div:
    a, b, comparison = result["A"], result["B"], result["comparison"]
    rows = build_rows(a, b)
    notes = [ui.notice("warn" if i["level"] == "warn" else "info", "Budget %s: %s" % (k, i["message"]))
             for k, x in (("A", a), ("B", b)) for i in x.issues]
    if a.rio_summary["basis"] != b.rio_summary["basis"]:
        notes.append(ui.notice("warn", "One budget has amounts and the other does not, so its shares are based on the number of budget lines. "
                               "Read the two columns with care.", "The shares are not measured the same way"))
    ea, eb = a.eu_summary, b.eu_summary
    labels = ["Rio-weighted share", "Principal (2)", "Significant (1)", "EU green", "EU brown"]
    ra, rb = a.rio_summary, b.rio_summary
    shares_a = [ra["weighted_share"], ra["principal_share"], ra["significant_share"], ea["green_share"], ea["brown_share"]]
    shares_b = [rb["weighted_share"], rb["principal_share"], rb["significant_share"], eb["green_share"], eb["brown_share"]]
    objectives = [C.EU_LABELS[k] for k in C.EU_OBJECTIVES]
    return html.Div(className="results", children=[
        html.Div(className="result-head", children=[
            html.Div([html.H3("Budget A and Budget B side by side", className="result-title"),
                      html.Div("%s and %s" % (a.name, b.name), className="muted")]),
            html.Button("Download comparison (.xlsx)", id="compare-download-btn", n_clicks=0, className="btn btn-outline")]),
        *notes,
        ui.notice("info", comparison.summary, "In short") if comparison.summary else None,
        compare_table(a, b, comparison, rows),
        html.Div(className="compare-reasons", children=[
            html.Div(className="reason reason-" + k.lower(), children=[html.Strong("Budget %s · %d / 100" % (k, comparison.scores[k])),
                                                                       comparison.reasons[k]]) for k in KEYS]),
        html.Div(className="chart-grid", children=[
            ui.chart_card("Climate shares", charts.fig_compare(labels, shares_a, shares_b, "Share of the budget")),
            ui.chart_card("Environmental objectives served", charts.fig_compare(
                objectives, [ea["objective_shares"].get(k) for k in C.EU_OBJECTIVES], [eb["objective_shares"].get(k) for k in C.EU_OBJECTIVES],
                "Share of the budget (a line can serve several)"))])])


# ── callbacks ───────────────────────────────────────────────────────────────
def _register_upload(key: str) -> None:
    @callback(Output("compare-file-" + key.lower(), "children"), Input("compare-upload-" + key.lower(), "contents"),
              State("compare-upload-" + key.lower(), "filename"), State("session", "data"), prevent_initial_call=True)
    def keep_file(contents: Optional[str], name: Optional[str], sid: str):
        if not contents:
            raise PreventUpdate
        data, error = read_upload(contents, name)
        if data is None:
            session.drop_upload(sid, key)
            return error
        session.set_upload(sid, key, name or "document", data)
        return file_chip(name or "document", len(data))


for _key in KEYS:
    _register_upload(_key)


def _work(files: Dict[str, session.Upload]) -> session.Work:
    def run(progress, cancelled):
        analyses: Dict[str, Analysis] = {}
        for key in KEYS:
            def step(stage: str, detail: str = "", key: str = key) -> None:
                progress(stage, "Budget %s%s" % (key, " · " + detail if detail else ""))
            try:
                analyses[key] = analyse_document(files[key].data, files[key].name, step, cancelled)
            except AnalysisError as exc:
                raise AnalysisError("Budget %s: %s" % (key, exc)) from exc
        progress(C.STAGE_SCORE)
        return {"A": analyses["A"], "B": analyses["B"], "comparison": compare_budgets(analyses["A"], analyses["B"], cancelled)}
    return run


@callback(Output("compare-message", "children"), Output("compare-job", "data"),
          Input("compare-run", "n_clicks"), Input("compare-cancel", "n_clicks"), State("session", "data"), prevent_initial_call=True)
def start_or_stop(run: int, _cancel: int, sid: str):
    if ctx.triggered_id == "compare-cancel":
        session.cancel_job(sid, SLOT)
        return ui.token(), {"t": time.time()}
    if not run:
        raise PreventUpdate
    problem = not_ready_notice()
    if problem is not None:
        return problem, no_update
    files = {k: session.get_upload(sid, k) for k in KEYS}
    missing = [k for k in KEYS if files[k] is None]
    if missing:
        return ui.notice("warn", "Please add %s first." % ("both budgets" if len(missing) == 2 else "budget " + missing[0]), "One more step"), no_update
    try:
        session.start_job(sid, SLOT, _work(files))
    except session.Busy:
        return ui.notice("warn", session.BUSY_ERROR, "Please wait a moment"), no_update
    return ui.token(), {"t": time.time()}


@callback(Output("compare-progress", "children"), Output("compare-results", "children"), Output("compare-poll", "disabled"),
          Output("compare-cancel", "style"), Input("compare-job", "data"), Input("compare-poll", "n_intervals"), State("session", "data"))
def show_job(_job: Any, _ticks: int, sid: str):
    session.touch(sid)
    job = session.current_job(sid, SLOT)
    hidden, shown = {"display": "none"}, {"display": "inline-flex"}
    if job is None:
        return None, None, True, hidden
    if job.state == session.RUNNING:
        return loader_for(job), None, False, shown
    if job.state == session.DONE:
        try:
            return None, results_view(job.result), True, hidden
        except Exception:
            log.exception("Could not draw the comparison")
            return ui.notice("error", session.GENERIC_ERROR, "We could not show the comparison"), None, True, hidden
    return job_notice(job), None, True, hidden


@callback(Output("compare-download", "data"), Input("compare-download-btn", "n_clicks"), State("session", "data"), prevent_initial_call=True)
def download(clicks: int, sid: str):
    job = session.current_job(sid, SLOT)
    if not clicks or not job or job.state != session.DONE:
        raise PreventUpdate
    result = job.result
    rows = text_rows(build_rows(result["A"], result["B"]), result["comparison"])
    return dcc.send_bytes(export.comparison_workbook(result["A"], result["B"], result["comparison"], rows), "budget_comparison.xlsx")
