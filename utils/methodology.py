"""Methodology page: how budgets are tagged, in plain language. Opens in its own browser tab."""

from __future__ import annotations

from typing import Any, List, Sequence

from dash import html

from . import components as ui
from . import constants as C

SECTIONS = [("idea", "The idea in short"), ("steps", "From document to results"), ("rio", "Rio Markers"), ("eu", "EU Taxonomy"),
            ("skip", "Spending we do not count"), ("shares", "How the shares are worked out"), ("sure", "How sure are we?"),
            ("score", "The overall score"), ("know", "Good to know"), ("words", "Words used in this tool")]


def _section(sid: str, title: str, *children: Any) -> html.Section:
    return html.Section(id=sid, className="doc-section", children=[html.H2(title, className="doc-h2"), *children])


def _p(*children: Any) -> html.P:
    return html.P(list(children), className="doc-p")


def _list(items: Sequence[Any]) -> html.Ul:
    return html.Ul([html.Li(i) for i in items], className="doc-list")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> html.Div:
    return html.Div(className="doc-table-wrap", children=html.Table(className="doc-table", children=[
        html.Thead(html.Tr([html.Th(h) for h in headers])),
        html.Tbody([html.Tr([html.Td(c) for c in r]) for r in rows])]))


def _callout(title: str, text: str, kind: str = "info") -> html.Div:
    return html.Div(className="callout callout-" + kind, children=[html.Strong(title), html.Div(text)])


def _flow(steps: Sequence[Sequence[str]]) -> html.Ol:
    return html.Ol(className="flow", children=[
        html.Li(className="flow-step", children=[html.Span(str(i), className="flow-n"),
                                                 html.Div([html.Strong(title), html.Div(text, className="flow-text")])])
        for i, (title, text) in enumerate(steps, start=1)])


def _swatch(colour: str) -> html.Span:
    return html.Span(className="swatch", style={"background": colour})


