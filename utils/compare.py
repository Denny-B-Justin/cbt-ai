"""Compare Budget page: two documents side by side, with an overall score on the last row."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

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
                ui.step_card(1, "Add the two budgets", "PDF, Word or Excel documents. They can be project budgets or larger budgets; the two do not need to match.", [
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
def _better(a: float | None, b: float | None, higher: bool = True) -> str:
    if a is None or b is None or round(a, 3) == round(b, 3):
        return ""
    return "A" if (a > b) == higher else "B"


def build_rows(a: Analysis, b: Analysis) -> list[Row]:
    sa, sb = a.summary, b.summary

    def pct(label: str, x: Any, y: Any, higher: bool | None = None) -> Row:
        return Row(label, fmt_pct(x), fmt_pct(y), _better(x, y, higher) if higher is not None else "")

    def lines(label: str, x: int, y: int) -> Row:
        return Row(label, fmt_int(x), fmt_int(y))

    def sectors(s: dict[str, Any]) -> tuple[str, str]:
        names = s["climate_sectors"]
        return "%d" % len(names), ", ".join(names[:3]) + (" …" if len(names) > 3 else "")

    (na, ta), (nb, tb) = sectors(sa), sectors(sb)
    top = C.LEVELS[0]
    return [
        Row("The documents", group=True),
        Row("Country and year", a.subtitle or "-", b.subtitle or "-"),
        lines("Budget lines assessed", sa["lines"], sb["lines"]),
        Row("Total amount (own currency)", money(a, sa["total_amount"]) if sa["has_amount"] else "-",
            money(b, sb["total_amount"]) if sb["has_amount"] else "-"),
        Row("Climate spending", group=True),
        pct("Climate share (level-weighted)", sa["climate_share"], sb["climate_share"], True),
        pct("Mitigation", sa["mitigation_share"], sb["mitigation_share"]),
        pct("Adaptation", sa["adaptation_share"], sb["adaptation_share"]),
        pct("Climate spend at levels 100 and 70", sa["high_level_share"], sb["high_level_share"], True),
        pct("Climate spend at %s" % C.LEVEL_LABELS[top].lower(), sa["level_of_climate"][top], sb["level_of_climate"][top]),
        Row("Climate-tagged lines", group=True),
        lines("All climate-tagged lines", sa["tagged_lines"], sb["tagged_lines"]),
        *[lines(C.CODE_LABELS[c], sa["code_lines"][c], sb["code_lines"][c]) for c in C.CBT_CODES],
        Row("Sectors with climate spending", na, nb, _better(float(na), float(nb)), ta, tb)]


def _head(key: str, a: Analysis) -> html.Th:
    return html.Th(html.Div(className="head-name", children=[
        html.Span(key, className="slot-mark slot-" + key.lower()),
        html.Div([a.name, *[html.Span(t, className="head-sub") for t in (a.subtitle, a.filename) if t]])]))


def _cell(text: str, sub: str, better: bool) -> html.Td:
    return html.Td(className="is-better" if better else "", children=[text, html.Span(sub, className="cell-sub") if sub else None])


def compare_table(a: Analysis, b: Analysis, comparison: Comparison, rows: list[Row]) -> html.Div:
    body: list[Any] = []
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


def text_rows(rows: list[Row], comparison: Comparison) -> list[list[str]]:
    out = [[r.label, r.a, r.b] for r in rows if not r.group]
    out.append(["Overall climate score (out of 100)", str(comparison.scores["A"]), str(comparison.scores["B"])])
    return out


# ── results ─────────────────────────────────────────────────────────────────
def results_view(result: dict[str, Any]) -> html.Div:
    a, b, comparison = result["A"], result["B"], result["comparison"]
    rows = build_rows(a, b)
    notes = [ui.notice("warn" if i["level"] == "warn" else "info", "Budget {}: {}".format(k, i["message"]))
             for k, x in (("A", a), ("B", b)) for i in x.issues]
    if a.summary["basis"] != b.summary["basis"]:
        notes.append(ui.notice("warn", "One budget has amounts and the other does not, so its shares are based on the number of budget lines. "
                               "Read the two columns with care.", "The shares are not measured the same way"))
    sa, sb = a.summary, b.summary
    labels = ["Climate share", "Mitigation", "Adaptation"]
    shares_a = [sa["climate_share"], sa["mitigation_share"], sa["adaptation_share"]]
    shares_b = [sb["climate_share"], sb["mitigation_share"], sb["adaptation_share"]]
    levels = [C.LEVEL_LABELS[lv] for lv in C.LEVELS]
    return html.Div(className="results", children=[
        html.Div(className="result-head", children=[
            html.Div([html.H3("Budget A and Budget B side by side", className="result-title"),
                      html.Div("{} and {}".format(a.name, b.name), className="muted")]),
            html.Button("Download comparison (.xlsx)", id="compare-download-btn", n_clicks=0, className="btn btn-outline")]),
        *notes,
        ui.notice("info", comparison.summary, "In short") if comparison.summary else None,
        compare_table(a, b, comparison, rows),
        html.Div(className="compare-reasons", children=[
            html.Div(className="reason reason-" + k.lower(), children=[html.Strong("Budget %s · %d / 100" % (k, comparison.scores[k])),
                                                                       comparison.reasons[k]]) for k in KEYS]),
        html.Div(className="chart-grid", children=[
            ui.chart_card("Climate shares", charts.fig_compare(labels, shares_a, shares_b, "Share of the budget")),
            ui.chart_card("Where the climate spend comes from", charts.fig_compare(
                levels, [sa["level_of_climate"][lv] for lv in C.LEVELS], [sb["level_of_climate"][lv] for lv in C.LEVELS],
                "Share of each budget's climate spend"))])])


# ── callbacks ───────────────────────────────────────────────────────────────
def _register_upload(key: str) -> None:
    @callback(Output("compare-file-" + key.lower(), "children"), Input("compare-upload-" + key.lower(), "contents"),
              State("compare-upload-" + key.lower(), "filename"), State("session", "data"), prevent_initial_call=True)
    def keep_file(contents: str | None, name: str | None, sid: str):
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


def _work(files: dict[str, session.Upload]) -> session.Work:
    def run(progress, cancelled):
        analyses: dict[str, Analysis] = {}
        for key in KEYS:
            def step(stage: str, detail: str = "", key: str = key) -> None:
                progress(stage, "Budget {}{}".format(key, " · " + detail if detail else ""))
            try:
                analyses[key] = analyse_document(files[key].data, files[key].name, step, cancelled)
            except AnalysisError as exc:
                raise AnalysisError("Budget {}: {}".format(key, exc)) from exc
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
