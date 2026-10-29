"""ai/tasks.py: the four AI jobs, driven by a scripted stand-in provider."""

import re
import threading

import pymupdf
import pytest

from ai import tasks
from ai.types import AIConfigError, AIQuotaError, AIResponseError, AIServerError, Cancelled, DocInfo
from tests.conftest import noop_progress
from utils import constants as C
from utils.documents import read_document


class Scripted:
    """A provider whose answers come from a function(kind, prompt, attachments) -> json, or raise."""

    def __init__(self, fn):
        self.fn, self.calls, self.lock = fn, [], threading.Lock()

    def is_configured(self):
        return True

    def model_name(self):
        return "scripted"

    def generate_json(self, system, prompt, schema, attachments=(), max_output_tokens=0, temperature=0.0):
        kind = "tags" if "tags" in schema["properties"] else "lines" if "lines" in schema["properties"] else "budgets" if "budgets" in schema["properties"] else "describe"
        with self.lock:
            self.calls.append((kind, prompt, len(attachments)))
        return self.fn(kind, prompt, attachments)


def doc_with(pages, rows=40):
    d = pymupdf.open()
    for i in range(pages):
        p = d.new_page()
        for k in range(rows):
            p.insert_text((40, 40 + 11 * k), "Programme %d-%d budget item %d %d,000.0" % (i, k, i, k), fontsize=8)
    return read_document(d.tobytes(), "doc.pdf")


def line_rows(prompt, n=2):
    first = int(re.search(r"\[Page (\d+)\]", prompt).group(1))
    return {"lines": [{"code": "", "ministry": "", "title": "L%d-%d" % (first, i), "description": "", "function_code": "",
                       "amount": "10", "kind": "programme", "page": first} for i in range(n)]}


def tag_rows(prompt, skip=()):
    ids = [int(x) for x in re.findall(r"^\[(\d+)\] Title", prompt, re.M)]
    return {"tags": [{"id": i, "rio_mitigation": 1, "rio_adaptation": 0, "eu_objectives": ["mitigation"], "brown": False,
                      "administrative": False, "confidence": "high", "rationale": "ok"} for i in ids if i not in skip]}


# ── describe ────────────────────────────────────────────────────────────────
def test_describe_reads_the_answer(use_provider, green_pdf):
    use_provider(Scripted(lambda k, p, a: {"name": "Examplia Budget", "country": "Examplia", "year": 2025, "currency": "EXM",
                                           "unit": "millions", "document_type": "ministry budget"}))
    info = tasks.describe_document(read_document(green_pdf, "green.pdf"))
    assert (info.name, info.country, info.year, info.unit, info.unit_text) == ("Examplia Budget", "Examplia", 2025, "millions", "million EXM")


def test_describe_cleans_odd_answers(use_provider, green_pdf):
    use_provider(Scripted(lambda k, p, a: {"name": "", "country": "X" * 200, "year": 3025, "currency": "EXM", "unit": "lakhs", "document_type": "?"}))
    info = tasks.describe_document(read_document(green_pdf, "my_budget_file.pdf"))
    assert info.name == "my budget file" and len(info.country) == 60 and info.year == 0 and info.unit == "units"


def test_describe_falls_back_when_the_ai_cannot_answer(use_provider, green_pdf):
    def boom(k, p, a):
        raise AIResponseError("empty")
    use_provider(Scripted(boom))
    assert tasks.describe_document(read_document(green_pdf, "Kenya_budget.pdf")).name == "Kenya budget"


@pytest.mark.parametrize("error", [AIConfigError("key"), AIQuotaError("daily"), Cancelled()])
def test_describe_passes_fatal_errors_on(use_provider, green_pdf, error):
    def boom(k, p, a):
        raise error
    use_provider(Scripted(boom))
    with pytest.raises(type(error)):
        tasks.describe_document(read_document(green_pdf, "x.pdf"))


