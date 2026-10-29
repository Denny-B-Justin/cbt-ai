"""Building blocks shared by every page. Class names are defined in assets/style.css."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from dash import dash_table, dcc, get_asset_url, html

from . import constants as C

GRAPH_CONFIG = {"displayModeBar": False, "responsive": True}
FOOTER_TEXT = "A World Bank initiative promoting digital tools for smarter budgets."
PRIVACY_TEXT = ("Your document is not stored and is removed when you close or refresh this page. "
                "It is read by an online AI service, so please do not upload confidential documents.")


def token() -> html.Span:
    """An invisible, always-different child, so a callback that has nothing to say still reports that it ran."""
    return html.Span(hidden=True, **{"data-t": str(time.time())})


def icon(name: str) -> html.Span:
    return html.Span(className="ico ico-" + name, **{"aria-hidden": "true"})


# ── page frame ──────────────────────────────────────────────────────────────
def header(current: str) -> html.Header:
    links = []
    for key, label, href in C.PAGES:
        cls = "nav-link" + (" is-current" if key == current else "")
        if key == C.PAGE_METHODOLOGY:
            links.append(html.A([label, icon("external")], href=href, target="_blank", rel="noopener", className=cls))
        else:
            links.append(dcc.Link(label, href=href, className=cls))
    return html.Header(className="app-header", children=html.Div(className="app-header-inner", children=[
        dcc.Link([html.Img(src=get_asset_url("cbt_logo.svg"), className="brand-mark", alt=""),
                  html.Span(C.APP_NAME, className="header-name")], href="?page=" + C.DEFAULT_PAGE, className="header-brand"),
        html.Nav(className="header-nav", **{"aria-label": "Main"}, children=links)]))


def footer() -> html.Footer:
    return html.Footer(className="site-footer", children=html.Div(className="site-footer-inner", children=html.Div(
        className="footer-about", children=[
            html.Img(src=get_asset_url("The-World-Bank-group-white.png"), className="footer-wb", alt="World Bank Group"),
            html.P(FOOTER_TEXT)])))


def page_shell(current: str, body: Any) -> html.Div:
    return html.Div(className="page", children=[header(current), html.Main(id="main", children=body), footer()])


def page_intro(title: str, lede: str, eyebrow: Optional[str] = None) -> html.Section:
    return html.Section(className="page-intro", children=html.Div(className="section-inner", children=[
        html.P(eyebrow, className="eyebrow") if eyebrow else None,
        html.H1(title, className="page-title"),
        html.P(lede, className="page-lede")]))


def section(children: Any, cls: str = "") -> html.Section:
    return html.Section(className=("section " + cls).strip(), children=html.Div(className="section-inner", children=children))


# ── cards and small parts ───────────────────────────────────────────────────
def step_card(n: int, title: str, hint: str, body: Any, cls: str = "") -> html.Div:
    return html.Div(className=("card " + cls).strip(), children=[
        html.Div(className="card-head", children=[
            html.Span(str(n), className="step-n"),
            html.Div([html.H3(title, className="card-title"), html.P(hint, className="card-hint")])]),
        html.Div(className="card-body", children=body)])


def kpi(label: str, value: str, sub: Optional[str] = None, tone: Optional[str] = None) -> html.Div:
    return html.Div(className="kpi" + (" kpi-" + tone if tone else ""), children=[
        html.Div(label, className="kpi-label"), html.Div(value, className="kpi-value"),
        html.Div(sub, className="kpi-sub") if sub else None])


def kpi_strip(items: Sequence[html.Div]) -> html.Div:
    return html.Div(className="kpis", children=list(items))


def notice(kind: str, children: Any, title: Optional[str] = None) -> html.Div:
    """kind: info | warn | error | ok"""
    marks = {"info": "i", "warn": "!", "error": "×", "ok": "✓"}
    return html.Div(className="notice notice-" + kind, role="alert" if kind == "error" else "status", children=[
        html.Span(marks.get(kind, "i"), className="notice-mark", **{"aria-hidden": "true"}),
        html.Div([html.Strong(title) if title else None, html.Div(children, className="notice-text")])])


def chip(text: str, tone: str = "neutral") -> html.Span:
    return html.Span(text, className="chip chip-" + tone)


def empty_state(title: str, text: str) -> html.Div:
    return html.Div(className="empty", children=[html.Strong(title), html.P(text)])


def graph(fig: Any) -> dcc.Graph:
    height = getattr(fig.layout, "height", None) or 320
    return dcc.Graph(figure=fig, config=GRAPH_CONFIG, style={"height": "%dpx" % int(height), "width": "100%"})


def chart_card(title: str, fig: Any, hint: Optional[str] = None, cls: str = "") -> html.Div:
    return html.Div(className=("chart-card " + cls).strip(), children=[
        html.H3(title, className="card-title"), html.P(hint, className="card-hint") if hint else None, graph(fig)])


# ── upload and loading ──────────────────────────────────────────────────────
def dropzone(component_id: str, title: str = "Drop a budget document here", filled: Optional[str] = None) -> dcc.Upload:
    mb = C.max_upload_bytes() // (1024 * 1024)
    if filled:
        inner = [html.Strong(filled), html.Div([html.Span("Drop another file or "), html.Span("browse", className="link"),
                                                html.Span(" to replace it")], className="dropzone-hint")]
    else:
        inner = [html.Strong(title), html.Span(" or "), html.Span("browse", className="link"),
                 html.Div("PDF or Word (.docx) · up to %d MB" % mb, className="dropzone-hint")]
    # No file-type filter here: a wrong file should get an explanation, not silence. The size cap only protects the browser.
    return dcc.Upload(id=component_id, multiple=False, max_size=C.UPLOAD_REJECT_FACTOR * C.max_upload_bytes(),
                      className="dropzone" + (" is-filled" if filled else ""), className_active="dropzone is-active",
                      children=html.Div(className="dropzone-inner", children=inner))


def loader(stage: str, detail: str = "", hint: str = "") -> html.Div:
    """A small bar that keeps sweeping from side to side until the work is done. It shows the step, not a percentage."""
    return html.Div(className="loader", role="status", **{"aria-live": "polite"}, children=[
        html.Div(className="loader-top", children=[
            html.Span(C.STAGE_LABELS.get(stage, stage) + "…", className="loader-stage"),
            html.Span(detail, className="loader-detail")]),
        html.Div(className="loader-track", children=html.Div(className="loader-bar")),
        html.Div(hint, className="loader-hint") if hint else None])


def status_slot(slot_id: str, children: Any = None) -> dcc.Loading:
    """A message area that shows the upload bar while the callback that fills it is still working."""
    return dcc.Loading(custom_spinner=loader(C.STAGE_UPLOAD), delay_show=100, parent_className="status-slot",
                       children=html.Div(id=slot_id, children=children))


# ── tables ──────────────────────────────────────────────────────────────────
def data_table(df: pd.DataFrame, table_id: str, columns: Optional[List[Dict[str, Any]]] = None,
               page_size: int = C.RESULT_TABLE_PAGE_SIZE, conditional: Optional[List[Dict[str, Any]]] = None) -> dash_table.DataTable:
    data = df.astype(object).where(df.notna(), None)
    cols = columns or [{"name": c, "id": c} for c in data.columns]
    records = data.to_dict("records")
    return dash_table.DataTable(
        id=table_id, data=records, columns=cols, page_size=page_size, page_action="native", sort_action="native",
        filter_action="native", filter_options={"placeholder_text": "Filter"}, cell_selectable=False, style_as_list_view=True,
        style_cell_conditional=[{"if": {"column_id": c}, "width": "72px", "minWidth": "72px"} for c in ("Line", "Page")],
        style_table={"overflowX": "auto"},
        style_header={"fontFamily": C.FONT_STACK, "fontWeight": "600", "backgroundColor": "#F3F7F4", "color": C.INK, "border": "0",
                      "borderBottom": "1px solid " + C.LINE, "fontSize": "12px"},
        style_cell={"fontFamily": C.FONT_STACK, "fontSize": "13px", "color": C.INK, "padding": "8px 10px", "textAlign": "left",
                    "border": "0", "borderBottom": "1px solid #E4EBE6", "maxWidth": "320px", "overflow": "hidden",
                    "textOverflow": "ellipsis", "whiteSpace": "nowrap", "backgroundColor": "white"},
        style_data_conditional=list(conditional or []) + [{"if": {"state": "active"}, "backgroundColor": "#EDF4EF", "border": "0"}],
        tooltip_data=[{c: {"value": "" if v is None else str(v), "type": "text"} for c, v in row.items()} for row in records[:500]],
        tooltip_duration=None)
