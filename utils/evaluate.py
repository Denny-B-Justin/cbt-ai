"""Evaluate Budget page: upload one document, see its climate tags and charts."""

from __future__ import annotations

import base64
import binascii
import logging
import time
from typing import Any

from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

import constants as C
import page_constants as P
from ai import client
from tagging.metrics import NOT_GIVEN
from tagging.pipeline import Analysis, analyse_document

from . import charts, components as ui, export, session
from .formatting import fmt_amount, fmt_int, fmt_money, fmt_pct, plural, short_text

log = logging.getLogger(__name__)

SLOT = "evaluate"
LOADER_HINT = "This can take a few minutes for a long document. Please keep this page open."
STEPS = [("Upload", "your budget document"), ("Wait", "while we read and tag it"), ("Review", "the results")]


# ── shared helpers (also used by the compare page) ──────────────────────────
def read_upload(contents: str | None, filename: str | None) -> tuple[bytes | None, html.Div | None]:
    """Decode a dcc.Upload payload. Returns (bytes, None) or (None, error notice)."""
    if not contents or not filename:
        return None, None
    if not filename.lower().endswith(C.ALLOWED_SUFFIXES):
        return None, ui.notice("error", "Please upload a PDF, a Word (.docx) or an Excel (.xlsx) file.", "This file type is not supported")
    try:
        data = base64.b64decode(contents.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError):
        return None, ui.notice("error", "The file could not be read. Please try again.", "Upload failed")
    if len(data) > C.max_upload_bytes():
        return None, ui.notice("error", "Please upload a file smaller than %d MB." % (C.max_upload_bytes() // (1024 * 1024)), "File too large")
    if not data:
        return None, ui.notice("error", "The file is empty.", "Upload failed")
    return data, None


def not_ready_notice(model: str | None = None) -> html.Div | None:
    """A notice when no model, or the chosen one, can be used; None when all is well."""
    if not client.is_configured():
        return ui.notice("error", "The analysis service is not set up yet. Please ask the person who manages this tool to finish its "
                         "set-up by adding an AI provider's key.", "Not available")
    if model is not None and model not in client.available_models():
        return ui.notice("warn", "%s is not available. Please choose another AI model." % client.model_label(model), "Choose another model")
    return None


def model_options() -> list[dict[str, Any]]:
    """The models of constants.MODELS whose provider has an API key, in that order."""
    return [{"label": C.MODELS_BY_ID[m].label, "value": m} for m in client.available_models()]


def model_picker(component_id: str) -> html.Div:
    return ui.model_picker(component_id, model_options(), client.default_model())


def loader_for(job: session.Job, hint: str = LOADER_HINT) -> html.Div:
    return ui.loader(job.stage, job.detail, hint)


def job_notice(job: session.Job) -> html.Div | None:
    if job.state == session.FAILED:
        return ui.notice("error", job.error, "We could not finish the analysis")
    if job.state == session.CANCELLED:
        return ui.notice("info", "The analysis was stopped. Nothing has been kept.", "Stopped")
    return None


def money(a: Analysis, value: Any) -> str:
    return fmt_money(value, a.info.currency, a.info.unit)


def basis_text(summary: dict[str, Any]) -> str:
    return "of amount" if summary["basis"] == "amount" else "of lines"


# ── layout ──────────────────────────────────────────────────────────────────
def layout() -> html.Div:
    return html.Div([
        ui.page_intro("Evaluate Budget",
                      "Upload a budget document. We read it, tag every budget line with the Georgian climate budget tagging method "
                      "(CM, CA or CB, at level 100, 70, 40 or 20), and show how much of the budget is climate spending.",
                      eyebrow="Climate budget tagging"),
        ui.section(_body(), "tight"),
        dcc.Store(id="eval-job"), dcc.Interval(id="eval-poll", interval=1000, disabled=True), dcc.Download(id="eval-download")])


def _body() -> Any:
    return [
        html.Ol(className="stepper", children=[html.Li([html.Span(str(i), className="step-n"), html.Div([html.Strong(a), html.Span(" " + b)])])
                                                for i, (a, b) in enumerate(STEPS, start=1)]),
        html.Div(className="stack", children=[
            ui.step_card(1, "Upload your budget", "A PDF, Word or Excel document. Budgets of any length work, from a one-page project sheet to a full national budget.", [
                model_picker("eval-model"),
                ui.dropzone("eval-upload"),
                html.Div(className="privacy-note", children=[ui.icon("lock"), html.Span(ui.PRIVACY_TEXT)]),
                ui.status_slot("eval-message")]),
            html.Div(id="eval-progress"),
            html.Div(className="actions", children=html.Button("Stop", id="eval-cancel", n_clicks=0, className="btn btn-outline",
                                                              style={"display": "none"})),
            html.Div(id="eval-results")])]


# ── results ─────────────────────────────────────────────────────────────────
def kpi_note(a: Analysis) -> str:
    return " · ".join(p for p in (plural(a.summary["lines"], "budget line"), plural(a.pages, "page"),
                                  "%s in total" % money(a, a.summary["total_amount"]) if a.summary["has_amount"] else "",
                                  "tagged by %s" % a.model_label if a.model else "") if p)


TOP = 12


def _known(table: Any, unknown: str = NOT_GIVEN) -> Any:
    return table[table.index != unknown]


def _names(index: Any, limit: int = 42) -> list[str]:
    return [short_text(k, limit) for k in index]


def charts_section(a: Analysis) -> html.Div:
    s = a.summary
    basis, by_amount = basis_text(s), s["basis"] == "amount"
    vfmt = fmt_amount if by_amount else (lambda v: "%s lines" % f"{float(v):,.1f}".rstrip("0").rstrip("."))
    axis = (("Amount (%s)" % a.info.unit_text) if a.info.unit_text else "Amount") if by_amount else "Number of lines"
    unit = s["basis"]
    mit, ada = ("Mitigation", P.MITIGATION_COLOR), ("Adaptation", P.ADAPTATION_COLOR)
    levels = list(C.LEVELS)
    lv = s["by_level"]

    def split(table: Any) -> list:
        return [(mit[0], table["mitigation"], mit[1]), (ada[0], table["adaptation"], ada[1])]

    def shares(table: Any) -> list:
        return [(mit[0], table["mitigation_share"], mit[1]), (ada[0], table["adaptation_share"], ada[1])]

    def composition(table: Any) -> Any:
        table = table[table["climate"] > 0]
        return charts.fig_stacked_h(_names(table.index), [(mit[0], table["mitigation"] / table["climate"], mit[1]),
                                                          (ada[0], table["adaptation"] / table["climate"], ada[1])],
                                    pct=True, inside=True, end_text=[vfmt(v) for v in table["climate"]],
                                    title="Share of the climate spend (climate amount at the end)")

    def by_level(table: Any) -> Any:
        table = table.loc[table.sum(axis=1).sort_values(ascending=False).index[:TOP]]
        table = table[table.sum(axis=1) > 0]
        return charts.fig_stacked_h(_names(table.index), [(C.LEVEL_LABELS[L], table[L], P.LEVEL_COLORS[L]) for L in levels],
                                    vfmt, title=axis)

    ministries = _known(s["by_ministry"])
    spenders = ministries[ministries["climate"] > 0].head(TOP)
    largest = ministries[ministries["budget"] > 0].sort_values("budget", ascending=False).head(TOP).sort_values("climate_share", ascending=False)
    functions = _known(s["by_function"], "Not known")
    functions = functions[functions["budget"] > 0].sort_values("climate_share", ascending=False).head(TOP)
    sectors = s["by_sector"].head(TOP)
    no_ministry = charts.empty_figure("The document does not name ministries")
    methods = s["by_method"]
    clim_levels = lv[lv["climate"] > 0]
    counted = [(L, lv.at[L, "climate"], lv.at[L, "budget"]) for L in levels]

    cards = [
        ui.chart_card("Share of the total budget", charts.fig_donut(
            [(mit[0], s["mitigation_share"], mit[1]), (ada[0], s["adaptation_share"], ada[1]),
             ("Not counted as climate", 1.0 - (s["climate_share"] or 0.0), P.NO_DATA_COLOR)], unit),
            "Each climate-tagged line counts at its level; a line with both aims is split half and half."),
        ui.chart_card("Budget lines by CBT code", charts.fig_donut(
            [(C.CODE_LABELS[c], s["code_lines"][c], P.CODE_COLORS[c]) for c in C.CBT_CODES]
            + [(C.NOT_TAGGED, s["lines"] - s["tagged_lines"], P.NO_DATA_COLOR)], "lines"), "Number of lines"),
        ui.chart_card("Split of the climate spend", charts.fig_donut(
            [(mit[0], s["mitigation"], mit[1]), (ada[0], s["adaptation"], ada[1])], "climate spend"),
            "Climate spend: %s" % vfmt(s["climate"])),
        ui.chart_card("Where the climate spend comes from", charts.fig_donut(
            [(C.LEVEL_LABELS[L], lv.at[L, "climate"], P.LEVEL_COLORS[L]) for L in levels], "climate spend"),
            "Climate spend by level"),
        ui.chart_card("Climate spend by sector", charts.fig_stacked_h(_names(sectors.index), split(sectors), vfmt, title=axis)),
        ui.chart_card("Top ministries by climate spend",
                      charts.fig_stacked_h(_names(spenders.index), split(spenders), vfmt, title=axis) if len(spenders) else no_ministry),
        ui.chart_card("Climate share of each function", charts.fig_stacked_h(
            _names(functions.index), shares(functions), pct=True, title="Share of the function's own budget"),
            "Government functions (COFOG divisions)"),
        ui.chart_card("Climate share of the %d largest ministries" % TOP, charts.fig_stacked_h(
            _names(largest.index), shares(largest), pct=True, title="Share of the ministry's own budget") if len(largest) else no_ministry),
        ui.chart_card("Budget and climate part at each level", charts.fig_stacked_h(
            [C.LEVEL_LABELS[L] for L in levels],
            [("Counted as climate", [c for _, c, _ in counted], [P.LEVEL_COLORS[L] for L in levels]),
             ("Not counted", [b - c for _, c, b in counted], P.NO_DATA_COLOR)],
            vfmt, title=axis, end_text=["%s · %s of %s" % (plural(int(lv.at[L, "lines"]), "line"), vfmt(c), vfmt(b)) for L, c, b in counted])),
        ui.chart_card("Climate amount by level and CBT code", charts.fig_level_code_heatmap(s["level_code"], vfmt)),
        ui.chart_card("Mitigation and adaptation share by level", composition(clim_levels.set_axis([C.LEVEL_LABELS[L] for L in clim_levels.index]))),
        ui.chart_card("Top ministries: mitigation and adaptation share",
                      composition(spenders.head(8)) if len(spenders) else no_ministry),
        ui.chart_card("Top ministries by climate spend, split by level",
                      by_level(_known(s["ministry_levels"])) if len(spenders) else no_ministry),
        ui.chart_card("Top sectors by climate spend, split by level", by_level(s["sector_levels"])),
        ui.chart_card("How each tag was decided (lines)", charts.fig_stacked_h(
            _names(methods.index, 50), [("Lines", methods["lines"], P.METHOD_COLOR)], fmt_int, title="Budget lines")),
        ui.chart_card("How each tag was decided (%s)" % ("amount" if by_amount else "weight"), charts.fig_stacked_h(
            _names(methods.index, 50), [("Budget", methods["budget"], P.METHOD_COLOR)], vfmt, title=axis))]

    floor = s["floor_lines"].head(10)
    if len(floor):
        cards.append(ui.chart_card(
            "Lines counted only for liveable or habitable wording", charts.fig_stacked_h(
                _names(floor["programme"], 60), [("Counted as climate (%d%%)" % C.FLOOR_LEVEL, floor["climate"], P.ADAPTATION_COLOR),
                                                 ("Not counted", floor["budget"] - floor["climate"], P.NO_DATA_COLOR)], vfmt, title=axis),
            "%s, %s counted as adaptation" % (plural(len(s["floor_lines"]), "line"), vfmt(s["floor_lines"]["climate"].sum())),
            cls="chart-wide"))

    lvc = s["level_of_climate"]
    return html.Div(className="result-col", children=[
        ui.kpi_strip([
            ui.kpi("Climate share", fmt_pct(s["climate_share"]), "level-weighted · " + basis, tone="primary"),
            ui.kpi("Mitigation", fmt_pct(s["mitigation_share"]), basis),
            ui.kpi("Adaptation", fmt_pct(s["adaptation_share"]), basis),
            ui.kpi("Climate-tagged lines", fmt_int(s["tagged_lines"]), "of %s" % fmt_int(s["lines"])),
            ui.kpi("At level 100", fmt_pct(lvc[100]), "of the climate spend"),
            ui.kpi("At level 20", fmt_pct(lvc[20]), "of the climate spend")]),
        html.Div(className="chart-grid", children=cards)])


def lines_table(a: Analysis) -> html.Div:
    df = export.display_frame(a)
    amount_col = [c for c in df.columns if c.startswith("Amount")][0]
    df = df.sort_values(amount_col, ascending=False, na_position="last")
    columns = [{"name": c, "id": c, **({"type": "numeric", "format": {"specifier": ",.1f"}} if c == amount_col or c.endswith(" part") else {})}
               for c in df.columns]
    rules = [{"if": {"filter_query": '{CBT code} contains "%s"' % code, "column_id": "CBT code"}, "color": colour, "fontWeight": "600"}
             for code, colour in P.CODE_COLORS.items()]
    return html.Div([html.Div("The largest lines come first. Use the boxes under the headings to search, or click a heading to sort.", className="table-note"),
                     ui.data_table(df, "eval-table", columns, conditional=rules)])


def results_view(a: Analysis) -> html.Div:
    head = html.Div(className="result-head", children=[
        html.Div([html.H3(a.name, className="result-title"),
                  html.Div(" · ".join(p for p in (a.subtitle, kpi_note(a)) if p), className="muted")]),
        html.Button("Download results (.xlsx)", id="eval-download-btn", n_clicks=0, className="btn btn-outline")])
    notes = [ui.notice("warn" if i["level"] == "warn" else "info", i["message"]) for i in a.issues]
    return html.Div(className="results", children=[
        head, *notes,
        html.P("Each climate-tagged line is marked CM (mitigation), CA (adaptation) or CB (both) and placed in one of four levels: "
               "100, 70, 40 or 20. The level is the part of the line counted as climate.", className="card-hint"),
        charts_section(a),
        html.Div("Tagged budget lines", className="subhead"),
        lines_table(a)])


# ── callbacks ───────────────────────────────────────────────────────────────
def _work(data: bytes, filename: str, model: str) -> session.Work:
    return lambda progress, cancelled: analyse_document(data, filename, progress, cancelled, model)


@callback(Output("eval-message", "children"), Output("eval-job", "data"),
          Input("eval-upload", "contents"), Input("eval-cancel", "n_clicks"),
          State("eval-upload", "filename"), State("eval-model", "value"), State("session", "data"), prevent_initial_call=True)
def start_or_stop(contents: str | None, _cancel: int, filename: str | None, model: str | None, sid: str):
    if ctx.triggered_id == "eval-cancel":
        session.cancel_job(sid, SLOT)
        return ui.token(), {"t": time.time()}
    if not contents:
        raise PreventUpdate
    model = model or client.default_model()
    problem = not_ready_notice(model)
    data, error = (None, problem) if problem else read_upload(contents, filename)
    if error is not None or data is None:
        return error, no_update
    try:
        session.start_job(sid, SLOT, _work(data, filename or "document", model))
    except session.Busy:
        return ui.notice("warn", session.BUSY_ERROR, "Please wait a moment"), no_update
    return ui.token(), {"t": time.time()}


@callback(Output("eval-progress", "children"), Output("eval-results", "children"), Output("eval-poll", "disabled"),
          Output("eval-cancel", "style"), Input("eval-job", "data"), Input("eval-poll", "n_intervals"), State("session", "data"))
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
            log.exception("Could not draw the results")
            return ui.notice("error", session.GENERIC_ERROR, "We could not show the results"), None, True, hidden
    return job_notice(job), None, True, hidden


@callback(Output("eval-download", "data"), Input("eval-download-btn", "n_clicks"), State("session", "data"), prevent_initial_call=True)
def download(clicks: int, sid: str):
    job = session.current_job(sid, SLOT)
    if not clicks or not job or job.state != session.DONE:
        raise PreventUpdate
    a: Analysis = job.result
    return dcc.send_bytes(export.evaluation_workbook(a), "climate_tagging_%s.xlsx" % export.file_stem(a.name))
