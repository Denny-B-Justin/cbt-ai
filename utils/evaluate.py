"""Evaluate Budget page: upload one document, see the Rio Markers, EU Taxonomy and Georgian Taxonomy results."""

from __future__ import annotations

import base64
import binascii
import logging
import time
from typing import Any

from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from ai import client
from tagging.georgia import NOT_GIVEN
from tagging.pipeline import Analysis, analyse_document

from . import charts, components as ui, export, session
from . import constants as C
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


def not_ready_notice() -> html.Div | None:
    if client.is_configured():
        return None
    return ui.notice("error", "The analysis service is not set up yet. Please ask the person who manages this tool to finish its set-up.",
                     "Not available")


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
                      "Upload a budget document. We read it, tag every budget line against the Rio Markers, the EU Taxonomy and the Georgian Taxonomy, "
                      "and show how much of the budget supports climate goals.", eyebrow="Climate budget tagging"),
        ui.section(_body(), "tight"),
        dcc.Store(id="eval-job"), dcc.Interval(id="eval-poll", interval=1000, disabled=True), dcc.Download(id="eval-download")])


def _body() -> Any:
    return [
        html.Ol(className="stepper", children=[html.Li([html.Span(str(i), className="step-n"), html.Div([html.Strong(a), html.Span(" " + b)])])
                                                for i, (a, b) in enumerate(STEPS, start=1)]),
        html.Div(className="stack", children=[
            ui.step_card(1, "Upload your budget", "A PDF, Word or Excel document. Budgets of any length work, from a one-page project sheet to a full national budget.", [
                ui.dropzone("eval-upload"),
                html.Div(className="privacy-note", children=[ui.icon("lock"), html.Span(ui.PRIVACY_TEXT)]),
                ui.status_slot("eval-message")]),
            html.Div(id="eval-progress"),
            html.Div(className="actions", children=html.Button("Stop", id="eval-cancel", n_clicks=0, className="btn btn-outline",
                                                              style={"display": "none"})),
            html.Div(id="eval-results")])]


# ── results ─────────────────────────────────────────────────────────────────
def kpi_note(a: Analysis) -> str:
    return " · ".join(p for p in (plural(a.rio_summary["lines"], "budget line"), plural(a.pages, "page"),
                                  "%s in total" % money(a, a.rio_summary["total_amount"]) if a.rio_summary["has_amount"] else "") if p)


def rio_column(a: Analysis) -> html.Div:
    s, basis = a.rio_summary, basis_text(a.rio_summary)
    return html.Div(className="result-col", children=[
        html.H3("Rio Markers", className="card-title"),
        ui.kpi_strip([
            ui.kpi("Rio-weighted share", fmt_pct(s["weighted_share"]), "Principal 100%% · Significant %d%% · %s" % (C.RIO_WEIGHTS[1] * 100, basis), tone="primary"),
            ui.kpi("Principal (2)", fmt_pct(s["principal_share"]), basis),
            ui.kpi("Significant (1)", fmt_pct(s["significant_share"]), basis),
            ui.kpi("Lines with a marker", fmt_int(s["tagged_lines"]), "of %s" % fmt_int(s["lines"]))]),
        html.Div("How the budget splits by Rio level", className="subhead"),
        ui.graph(charts.fig_rio_donut(s["principal_share"] or 0, s["significant_share"] or 0, s["basis"])),
        html.Div("Mitigation and adaptation", className="subhead"),
        ui.graph(charts.fig_bar_h(["Climate change mitigation", "Climate change adaptation"],
                                  [s["mitigation_share"] or 0, s["adaptation_share"] or 0], pct=True,
                                  title="Share of %s with a Rio marker" % s["basis"], height=170)),
        html.Div("How each tag was decided", className="subhead"),
        ui.graph(charts.fig_methods(a.stats.get("rio_methods", {})))])