def _body() -> List[Any]:
    w = C.RIO_WEIGHTS
    significant = int(round(w[1] * 100))
    objectives = [html.Li([html.Strong(C.EU_LABELS[k]), " - " + text]) for k, text in [
        ("mitigation", "cutting greenhouse gas emissions, for example with renewable energy, energy saving or clean transport."),
        ("adaptation", "getting ready for the effects of climate change, for example with flood protection or drought-resistant farming."),
        ("water", "looking after water and the sea, for example with water and wastewater treatment."),
        ("circular_economy", "wasting less and reusing more, for example with recycling and repair."),
        ("pollution", "keeping air, water and soil clean."),
        ("biodiversity", "protecting nature, for example with national parks and wildlife conservation.")]]
    return [
        _section("idea", "The idea in short",
                 _p("Governments spend money on many things. Some of that spending helps to fight climate change, or helps people and places "
                    "cope with its effects. This tool finds that spending and shows you how big it is."),
                 _p("It looks at every line of a budget, for example ", html.Strong("Solar power plant"), " or ", html.Strong("Flood protection"),
                    ", and asks: does this line help the climate? If it does, how much? The answers are written in two well-known ways: "
                    "the ", html.Strong("Rio Markers"), " and the ", html.Strong("EU Taxonomy"), ". You see both for every budget."),
                 _callout("Think of it as a careful first reading",
                          "It saves many hours of work. But people should always check the results before using them in an official decision.")),
        _section("steps", "From document to results", _flow([
            ("You upload a document", "A PDF or Word file that contains a budget. It can be one page or hundreds of pages."),
            ("We read it", "We read the text and the tables, and work out what the document is: which country, which year and which currency."),
            ("We find the budget lines", "Each programme, project or spending item becomes one budget line with its amount. "
                                         "Totals and subtotals are left out, so that no money is counted twice."),
            ("We tag every line", "An AI assistant reads each line, much as a budget analyst would, and gives it a tag. "
                                  "A second, simple check based on lists of climate words runs next to it. When both agree, we are more sure."),
            ("We add up the amounts", "We work out which share of the budget goes to each tag."),
            ("You see the results", "Charts, a table of every line with the reason for its tag, and an Excel file you can download.")])),
        _section("rio", "Rio Markers",
                 _p("The Rio Markers are a widely used way to tag spending for climate. They were first used to follow development aid, and "
                    "many governments now use them for their own budgets."),
                 _p("Every line is judged on two aims, one at a time:"),
                 _list([[html.Strong("Mitigation"), " - cutting greenhouse gas emissions. For example solar power, saving energy, clean transport, protecting forests."],
                        [html.Strong("Adaptation"), " - getting ready for the effects of climate change. For example flood defences, drought-resistant crops, early warning systems."]]),
                 _p("For each aim the line gets a score of 0, 1 or 2. The marker of the line is the higher of its two scores."),
                 _table(["Marker", "Name", "What it means", "How much of the line counts"], [
                     ["2", [_swatch(C.RIO_COLORS[2]), "Principal"], "Climate is the main purpose of the line.", "100%"],
                     ["1", [_swatch(C.RIO_COLORS[1]), "Significant"], "Climate is an important goal, but not the only one.", "%d%%" % significant],
                     ["0", [_swatch(C.RIO_COLORS[0]), "Not targeted"], "There is no clear link to climate.", "0%"]]),
                 _p("The ", html.Strong("Rio-weighted share"), " adds the full amount of the Principal lines to %d%% of the amount of the Significant lines, "
                    "and divides the result by the whole budget." % significant),
                 _callout("An example", "A budget has 100 million. Principal lines add up to 10 million and Significant lines to 20 million. "
                                        "The climate share is (10 + 0.%d × 20) ÷ 100 = 18%%." % significant)),
        _section("eu", "EU Taxonomy",
                 _p("The EU Taxonomy is a list of the activities that the European Union counts as good for the environment. "
                    "We use it as a guide. It is not a legal test."),
                 _p("A line is checked against six environmental goals:"),
                 html.Ul(objectives, className="doc-list"),
                 _p("Each line gets one of three tags:"),
                 _table(["Tag", "What it means"], [
                     [[_swatch(C.GREEN_COLOR), "Green"], "The line clearly serves at least one of the six goals. A line can serve more than one."],
                     [[_swatch(C.BROWN_COLOR), "Brown"], "The line pays for something that harms the environment, for example coal, oil and gas, mining or waste burning."],
                     [[_swatch(C.NO_DATA_COLOR), "Neutral"], "Everything else."]]),
                 _p("The ", html.Strong("green share"), " is the part of the budget that is Green. The ", html.Strong("brown share"),
                    " is the part that is Brown.")),
        _section("skip", "Spending we do not count",
                 _p("Some spending is not climate spending, even when the name sounds green. We do not count:"),
                 _list([[html.Strong("Routine running costs"), " such as salaries, pensions, rent, office costs, interest on debt, audits and routine upkeep."],
                        [html.Strong("Names without substance"), ". A line is not climate spending just because it sits under an environment ministry, or because it contains a popular word. "
                                                                 "We look at what the money is spent on."]]),
                 _p("Lines for harmful activities, such as coal power, are tagged Brown and never count as climate spending.")),
        _section("shares", "How the shares are worked out",
                 _list([[html.Strong("By amount."), " When the document gives amounts, every share is a share of the money."],
                        [html.Strong("By number of lines."), " When a document has no amounts, shares are based on the number of budget lines. The tool tells you when this happens."],
                        [html.Strong("No double counting."), " Some documents show the same money in several ways, for example by ministry, by programme and by function. "
                                                             "We use one of these views: programmes first, then functions, then ministries. The tool tells you which one it used."],
                        [html.Strong("Lines we leave out of the amounts."), " Lines without an amount and lines with a negative amount do not change the shares."]])),
        _section("sure", "How sure are we?",
                 _p("Every line in the results table shows how sure we are (High, Medium or Low) and what the decision rested on:"),
                 _table(["Decided by", "What it means"], [
                     [C.DECIDED_LABELS[C.DECIDED_CONFIRMED], "The AI assistant and the word check both found a link to climate."],
                     [C.DECIDED_LABELS[C.DECIDED_AI_ONLY], "The AI assistant found a link to climate, but the word check did not. We are a little less sure."],
                     [C.DECIDED_LABELS[C.DECIDED_NONE], "Neither check found a link to climate."],
                     [C.DECIDED_LABELS[C.DECIDED_ADMIN], "The line is a routine running cost."],
                     [C.DECIDED_LABELS[C.DECIDED_BROWN], "The line pays for a fossil or polluting activity."],
                     [C.DECIDED_LABELS[C.DECIDED_REVIEW], "The two checks disagree in a way that matters. The line is not counted as climate spending, and we ask you to take a look."],
                     [C.DECIDED_LABELS[C.DECIDED_RULES], "The AI assistant could not assess this line, so only the word check was used. We are not very sure."]]),
                 _callout("Tip", "Sort the table by confidence, or search for \"second look\", to find the lines that deserve a human check first.", "ok")),
        _section("score", "The overall score",
                 _p("On the Compare Budget page, each budget gets an overall score from 0 to 100. It is a guide for comparing two budgets. It is not an official rating."),
                 _p("The score looks at four things, most important first:"),
                 _list(["How much of the budget supports climate goals.",
                        "How directly: Principal lines count for more than Significant lines.",
                        "How broad: whether the budget covers both mitigation and adaptation, and how many of the six EU goals it serves.",
                        "Harm: spending on fossil or polluting activities lowers the score."]),
                 _table(["Score", "What it usually means"], [
                     ["0 - 10", "Almost no climate spending."], ["10 - 30", "A small share, mostly as a side benefit."],
                     ["30 - 60", "A meaningful share, with some spending where climate is the main purpose."],
                     ["60 - 85", "A large share, mostly with climate as the main purpose, and broad."], ["85 - 100", "Exceptional."]]),
                 _p("The score is worked out by an AI assistant and checked against a fixed rule based on the numbers in the table. "
                    "This keeps it fair: a budget with clearly more climate spending and no more harmful spending does not score lower.")),
        _section("know", "Good to know",
                 _list([[html.Strong("A person should check the results."), " The AI assistant can make mistakes. If you run the same document twice, a few tags may differ."],
                        [html.Strong("Text works best."), " Pages that are scans or pictures cannot be read. The tool tells you when it skips them."],
                        [html.Strong("Complicated tables can be misread."), " For the most important lines, compare the result with the original document."],
                        [html.Strong("Only what is written can be tagged."), " If a budget does not say what the money is for, we cannot tell."],
                        [html.Strong("Currencies are not converted."), " Amounts are shown in the currency of each document."],
                        [html.Strong("Your document is not stored."), " It is removed when you close or refresh the page. Download your results first if you want to keep them."],
                        [html.Strong("This is a demonstration."), " Your document is read by an online AI service, so please do not upload documents that must stay confidential."]])),
        _section("words", "Words used in this tool", _table(["Word", "Meaning"], [
            ["Budget line", "One programme, project or spending item in a budget, with its amount."],
            ["Mitigation", "Actions that cut greenhouse gas emissions."],
            ["Adaptation", "Actions that help people and places cope with the effects of climate change."],
            ["Principal", "Climate is the main purpose of the line."],
            ["Significant", "Climate is an important goal, but not the only one."],
            ["Green", "Serves at least one of the six EU environmental goals."],
            ["Brown", "Pays for an activity that harms the environment."],
            ["Neutral", "No clear link to climate or the environment."],
            ["Share", "The part of the budget, in percent, that has a given tag."]]))]


def layout() -> html.Div:
    return html.Div([
        ui.page_intro("How budgets are tagged", "A short guide, in plain words, to how this tool decides which parts of a budget support climate goals.",
                      eyebrow="Methodology"),
        html.Div(className="section-inner doc-layout", children=[
            html.Nav(className="doc-toc", **{"aria-label": "On this page"}, children=[
                html.Div("On this page", className="doc-toc-title"), *[html.A(title, href="#" + sid) for sid, title in SECTIONS]]),
            html.Div(className="doc-body", children=_body())])])
