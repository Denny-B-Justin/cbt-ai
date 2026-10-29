"""Plotly figures. Same look as the earlier tool: green and brown carry meaning, Rio levels are one green hue."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np
import plotly.graph_objects as go

from . import constants as C
from .formatting import fmt_int, fmt_pct, is_missing

_GRID = "#E4EBE6"
_AXIS_FONT = dict(family=C.FONT_STACK, size=12, color=C.INK_SOFT)
_HOVER = dict(bgcolor="white", font_size=13, font_family=C.FONT_STACK, align="left", bordercolor=C.LINE)


def _base_layout(fig: go.Figure, height: int = 320, margin: Optional[Dict[str, int]] = None, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height, margin=margin or dict(l=8, r=16, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=C.FONT_STACK, size=13, color=C.INK), hoverlabel=_HOVER,
        showlegend=legend, legend=dict(orientation="h", x=0, font=_AXIS_FONT, title_text="", y=-0.18),
        bargap=0.5, uirevision="keep")
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=C.LINE, tickfont=_AXIS_FONT, title_font=_AXIS_FONT, automargin=True)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=C.LINE, tickfont=_AXIS_FONT, title_font=_AXIS_FONT, automargin=True)
    return fig


def empty_figure(message: str = "No data to show", height: int = 240) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                       font=dict(size=14, color=C.INK_MUTE, family=C.FONT_STACK))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _base_layout(fig, height)


def fig_donut(slices: Sequence[Tuple[str, float, str]], unit: str = "amount", height: int = 300) -> go.Figure:
    """Donut of (label, value, colour) slices; every slice carries its name and share."""
    slices = [(l, float(v), c) for l, v, c in slices if not is_missing(v) and float(v) > 0]
    if not slices:
        return empty_figure("Nothing to show", height)
    fig = go.Figure(go.Pie(
        labels=[l for l, _, _ in slices], values=[v for _, v, _ in slices], sort=False, direction="clockwise", hole=0.58,
        marker=dict(colors=[c for _, _, c in slices], line=dict(color="white", width=2)),
        texttemplate="%{label}<br>%{percent:.0%}", textposition="outside",
        textfont=dict(size=12, color=C.INK, family=C.FONT_STACK),
        hovertemplate="%%{label}<br>%%{percent:.1%%} of %s<extra></extra>" % unit))
    fig = _base_layout(fig, height, legend=True, margin=dict(l=40, r=40, t=56, b=32))
    fig.update_layout(legend=dict(orientation="h", x=0.5, xanchor="center", y=1.12, yanchor="bottom"))
    return fig


def fig_rio_donut(principal: float, significant: float, unit: str = "amount", height: int = 300) -> go.Figure:
    rest = max(0.0, 1.0 - (principal or 0) - (significant or 0))
    return fig_donut([("%s (2)" % C.RIO_LABELS[2], principal, C.RIO_COLORS[2]),
                      ("%s (1)" % C.RIO_LABELS[1], significant, C.RIO_COLORS[1]),
                      (C.RIO_LABELS[0], rest, C.RIO_COLORS[0])], unit, height)


def fig_tag_donut(green: float, brown: float, unit: str = "amount", height: int = 300) -> go.Figure:
    rest = max(0.0, 1.0 - (green or 0) - (brown or 0))
    return fig_donut([(C.TAG_LABELS[C.TAG_GREEN], green, C.TAG_COLORS[C.TAG_GREEN]),
                      (C.TAG_LABELS[C.TAG_BROWN], brown, C.TAG_COLORS[C.TAG_BROWN]),
                      (C.TAG_LABELS[C.TAG_NEUTRAL], rest, C.TAG_COLORS[C.TAG_NEUTRAL])], unit, height)


def fig_bar_h(labels: Sequence[str], values: Sequence[float], title: str = "", pct: bool = False,
              color: str = C.INDIGO, height: Optional[int] = None) -> go.Figure:
    """Horizontal single-series bars, largest on top, value written at the bar end."""
    labels, values = list(labels), [0.0 if is_missing(v) else float(v) for v in values]
    if not labels:
        return empty_figure()
    order = np.argsort(values)
    labels = [labels[i] for i in order]
    values = [values[i] for i in order]
    text = [fmt_pct(v) if pct else fmt_int(v) for v in values]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h", marker=dict(color=color, cornerradius=4, line=dict(width=0)),
        text=text, textposition="outside", cliponaxis=False,
        textfont=dict(color=C.INK, size=12, family=C.FONT_STACK), hovertemplate="%{y}<br>%{text}<extra></extra>"))
    fig.update_xaxes(tickformat=".0%" if pct else None, title=title, range=[0, max(max(values) * 1.18, 0.05 if pct else 1.0)])
    return _base_layout(fig, height or max(150, 34 * len(labels) + 70), margin=dict(l=8, r=48, t=8, b=8))


def fig_eu_objectives(summary: Dict[str, Any]) -> go.Figure:
    shares = summary.get("objective_shares") or {}
    return fig_bar_h([C.EU_LABELS[k] for k in C.EU_OBJECTIVES], [shares.get(k) or 0.0 for k in C.EU_OBJECTIVES], pct=True,
                     title="Share of %s serving the objective (a line can serve several)" % summary.get("basis", "amount"))


def fig_methods(counts: Dict[str, int], title: str = "Distinct classifications") -> go.Figure:
    if not counts:
        return empty_figure()
    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return fig_bar_h([k for k, _ in items], [v for _, v in items], title=title, color="#5E7A6B")


def fig_compare(labels: Sequence[str], a_values: Sequence[float], b_values: Sequence[float], title: str = "",
                names: Tuple[str, str] = ("Budget A", "Budget B"), height: Optional[int] = None) -> go.Figure:
    """Two budgets side by side as grouped horizontal bars (shares 0..1)."""
    if not labels:
        return empty_figure()
    fig = go.Figure()
    for name, values, colour in ((names[0], a_values, C.COMPARE_COLORS["A"]), (names[1], b_values, C.COMPARE_COLORS["B"])):
        vals = [0.0 if is_missing(v) else float(v) for v in values]
        fig.add_trace(go.Bar(
            y=list(labels), x=vals, orientation="h", name=name, marker=dict(color=colour, cornerradius=4, line=dict(width=0)),
            text=[fmt_pct(v) for v in vals], textposition="outside", cliponaxis=False,
            textfont=dict(color=C.INK, size=12, family=C.FONT_STACK), hovertemplate="%%{y}<br>%s: %%{text}<extra></extra>" % name))
    top = max([float(v) for v in list(a_values) + list(b_values) if not is_missing(v)] + [0.0])
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.06)
    fig.update_xaxes(tickformat=".0%", title=title, range=[0, max(top * 1.2, 0.05)])
    fig.update_yaxes(autorange="reversed")
    fig = _base_layout(fig, height or max(240, 72 * len(labels) + 90), legend=True, margin=dict(l=8, r=52, t=34, b=8))
    fig.update_layout(legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom", traceorder="normal"))
    return fig