def eu_column(a: Analysis) -> html.Div:
    s, basis = a.eu_summary, basis_text(a.eu_summary)
    return html.Div(className="result-col", children=[
        html.H3("EU Taxonomy", className="card-title"),
        ui.kpi_strip([
            ui.kpi("Green share", fmt_pct(s["green_share"]), "any objective · " + basis, tone="primary"),
            ui.kpi("Brown share", fmt_pct(s["brown_share"]), basis, tone="brown"),
            ui.kpi("Green lines", fmt_int(s["tagged_lines"]), "of %s" % fmt_int(s["lines"]))]),
        html.Div("Green, brown and neutral spending", className="subhead"),
        ui.graph(charts.fig_tag_donut(s["green_share"] or 0, s["brown_share"] or 0, s["basis"])),
        html.Div("Environmental objectives served", className="subhead"),
        ui.graph(charts.fig_eu_objectives(s)),
        html.Div("How each tag was decided", className="subhead"),
        ui.graph(charts.fig_methods(a.stats.get("eu_methods", {})))])


GEO_TOP = 12


def _known(table: Any, unknown: str = NOT_GIVEN) -> Any:
    return table[table.index != unknown]


def _names(index: Any, limit: int = 42) -> list[str]:
    return [short_text(k, limit) for k in index]


