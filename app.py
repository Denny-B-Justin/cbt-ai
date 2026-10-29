"""Climate Budget Tagging Tool - Dash app.

Run locally:   python app.py          then open http://127.0.0.1:8050
Production:    gunicorn app:server --workers 1 --threads 8 --timeout 300
Pages are chosen with the query string (?page=home|evaluate|compare|methodology).
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from typing import Any, Callable, Dict
from urllib.parse import parse_qs

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:                                        # the .env file is optional
    pass

from dash import Dash, Input, Output, State, callback, dcc, html
from flask import request

from utils import compare, evaluate, home, methodology, session
from utils import components as ui
from utils import constants as C

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Dash(
    __name__, suppress_callback_exceptions=True, title=C.APP_NAME, update_title=None,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"},
               {"name": "description", "content": C.APP_TAGLINE}])
server = app.server

app.index_string = """<!DOCTYPE html>
<html lang="en">
    <head>
        {%metas%}
        <title>{%title%}</title>
        <link rel="icon" type="image/x-icon" href=\"""" + app.get_asset_url("favicon.ico") + """\">
        <link rel="preload" as="font" type="font/woff2" crossorigin href=\"""" + app.get_asset_url("fonts/fira-sans-latin-400-normal.woff2") + """\">
        <link rel="preload" as="font" type="font/woff2" crossorigin href=\"""" + app.get_asset_url("fonts/fira-sans-latin-600-normal.woff2") + """\">
        {%css%}
    </head>
    <body>
        <noscript>This tool needs JavaScript. Please turn it on in your browser.</noscript>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


def serve_layout() -> html.Div:
    """Runs on every page load, so every visitor gets a session of their own."""
    sid = session.new_id()
    return html.Div([
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="session", data=sid),
        html.Div(id="session-root", hidden=True, **{"data-sid": sid, "data-base": app.config.requests_pathname_prefix}),
        html.Div(id="page-content"),
        html.Div(id="title-sink", hidden=True)])


app.layout = serve_layout

PAGE_BUILDERS: Dict[str, Callable[[str], Any]] = {
    C.PAGE_HOME: lambda sid: home.layout(),
    C.PAGE_EVALUATE: lambda sid: evaluate.layout(),
    C.PAGE_COMPARE: compare.layout,
    C.PAGE_METHODOLOGY: lambda sid: methodology.layout()}


def not_found() -> html.Div:
    return html.Div(className="notfound", children=[
        html.H1("Page not found", className="page-title"), html.P("That page does not exist.", className="page-lede"),
        dcc.Link("Back to the home page", href="?page=" + C.DEFAULT_PAGE, className="btn btn-primary")])


@callback(Output("page-content", "children"), Input("url", "search"), State("session", "data"))
def route(search: str, sid: str):
    page = (parse_qs((search or "").lstrip("?")).get("page") or [C.DEFAULT_PAGE])[0]
    if page == C.PAGE_HOME:
        return ui.page_shell(page, home.layout())
    builder = PAGE_BUILDERS.get(page)
    return ui.page_shell(page, builder(sid)) if builder else ui.page_shell("", not_found())


app.clientside_callback(
    """function(search) {
        const titles = %s;
        const page = new URLSearchParams(search || "").get("page") || %s;
        document.title = titles[page] || %s;
        return "";
    }""" % (json.dumps({key: "%s - %s" % (label, C.APP_NAME) for key, label, _ in C.PAGES}), json.dumps(C.DEFAULT_PAGE), json.dumps(C.APP_NAME)),
    Output("title-sink", "children"), Input("url", "search"))


@server.post(app.config.routes_pathname_prefix + "_session/ping")
def session_ping():
    session.touch(request.get_data(as_text=True).strip())
    return "", 204


@server.post(app.config.routes_pathname_prefix + "_session/end")
def session_end():
    session.end(request.get_data(as_text=True).strip())
    return "", 204


def main() -> None:
    app.run(debug=False, host="0.0.0.0", port=C.env_int(C.ENV_PORT, 8050))


if __name__ == "__main__":
    main()
