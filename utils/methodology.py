"""Methodology page: how budgets are tagged, in plain language. Opens in its own browser tab."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from dash import html

import constants as C
import page_constants as P

from . import components as ui

SECTIONS = [("idea", "The idea in short"), ("steps", "From document to results"), ("questions", "The four guiding questions"),
            ("levels", "The four levels"), ("rules", "What counts and what does not"), ("shares", "How the shares are worked out"),
            ("sure", "How sure are we?"), ("score", "The overall score"), ("know", "Good to know"), ("words", "Words used in this tool")]


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


def _body() -> list[Any]:
    codes = [[_swatch(P.CODE_COLORS[c]), C.CODE_LABELS[c]] for c in C.CBT_CODES]
    return [
        _section("idea", "The idea in short",
                 _p("Governments spend money on many things. Some of that spending helps to cut greenhouse gas emissions, or helps people and "
                    "places cope with the effects of climate change. This tool finds that spending in a budget and shows you how big it is."),
                 _p("It follows the method of ", html.Em("Climate Budget Tagging in Georgia: Handbook"), " (Ministry of Environmental Protection "
                    "and Agriculture of Georgia and the World Bank, June 2025). Every budget line, for example ", html.Strong("Reforestation"),
                    " or ", html.Strong("Irrigation system rehabilitation"), ", is checked with the handbook's four guiding questions, "
                    "marked as mitigation, adaptation or both, and placed in one of four levels that say how much of it counts as climate spending."),
                 _callout("Think of it as a careful first reading",
                          "It saves many hours of work. But people should always check the results before using them in an official decision.")),
        _section("steps", "From document to results", _flow([
            ("You upload a document", "A PDF, Word or Excel file that contains a budget. It can be one page or hundreds of pages, or a spreadsheet with any number of sheets."),
            ("We read it", "We read the text and the tables, and work out what the document is: which country, which year and which currency."),
            ("We find the budget lines", "Each programme, sub-programme, project or activity becomes one budget line with its amount. "
                                         "Totals and subtotals are left out, so that no money is counted twice."),
            ("We tag every line", "An AI assistant reads each line, much as a budget analyst would, answers the four guiding questions, "
                                  "and gives the line its code (CM, CA or CB) and its level (100, 70, 40 or 20)."),
            ("We add up the amounts", "Each tagged line counts at its level. The tool adds up the climate part of every line."),
            ("You see the results", "Charts, a table of every line with the reason for its tag, and an Excel file you can download.")])),
        _section("questions", "The four guiding questions",
                 _p("Each line is checked with four questions, in order:"),
                 _list(["Q1: does the line involve activities that emit or absorb greenhouse gases? For example burning fuel, transport, "
                        "buildings, industry, farming, waste or forests.",
                        "Q2: does it include a measure that cuts those emissions or absorbs more? For example renewable energy, insulation, "
                        "efficient equipment, methane capture or new forests.",
                        "Q3: does it involve risks from climate hazards? For example floods, droughts, landslides, mudflows, extreme heat, "
                        "storms or sea-level rise.",
                        "Q4: does it include a measure that lowers those risks or makes people and places more resilient?"]),
                 _p("The answers give the line its code:"),
                 _table(["Code", "When"], [
                     [codes[0], "Q1 and Q2 are yes: the line helps to cut emissions (mitigation)."],
                     [codes[1], "Q3 and Q4 are yes: the line helps to cope with climate change (adaptation)."],
                     [codes[2], "Both of the above. The counted part is split half and half between mitigation and adaptation."],
                     [[_swatch(P.NO_DATA_COLOR), C.NOT_TAGGED], "Neither. The line is not climate-tagged and does not count."]])),
        _section("levels", "The four levels",
                 _p("Every climate-tagged line, even one with only a small or indirect link to climate, is placed in one of four levels. "
                    "The levels are classes chosen from what the line says, not measured percentages. Lines that are not climate-tagged have no level."),
                 _table(["Level", "What it means", "How much of the line counts"],
                        [[[_swatch(P.LEVEL_COLORS[lv]), C.LEVEL_LABELS[lv]], P.LEVEL_MEANING[lv], "%d%%" % lv] for lv in C.LEVELS]),
                 _p("When the climate part of a line's cost is known, the closest level is used: a line where about 37% of the cost is "
                    "climate work is placed at level 40. When two levels are possible, the lower one is chosen."),
                 _callout("An example", "A line of 10 million at level 70 that is both mitigation and adaptation (CB) adds 7 million to the "
                                        "climate spending: 3.5 million to mitigation and 3.5 million to adaptation.")),
        _section("rules", "What counts and what does not",
                 _list([[html.Strong("Service costs are not tagged."), " Salaries, equipment, upkeep and general management that support a "
                         "whole programme or ministry are not counted."],
                        [html.Strong("Pay for one climate activity counts with it."), " Salaries and benefits of the staff who deliver one "
                         "specific climate activity take the level of that activity."],
                        [html.Strong("Names without substance do not count."), " A line is not tagged just because it sits under an "
                         "environment ministry or contains a popular word. We look at what the money is spent on."],
                        [html.Strong("Lending and debt do not count."), " Loans, equity and debt repayment are not climate activities."],
                        [html.Strong("Liveable or habitable wording."), " A line named for liveable or habitable cities or settlements, with no "
                         "other climate measure, counts as adaptation at level %d. This is a rule of this tool, not of the handbook." % C.FLOOR_LEVEL]])),
        _section("shares", "How the shares are worked out",
                 _list([[html.Strong("The climate share"), " adds up the counted part of every climate-tagged line (its amount times its "
                         "level) and divides it by the whole budget."],
                        [html.Strong("Mitigation and adaptation shares"), " split that climate spending by code; a CB line counts half in each."],
                        [html.Strong("By amount."), " When the document gives amounts, every share is a share of the money."],
                        [html.Strong("By number of lines."), " When a document has no amounts, shares are based on the number of budget lines. The tool tells you when this happens."],
                        [html.Strong("No double counting."), " Some documents show the same money in several ways, for example by ministry, by programme and by function. "
                                                             "We use one of these views: programmes first, then functions, then ministries. The tool tells you which one it used."],
                        [html.Strong("Lines we leave out of the amounts."), " Lines without an amount and lines with a negative amount do not change the shares."]])),
        _section("sure", "How sure are we?",
                 _p("Every line in the results table shows how sure we are (High, Medium or Low) and what the decision rested on:"),
                 _table(["Decided by", "What it means"], [
                     [C.DECIDED_LABELS[C.DECIDED_BOTH], "Both a mitigation measure and an adaptation measure were found: the line is CB."],
                     [C.DECIDED_LABELS[C.DECIDED_MIT], "A measure that cuts emissions was found: the line is CM."],
                     [C.DECIDED_LABELS[C.DECIDED_ADP], "A measure that lowers climate risks was found: the line is CA."],
                     [C.DECIDED_LABELS[C.DECIDED_FLOOR], "Only the liveable or habitable wording links the line to climate."],
                     [C.DECIDED_LABELS[C.DECIDED_SERVICE], "The line is a service cost of its programme or ministry."],
                     [C.DECIDED_LABELS[C.DECIDED_LINK], "The line touches emissions or climate hazards, but no measure was found."],
                     [C.DECIDED_LABELS[C.DECIDED_NONE], "No link to climate was found."],
                     [C.DECIDED_LABELS[C.DECIDED_MISSING], "The AI assistant could not assess this line. It does not count."]]),
                 _callout("Tip", "Sort the table by confidence, or search for \"Not assessed\", to find the lines that deserve a human check first.", "ok")),
        _section("score", "The overall score",
                 _p("On the Compare Budget page, each budget gets an overall score from 0 to 100. It is a guide for comparing two budgets. It is not an official rating."),
                 _p("The score looks at four things, most important first:"),
                 _list(["How much of the budget is climate spending (the climate share).",
                        "How directly: climate spending in lines at levels 100 and 70 counts for more than spending at levels 40 and 20.",
                        "Balance: whether the budget funds both mitigation and adaptation.",
                        "Breadth: how many sectors carry climate spending."]),
                 _table(["Score", "What it usually means"], [
                     ["0 - 10", "Almost no climate spending."], ["10 - 30", "A small share, mostly at low levels."],
                     ["30 - 60", "A meaningful share, with some lines at high levels."],
                     ["60 - 85", "A large share, mostly at high levels, and broad."], ["85 - 100", "Exceptional."]]),
                 _p("The score is worked out by an AI assistant and checked against a fixed rule based on the numbers in the table. "
                    "This keeps it fair: a budget with clearly more climate spending does not score lower.")),
        _section("know", "Good to know",
                 _list([[html.Strong("A person should check the results."), " The AI assistant can make mistakes. If you run the same document twice, a few tags may differ."],
                        [html.Strong("Text works best."), " Pages that are scans or pictures are harder to read. The tool tells you when it finds them."],
                        [html.Strong("Complicated tables can be misread."), " For the most important lines, compare the result with the original document."],
                        [html.Strong("Only what is written can be tagged."), " If a budget does not say what the money is for, we cannot tell."],
                        [html.Strong("Currencies are not converted."), " Amounts are shown in the currency of each document."],
                        [html.Strong("Your document is not stored."), " It is removed when you close or refresh the page. Download your results first if you want to keep them."],
                        [html.Strong("This is a demonstration."), " Your document is read by an online AI service, so please do not upload documents that must stay confidential."]])),
        _section("words", "Words used in this tool", _table(["Word", "Meaning"], [
            ["Budget line", "One programme, sub-programme, project or activity in a budget, with its amount."],
            ["Mitigation (CM)", "Actions that cut greenhouse gas emissions or absorb more of them."],
            ["Adaptation (CA)", "Actions that help people and places cope with the effects of climate change."],
            ["Both (CB)", "A line with mitigation and adaptation parts."],
            ["Level", "The class of a climate-tagged line (100, 70, 40 or 20): the part of the line counted as climate spending."],
            ["Service cost", "Salaries, equipment, upkeep or management that support a whole programme or ministry."],
            ["Climate share", "The part of the budget, in percent, counted as climate spending."]]))]


def layout() -> html.Div:
    return html.Div([
        ui.page_intro("How budgets are tagged", "A short guide, in plain words, to how this tool applies the Georgian climate budget tagging method.",
                      eyebrow="Methodology"),
        html.Div(className="section-inner doc-layout", children=[
            html.Nav(className="doc-toc", **{"aria-label": "On this page"}, children=[
                html.Div("On this page", className="doc-toc-title"), *[html.A(title, href="#" + sid) for sid, title in SECTIONS]]),
            html.Div(className="doc-body", children=_body())])])