# ── extract ─────────────────────────────────────────────────────────────────
def test_extraction_reads_every_section_in_order(use_provider):
    doc = doc_with(12)
    provider = use_provider(Scripted(lambda k, p, a: line_rows(p)))
    seen = []
    result = tasks.extract_budget_lines(doc, DocInfo(), lambda stage, detail="": seen.append((stage, detail)))
    assert result.sections > 1 and len(provider.calls) == result.sections and not result.failed_sections
    firsts = [int(r["title"].split("-")[0][1:]) for r in result.records]
    assert firsts == sorted(firsts) and len(result.records) == 2 * result.sections
    assert seen[0] == (C.STAGE_FIND, "Section 0 of %d" % result.sections) and seen[-1][1] == "Section %d of %d" % (result.sections, result.sections)


def test_a_cut_off_answer_is_retried_on_smaller_sections(use_provider):
    doc = doc_with(8)

    def answer(kind, prompt, attachments):
        pages = len(re.findall(r"\[Page \d+\]", prompt))
        if pages > 2:
            raise AIResponseError("The answer was cut off", truncated=True)
        return line_rows(prompt)

    provider = use_provider(Scripted(answer))
    result = tasks.extract_budget_lines(doc, DocInfo(), noop_progress)
    assert not result.failed_sections and len(result.records) >= 8
    assert all(len(re.findall(r"\[Page \d+\]", c[1])) <= 2 or c[0] == "lines" for c in provider.calls)


def test_a_section_that_keeps_failing_is_reported_and_the_rest_is_kept(use_provider):
    doc = doc_with(12)

    def answer(kind, prompt, attachments):
        if "[Page 1]" in prompt:
            raise AIResponseError("Empty answer")
        return line_rows(prompt)

    use_provider(Scripted(answer))
    result = tasks.extract_budget_lines(doc, DocInfo(), noop_progress)
    assert len(result.failed_sections) == 1 and result.failed_sections[0].startswith("page")
    assert result.records, "other sections still count"


def test_every_section_failing_is_an_error(use_provider):
    def answer(kind, prompt, attachments):
        raise AIResponseError("Empty answer")
    use_provider(Scripted(answer))
    with pytest.raises(AIServerError):
        tasks.extract_budget_lines(doc_with(6), DocInfo(), noop_progress)


def test_a_blocked_answer_is_retried_without_the_attached_pages(use_provider, green_pdf):
    doc = read_document(green_pdf, "green.pdf")
    doc.pages[0].table_like = True

    def answer(kind, prompt, attachments):
        if attachments:
            raise AIResponseError("blocked", blocked=True)
        return line_rows(prompt)

    provider = use_provider(Scripted(answer))
    result = tasks.extract_budget_lines(doc, DocInfo(), noop_progress)
    assert [c[2] for c in provider.calls] == [1, 0] and result.records


def test_a_fatal_error_stops_the_other_sections(use_provider):
    def answer(kind, prompt, attachments):
        raise AIQuotaError("daily limit")
    use_provider(Scripted(answer))
    with pytest.raises(AIQuotaError):
        tasks.extract_budget_lines(doc_with(12), DocInfo(), noop_progress)


def test_cancelling_stops_extraction(use_provider):
    use_provider(Scripted(lambda k, p, a: line_rows(p)))
    with pytest.raises(Cancelled):
        tasks.extract_budget_lines(doc_with(6), DocInfo(), noop_progress, cancelled=lambda: True)


# ── tag ─────────────────────────────────────────────────────────────────────
def items(n):
    return [{"id": i, "title": "Item %d" % i, "ministry": "", "description": "", "function_code": ""} for i in range(1, n + 1)]


def test_every_line_gets_a_verdict(use_provider):
    provider = use_provider(Scripted(lambda k, p, a: tag_rows(p)))
    verdicts = tasks.tag_budget_lines(items(130), noop_progress)
    assert sorted(verdicts) == list(range(1, 131)) and len(provider.calls) == 3
    assert verdicts[1].rio_mitigation == 1 and verdicts[1].eu_objectives == ["mitigation"] and verdicts[1].confidence == C.CONF_HIGH


def test_lines_the_ai_skipped_are_asked_again(use_provider):
    calls = []

    def answer(kind, prompt, attachments):
        calls.append(prompt)
        return tag_rows(prompt, skip={3, 7} if len(calls) == 1 else ())

    use_provider(Scripted(answer))
    verdicts = tasks.tag_budget_lines(items(10), noop_progress)
    assert sorted(verdicts) == list(range(1, 11)) and len(calls) == 2 and "[3] Title" in calls[1] and "[1] Title" not in calls[1]


