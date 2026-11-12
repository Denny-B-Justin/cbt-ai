"""Plotly figures. Mitigation is green, adaptation blue, both orange; the four levels are one purple hue, dark to light."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import plotly.graph_objects as go

import constants as C
import page_constants as P

from .formatting import fmt_int, fmt_pct, is_missing, plural

_GRID = "#E4EBE6"
_AXIS_FONT = dict(family=P.FONT_STACK, size=12, color=P.INK_SOFT)
_HOVER = dict(bgcolor="white", font_size=13, font_family=P.FONT_STACK, align="left", bordercolor=P.LINE)


def _base_layout(fig: go.Figure, height: int = 320, margin: dict[str, int] | None = None, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height, margin=margin or dict(l=8, r=16, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=P.FONT_STACK, size=13, color=P.INK), hoverlabel=_HOVER,
        showlegend=legend, legend=dict(orientation="h", x=0, font=_AXIS_FONT, title_text="", y=-0.18),
        bargap=0.5, uirevision="keep")
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=P.LINE, tickfont=_AXIS_FONT, title_font=_AXIS_FONT, automargin=True)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=P.LINE, tickfont=_AXIS_FONT, title_font=_AXIS_FONT, automargin=True)
    return fig


def empty_figure(message: str = "No data to show", height: int = 240) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                       font=dict(size=14, color=P.INK_MUTE, family=P.FONT_STACK))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _base_layout(fig, height)


def fig_donut(slices: Sequence[tuple[str, float, str]], unit: str = "amount", height: int = 300) -> go.Figure:
    """Donut of (label, value, colour) slices; every slice carries its name and share."""
    slices = [(l, float(v), c) for l, v, c in slices if not is_missing(v) and float(v) > 0]
    if not slices:
        return empty_figure("Nothing to show", height)
    fig = go.Figure(go.Pie(
        labels=[l for l, _, _ in slices], values=[v for _, v, _ in slices], sort=False, direction="clockwise", hole=0.58,
        marker=dict(colors=[c for _, _, c in slices], line=dict(color="white", width=2)),
        texttemplate="%{label}<br>%{percent:.0%}", textposition="outside",
        textfont=dict(size=12, color=P.INK, family=P.FONT_STACK),
        hovertemplate="%%{label}<br>%%{percent:.1%%} of %s<extra></extra>" % unit))
    fig = _base_layout(fig, height, legend=True, margin=dict(l=40, r=40, t=56, b=32))
    fig.update_layout(legend=dict(orientation="h", x=0.5, xanchor="center", y=1.12, yanchor="bottom"))
    return fig


def fig_compare(labels: Sequence[str], a_values: Sequence[float], b_values: Sequence[float], title: str = "",
                names: tuple[str, str] = ("Budget A", "Budget B"), height: int | None = None) -> go.Figure:
    """Two budgets side by side as grouped horizontal bars (shares 0..1)."""
    if not labels:
        return empty_figure()
    fig = go.Figure()
    for name, values, colour in ((names[0], a_values, P.COMPARE_COLORS["A"]), (names[1], b_values, P.COMPARE_COLORS["B"])):
        vals = [0.0 if is_missing(v) else float(v) for v in values]
        fig.add_trace(go.Bar(
            y=list(labels), x=vals, orientation="h", name=name, marker=dict(color=colour, cornerradius=4, line=dict(width=0)),
            text=[fmt_pct(v) for v in vals], textposition="outside", cliponaxis=False,
            textfont=dict(color=P.INK, size=12, family=P.FONT_STACK), hovertemplate="%%{y}<br>%s: %%{text}<extra></extra>" % name))
    top = max([float(v) for v in list(a_values) + list(b_values) if not is_missing(v)] + [0.0])
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.06)
    fig.update_xaxes(tickformat=".0%", title=title, range=[0, max(top * 1.2, 0.05)])
    fig.update_yaxes(autorange="reversed")
    fig = _base_layout(fig, height or max(240, 72 * len(labels) + 90), legend=True, margin=dict(l=8, r=52, t=34, b=8))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom", traceorder="normal"))
    return fig


# ── stacked bars and the level × code grid ──────────────────────────────────
def fig_stacked_h(labels: Sequence[str], series: Sequence[tuple[str, Sequence[float], str]], value_fmt=fmt_int,
                  pct: bool = False, title: str = "", end_text: Sequence[str] | None = None, inside: bool = False,
                  height: int | None = None) -> go.Figure:
    """Horizontal stacked bars, first label on top. The bar total (or end_text) is written at the bar end.

    pct: values are fractions (0..1). inside: also write each segment's share inside it when there is room.
    """
    labels = list(labels)
    series = [(n, [0.0 if is_missing(v) else float(v) for v in vals], c) for n, vals, c in series]
    totals = np.sum([vals for _, vals, _ in series], axis=0) if series and labels else np.zeros(0)
    if not labels or not np.any(totals > 0):
        return empty_figure("Nothing to show", height or 200)
    fmt = fmt_pct if pct else value_fmt
    fig = go.Figure()
    for name, vals, colour in series:
        fig.add_trace(go.Bar(
            y=labels, x=vals, orientation="h", name=name, marker=dict(color=colour, line=dict(color="white", width=2)),
            text=[fmt_pct(v, 0) if inside and v >= 0.09 else "" for v in vals], textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=11, family=P.FONT_STACK), customdata=[fmt(v) for v in vals],
            hovertemplate="%%{y}<br>%s: %%{customdata}<extra></extra>" % name))
    ends = list(end_text) if end_text is not None else [fmt(t) for t in totals]
    fig.add_trace(go.Scatter(x=totals, y=labels, mode="text", text=["  " + t for t in ends], textposition="middle right",
                             textfont=dict(color=P.INK, size=12, family=P.FONT_STACK), showlegend=False, hoverinfo="skip",
                             cliponaxis=False))
    top = float(totals.max())
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_xaxes(tickformat=".0%" if pct else None, title=title, range=[0, top * 1.28])
    if inside:                                         # a composition: shares of 100%, never a tick beyond it
        fig.update_xaxes(tickvals=[0, 0.25, 0.5, 0.75, 1.0])
    fig.update_yaxes(autorange="reversed")
    legend = len(series) > 1
    fig = _base_layout(fig, height or max(170, 34 * len(labels) + (110 if legend else 70)), legend=legend,
                       margin=dict(l=8, r=16, t=34 if legend else 8, b=8))
    if legend:
        fig.update_layout(legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom", traceorder="normal"))
    return fig


def fig_level_code_heatmap(level_code: Any, value_fmt=fmt_int, height: int = 300) -> go.Figure:
    """Climate amount and number of lines for every level and CBT code."""
    levels, codes = list(C.LEVELS), list(C.CBT_CODES)
    z = [[float(level_code.at[(lv, c), "climate"]) for c in codes] for lv in levels]
    n = [[int(level_code.at[(lv, c), "lines"]) for c in codes] for lv in levels]
    if not any(any(row) for row in n):
        return empty_figure("No climate-tagged lines", height)
    text = [["%s<br>%s" % (value_fmt(v), plural(k, "line")) if k else "-" for v, k in zip(zr, nr)] for zr, nr in zip(z, n)]
    fig = go.Figure(go.Heatmap(
        z=z, x=[C.CODE_LABELS[c] for c in codes], y=[C.LEVEL_LABELS[lv] for lv in levels], text=text,
        texttemplate="%{text}", textfont=dict(size=12, family=P.FONT_STACK), xgap=2, ygap=2, showscale=False,
        colorscale=[[0, "#F4F0FB"], [1, P.LEVEL_COLORS[100]]], zmin=0, hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(side="top", showgrid=False)
    return _base_layout(fig, height, margin=dict(l=8, r=8, t=8, b=8))
