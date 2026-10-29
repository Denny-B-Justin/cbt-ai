"""Home page."""

from __future__ import annotations

from dash import dcc, get_asset_url, html

from . import constants as C


def layout() -> html.Section:
    return html.Section(className="hero", style={"--hero-map": "url(%s)" % get_asset_url("climate-finance.svg")},
                        children=html.Div(className="hero-inner", children=[
                            html.P("CBT", className="eyebrow"),
                            html.H1(C.APP_NAME, className="hero-title"),
                            html.P("Upload a budget document and see how much of it supports climate goals. Look at one budget, "
                                   "or compare two side by side.", className="hero-lede"),
                            html.Div(className="hero-actions", children=[
                                dcc.Link("Evaluate Budget", href="?page=" + C.PAGE_EVALUATE, className="btn btn-primary btn-lg"),
                                dcc.Link("Compare Budget", href="?page=" + C.PAGE_COMPARE, className="btn btn-teal btn-lg"),
                                html.A("How it works", href="?page=" + C.PAGE_METHODOLOGY, target="_blank", rel="noopener",
                                       className="btn btn-ghost btn-lg")])]))