def test_lines_that_stay_missing_are_left_out_not_invented(use_provider):
    use_provider(Scripted(lambda k, p, a: tag_rows(p, skip={4})))
    verdicts = tasks.tag_budget_lines(items(6), noop_progress)
    assert 4 not in verdicts and sorted(verdicts) == [1, 2, 3, 5, 6]


def test_unknown_ids_and_junk_rows_are_ignored(use_provider):
    def answer(kind, prompt, attachments):
        rows = tag_rows(prompt)["tags"] + [{"id": 999, "rio_mitigation": 2}, {"id": "x"}, "junk", {"nothing": 1}]
        return {"tags": rows}
    use_provider(Scripted(answer))
    assert sorted(tasks.tag_budget_lines(items(3), noop_progress)) == [1, 2, 3]


def test_a_cut_off_tag_answer_is_retried_in_halves(use_provider):
    def answer(kind, prompt, attachments):
        if len(re.findall(r"^\[\d+\] Title", prompt, re.M)) > 20:
            raise AIResponseError("cut off", truncated=True)
        return tag_rows(prompt)
    use_provider(Scripted(answer))
    assert len(tasks.tag_budget_lines(items(60), noop_progress)) == 60


def test_no_verdicts_at_all_is_an_error(use_provider):
    def answer(kind, prompt, attachments):
        raise AIResponseError("Empty answer")
    use_provider(Scripted(answer))
    with pytest.raises(AIResponseError):
        tasks.tag_budget_lines(items(5), noop_progress)


def test_progress_counts_lines(use_provider):
    use_provider(Scripted(lambda k, p, a: tag_rows(p)))
    seen = []
    tasks.tag_budget_lines(items(70), lambda stage, detail="": seen.append(detail))
    assert seen[0] == "0 of 70 lines" and seen[-1] == "70 of 70 lines"


@pytest.mark.parametrize("row,expected", [
    ({"rio_mitigation": 5, "rio_adaptation": -3, "eu_objectives": ["water", "water", "nonsense"], "confidence": "LOW"},
     dict(rio_mitigation=2, rio_adaptation=0, eu_objectives=["water"], confidence="LOW")),
    ({"rio_mitigation": "2", "administrative": True, "eu_objectives": ["water"], "brown": True},
     dict(rio_mitigation=0, eu_objectives=[], brown=False, administrative=True)),
    ({"rio_mitigation": 2, "brown": True, "eu_objectives": ["mitigation"]}, dict(rio_mitigation=0, eu_objectives=[], brown=True)),
    ({"rio_mitigation": None, "confidence": "certain"}, dict(rio_mitigation=0, confidence="MEDIUM")),
])
def test_verdicts_are_made_consistent(row, expected):
    v = tasks.verdict_from_row(row)
    for key, value in expected.items():
        assert getattr(v, key) == value


# ── score ───────────────────────────────────────────────────────────────────
def briefs():
    base = dict(name="Budget", lines=10, basis="amount", weighted_share="20.0%", principal_share="10.0%", significant_share="25.0%",
                mitigation_share="15.0%", adaptation_share="5.0%", green_share="12.0%", brown_share="1.0%", objectives="mitigation 10%")
    return [dict(base, label="A"), dict(base, label="B")]


def test_scores_are_read_and_clamped(use_provider):
    use_provider(Scripted(lambda k, p, a: {"budgets": [{"label": "A", "score": 140, "reason": "x " * 300}, {"label": "B", "score": -5, "reason": "ok"}],
                                           "summary": "Two sentences."}))
    out = tasks.score_budgets(briefs())
    assert out["scores"]["A"][0] == 100 and out["scores"]["B"][0] == 0 and len(out["scores"]["A"][1]) <= 300 and out["summary"] == "Two sentences."


@pytest.mark.parametrize("answer", [{"budgets": [{"label": "A", "score": 10, "reason": "x"}], "summary": ""}, ["not", "an", "object"],
                                    {"budgets": [{"label": "A"}, {"label": "B"}], "summary": ""}])
def test_incomplete_score_answers_are_rejected(use_provider, answer):
    use_provider(Scripted(lambda k, p, a: answer))
    with pytest.raises(AIResponseError):
        tasks.score_budgets(briefs())