def georgia_section(a: Analysis) -> html.Div | None:
    s = a.georgia_summary
    if not s:
        return None
    basis, by_amount = basis_text(s), s["basis"] == "amount"
    vfmt = fmt_amount if by_amount else (lambda v: "%s lines" % f"{float(v):,.1f}".rstrip("0").rstrip("."))
    axis = (("Amount (%s)" % a.info.unit_text) if a.info.unit_text else "Amount") if by_amount else "Number of lines"
    unit = s["basis"]
    mit, ada = ("Mitigation", C.MITIGATION_COLOR), ("Adaptation", C.ADAPTATION_COLOR)
    levels = list(C.GEO_LEVELS)
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
        table = table.loc[table.sum(axis=1).sort_values(ascending=False).index[:GEO_TOP]]
        table = table[table.sum(axis=1) > 0]
        return charts.fig_stacked_h(_names(table.index), [(C.GEO_LEVEL_LABELS[L], table[L], C.GEO_LEVEL_COLORS[L]) for L in levels],
                                    vfmt, title=axis)

    ministries = _known(s["by_ministry"])
    spenders = ministries[ministries["climate"] > 0].head(GEO_TOP)
    largest = ministries[ministries["budget"] > 0].sort_values("budget", ascending=False).head(GEO_TOP).sort_values("climate_share", ascending=False)
    functions = _known(s["by_function"], "Not known")
    functions = functions[functions["budget"] > 0].sort_values("climate_share", ascending=False).head(GEO_TOP)
    sectors = s["by_sector"].head(GEO_TOP)
    no_ministry = charts.empty_figure("The document does not name ministries")
    methods = s["by_method"]
    clim_levels = lv[lv["climate"] > 0]
    counted = [(L, lv.at[L, "climate"], lv.at[L, "budget"]) for L in levels]

    cards = [
        ui.chart_card("Share of the total budget", charts.fig_donut(
            [(mit[0], s["mitigation_share"], mit[1]), (ada[0], s["adaptation_share"], ada[1]),
             ("Not counted as climate", 1.0 - (s["climate_share"] or 0.0), C.NO_DATA_COLOR)], unit),
            "Each climate-tagged line counts at its level; a line with both aims is split half and half."),
        ui.chart_card("Budget lines by CBT code", charts.fig_donut(
            [(C.GEO_CODE_LABELS[c], s["code_lines"][c], C.GEO_CODE_COLORS[c]) for c in C.GEO_CODES]
            + [(C.GEO_NOT_TAGGED, s["lines"] - s["tagged_lines"], C.NO_DATA_COLOR)], "lines"), "Number of lines"),
        ui.chart_card("Split of the climate spend", charts.fig_donut(
            [(mit[0], s["mitigation"], mit[1]), (ada[0], s["adaptation"], ada[1])], "climate spend"),
            "Climate spend: %s" % vfmt(s["climate"])),
        ui.chart_card("Where the climate spend comes from", charts.fig_donut(
            [(C.GEO_LEVEL_LABELS[L], lv.at[L, "climate"], C.GEO_LEVEL_COLORS[L]) for L in levels], "climate spend"),
            "Climate spend by level"),
        ui.chart_card("Climate spend by sector", charts.fig_stacked_h(_names(sectors.index), split(sectors), vfmt, title=axis)),
        ui.chart_card("Top ministries by climate spend",
                      charts.fig_stacked_h(_names(spenders.index), split(spenders), vfmt, title=axis) if len(spenders) else no_ministry),
        ui.chart_card("Climate share of each function", charts.fig_stacked_h(
            _names(functions.index), shares(functions), pct=True, title="Share of the function's own budget"),
            "Government functions (COFOG divisions)"),
        ui.chart_card("Climate share of the %d largest ministries" % GEO_TOP, charts.fig_stacked_h(
            _names(largest.index), shares(largest), pct=True, title="Share of the ministry's own budget") if len(largest) else no_ministry),
        ui.chart_card("Budget and climate part at each level", charts.fig_stacked_h(
            [C.GEO_LEVEL_LABELS[L] for L in levels],
            [("Counted as climate", [c for _, c, _ in counted], [C.GEO_LEVEL_COLORS[L] for L in levels]),
             ("Not counted", [b - c for _, c, b in counted], C.NO_DATA_COLOR)],
            vfmt, title=axis, end_text=["%s · %s of %s" % (plural(int(lv.at[L, "lines"]), "line"), vfmt(c), vfmt(b)) for L, c, b in counted])),
        ui.chart_card("Climate amount by level and CBT code", charts.fig_geo_heatmap(s["level_code"], vfmt)),
        ui.chart_card("Mitigation and adaptation share by level", composition(clim_levels.set_axis([C.GEO_LEVEL_LABELS[L] for L in clim_levels.index]))),
        ui.chart_card("Top ministries: mitigation and adaptation share",
                      composition(spenders.head(8)) if len(spenders) else no_ministry),
        ui.chart_card("Top ministries by climate spend, split by level",
                      by_level(_known(s["ministry_levels"])) if len(spenders) else no_ministry),
        ui.chart_card("Top sectors by climate spend, split by level", by_level(s["sector_levels"])),
        ui.chart_card("How each tag was decided (lines)", charts.fig_stacked_h(
            _names(methods.index, 50), [("Lines", methods["lines"], C.METHOD_COLOR)], fmt_int, title="Budget lines")),
        ui.chart_card("How each tag was decided (%s)" % ("amount" if by_amount else "weight"), charts.fig_stacked_h(
            _names(methods.index, 50), [("Budget", methods["budget"], C.METHOD_COLOR)], vfmt, title=axis))]

    floor = s["floor_lines"].head(10)
    if len(floor):
        cards.append(ui.chart_card(
            "Lines counted only for liveable or habitable wording", charts.fig_stacked_h(
                _names(floor["programme"], 60), [("Counted as climate (%d%%)" % C.GEO_FLOOR_LEVEL, floor["climate"], C.ADAPTATION_COLOR),
                                                 ("Not counted", floor["budget"] - floor["climate"], C.NO_DATA_COLOR)], vfmt, title=axis),
            "%s, %s counted as adaptation" % (plural(len(s["floor_lines"]), "line"), vfmt(s["floor_lines"]["climate"].sum())),
            cls="chart-wide"))

    lvc = s["level_of_climate"]
    return html.Div(className="result-col", children=[
        html.H3(C.KIND_LABELS[C.KIND_GEO], className="card-title"),
        html.P("Climate Budget Tagging in Georgia (handbook, June 2025). Each climate-tagged line is marked CM (mitigation), CA (adaptation) "
               "or CB (both) and placed in one of four levels: 100, 70, 40 or 20. The level is the part of the line counted as climate.",
               className="card-hint"),
        ui.kpi_strip([
            ui.kpi("Climate share", fmt_pct(s["climate_share"]), "level-weighted · " + basis, tone="primary"),
            ui.kpi("Mitigation", fmt_pct(s["mitigation_share"]), basis),
            ui.kpi("Adaptation", fmt_pct(s["adaptation_share"]), basis),
            ui.kpi("Climate-tagged lines", fmt_int(s["tagged_lines"]), "of %s" % fmt_int(s["lines"])),
            ui.kpi("At level 100", fmt_pct(lvc[100]), "of the climate spend"),
            ui.kpi("At level 20", fmt_pct(lvc[20]), "of the climate spend")]),
        html.Div(className="chart-grid", children=cards)])


def lines_table(a: Analysis, kind: str) -> html.Div:
    df = export.display_frame(a, kind)
    amount_col = [c for c in df.columns if c.startswith("Amount")][0]
    df = df.sort_values(amount_col, ascending=False, na_position="last")
    columns = [{"name": c, "id": c, **({"type": "numeric", "format": {"specifier": ",.1f"}} if c == amount_col or c.endswith(" part") else {})} for c in df.columns]
    if kind == C.KIND_RIO:
        rules = [{"if": {"filter_query": '{Rio marker} contains "Principal"', "column_id": "Rio marker"}, "color": C.GREEN_COLOR, "fontWeight": "600"},
                 {"if": {"filter_query": '{Rio marker} contains "Significant"', "column_id": "Rio marker"}, "color": "#4FAE6F", "fontWeight": "600"}]
    elif kind == C.KIND_GEO:
        rules = [{"if": {"filter_query": '{CBT code} contains "%s"' % code, "column_id": "CBT code"}, "color": colour, "fontWeight": "600"}
                 for code, colour in C.GEO_CODE_COLORS.items()]
    else:
        rules = [{"if": {"filter_query": '{Climate tag} = "Green"', "column_id": "Climate tag"}, "color": C.GREEN_COLOR, "fontWeight": "600"},
                 {"if": {"filter_query": '{Climate tag} = "Brown"', "column_id": "Climate tag"}, "color": C.BROWN_COLOR, "fontWeight": "600"}]
    return html.Div([html.Div("The largest lines come first. Use the boxes under the headings to search, or click a heading to sort.", className="table-note"),
                     ui.data_table(df, "eval-table-%s" % kind, columns, conditional=rules)])


def results_view(a: Analysis) -> html.Div:
    head = html.Div(className="result-head", children=[
        html.Div([html.H3(a.name, className="result-title"),
                  html.Div(" · ".join(p for p in (a.subtitle, kpi_note(a)) if p), className="muted")]),
        html.Button("Download results (.xlsx)", id="eval-download-btn", n_clicks=0, className="btn btn-outline")])
    notes = [ui.notice("warn" if i["level"] == "warn" else "info", i["message"]) for i in a.issues]
    return html.Div(className="results", children=[
        head, *notes,
        html.Div(className="result-cols", children=[rio_column(a), eu_column(a)]),
        georgia_section(a),
        html.Div(className="subhead-row", children=[
            html.Div("Tagged budget lines", className="subhead"),
            dcc.RadioItems(id="eval-table-which", value=C.KIND_RIO, className="segmented", inputClassName="seg-input", labelClassName="seg-label",
                           options=[{"label": C.KIND_LABELS[k], "value": k} for k in C.KINDS])]),
        html.Div(id="eval-table-wrap", children=lines_table(a, C.KIND_RIO))])


# ── callbacks ───────────────────────────────────────────────────────────────
def _work(data: bytes, filename: str) -> session.Work:
    return lambda progress, cancelled: analyse_document(data, filename, progress, cancelled)


@callback(Output("eval-message", "children"), Output("eval-job", "data"),
          Input("eval-upload", "contents"), Input("eval-cancel", "n_clicks"),
          State("eval-upload", "filename"), State("session", "data"), prevent_initial_call=True)
def start_or_stop(contents: str | None, _cancel: int, filename: str | None, sid: str):
    if ctx.triggered_id == "eval-cancel":
        session.cancel_job(sid, SLOT)
        return ui.token(), {"t": time.time()}
    if not contents:
        raise PreventUpdate
    problem = not_ready_notice()
    data, error = (None, problem) if problem else read_upload(contents, filename)
    if error is not None or data is None:
        return error, no_update
    try:
        session.start_job(sid, SLOT, _work(data, filename or "document"))
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


@callback(Output("eval-table-wrap", "children"), Input("eval-table-which", "value"), State("session", "data"), prevent_initial_call=True)
def switch_table(kind: str, sid: str):
    job = session.current_job(sid, SLOT)
    if not job or job.state != session.DONE or kind not in C.KINDS:
        raise PreventUpdate
    return lines_table(job.result, kind)


@callback(Output("eval-download", "data"), Input("eval-download-btn", "n_clicks"), State("session", "data"), prevent_initial_call=True)
def download(clicks: int, sid: str):
    job = session.current_job(sid, SLOT)
    if not clicks or not job or job.state != session.DONE:
        raise PreventUpdate
    a: Analysis = job.result
    return dcc.send_bytes(export.evaluation_workbook(a), "climate_tagging_%s.xlsx" % export.file_stem(a.name))
