"""tagging/pipeline.py: whole analyses on the sample documents, and the two-budget comparison."""

import os
from pathlib import Path

import pymupdf
import pytest

from ai import ratelimit, tasks
from ai.types import AIConfigError, AIQuotaError, AIResponseError, AIServerError, Cancelled
from tagging import pipeline
from tagging.pipeline import AnalysisError, analyse_document, brief, compare_budgets
from tests.conftest import noop_progress
from tests.fake_llm import FakeProvider
from utils import constants as C
from utils import documents


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Retries back off for real in production; here they return at once."""
    monkeypatch.setattr(ratelimit, "_sleep", lambda seconds, cancelled=None: None)


def analyse(data, name, cancelled=None):
    return analyse_document(data, name, noop_progress, cancelled)


class Variant(FakeProvider):
    """A FakeProvider whose answers can be bent for one kind of call."""

    def __init__(self, extract=None, tag=None, **kw):
        super().__init__(**kw)
        self.extract_hook, self.tag_hook = extract, tag

    def generate_json(self, system, prompt, schema, attachments=(), max_output_tokens=0, temperature=0.0):
        out = super().generate_json(system, prompt, schema, attachments, max_output_tokens, temperature)
        if "lines" in schema["properties"] and self.extract_hook:
            return self.extract_hook(out)
        if "tags" in schema["properties"] and self.tag_hook:
            return self.tag_hook(out)
        return out


# ── a normal analysis ───────────────────────────────────────────────────────
def test_green_budget_is_greener_than_the_traditional_one(fake_ai, green_pdf, traditional_pdf):
    g, t = analyse(green_pdf, "g.pdf"), analyse(traditional_pdf, "t.pdf")
    assert g.rio_summary["weighted_share"] > 10 * t.rio_summary["weighted_share"]
    assert g.eu_summary["green_share"] > 10 * t.eu_summary["green_share"]
    assert g.rio_summary["basis"] == t.rio_summary["basis"] == "amount"


def test_totals_are_not_counted_as_lines(fake_ai, green_pdf):
    a = analyse(green_pdf, "g.pdf")
    assert not a.rio["programme"].str.lower().str.startswith("total").any()
    assert a.rio_summary["total_amount"] == pytest.approx(a.rio["amount"].sum())


def test_both_taxonomies_cover_the_same_lines(fake_ai, green_pdf):
    a = analyse(green_pdf, "g.pdf")
    assert list(a.rio["line"]) == list(a.eu["line"]) == list(range(1, len(a.rio) + 1))
    assert a.rio["amount"].equals(a.eu["amount"]) and a.stats["lines"] == len(a.rio)
    assert set(a.rio["rio_marker"]) <= {0, 1, 2} and set(a.eu["climate_tag"]) <= {C.TAG_GREEN, C.TAG_BROWN, C.TAG_NEUTRAL}


def test_the_document_is_described_from_its_first_pages(fake_ai, green_pdf):
    a = analyse(green_pdf, "g.pdf")
    assert a.info.country == "Testland" and a.info.year == 2025 and a.name == "Sample Budget 2025" and a.subtitle == "Testland · 2025"


def test_word_and_pdf_versions_find_the_same_projects(fake_ai, project_pdf, project_docx):
    p, d = analyse(project_pdf, "p.pdf"), analyse(project_docx, "p.docx")
    assert d.stats["lines"] >= 5 and p.stats["lines"] >= 5
    assert "early warning system" in {t.lower() for t in p.rio["programme"]} & {t.lower() for t in d.rio["programme"]}
    assert d.eu_summary["green_share"] > 0.3 and p.eu_summary["green_share"] > 0.3


def test_progress_walks_through_the_stages_in_order(fake_ai, green_pdf):
    seen = []
    analyse_document(green_pdf, "g.pdf", lambda stage, detail="": seen.append(stage))
    order = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    assert order == [C.STAGE_READ, C.STAGE_FIND, C.STAGE_TAG, C.STAGE_CALC]


def test_identical_lines_are_tagged_once(use_provider, green_pdf):
    provider = use_provider(Variant(extract=lambda out: {"lines": out["lines"] + out["lines"]}))
    a = analyse(green_pdf, "g.pdf")
    tagged = sum(len(c["prompt"].split("\n[")) - 1 for c in provider.calls if "tags" in c["schema"]["properties"])
    assert a.stats["unique_classifications"] <= tagged <= a.stats["lines"]


# ── things that go wrong ────────────────────────────────────────────────────
def test_a_document_without_budget_lines_gives_a_clear_message(use_provider, green_pdf):
    use_provider(Variant(extract=lambda out: {"lines": []}))
    with pytest.raises(AnalysisError, match="could not find any budget lines"):
        analyse(green_pdf, "g.pdf")


def test_a_file_that_is_not_a_document_gives_a_clear_message(fake_ai):
    with pytest.raises(AnalysisError, match="PDF or Word"):
        analyse(b"hello", "notes.txt")
    with pytest.raises(AnalysisError):
        analyse(b"%PDF-1.4 this is not really a pdf", "broken.pdf")
    with pytest.raises(AnalysisError, match="empty"):
        analyse(b"", "empty.pdf")


@pytest.mark.parametrize("error", [AIConfigError("API key invalid 403"), AIQuotaError("RESOURCE_EXHAUSTED per day"), AIServerError("503 UNAVAILABLE")])
def test_ai_problems_become_plain_messages(use_provider, green_pdf, error):
    use_provider(FakeProvider(fail_first=99, error=error))
    with pytest.raises(AnalysisError) as caught:
        analyse(green_pdf, "g.pdf")
    assert str(caught.value) == error.user_message
    assert str(error) not in str(caught.value)


def test_when_tagging_fails_for_every_line_the_analysis_stops(use_provider, green_pdf):
    class NoTags(FakeProvider):
        def generate_json(self, system, prompt, schema, attachments=(), max_output_tokens=0, temperature=0.0):
            if "tags" in schema["properties"]:
                raise AIResponseError("Empty answer")
            return super().generate_json(system, prompt, schema, attachments, max_output_tokens, temperature)

    use_provider(NoTags())
    with pytest.raises(AnalysisError):
        analyse(green_pdf, "g.pdf")


def test_lines_the_ai_skipped_fall_back_to_keywords_and_say_so(use_provider, green_pdf):
    def drop_some(out):
        return {"tags": [t for t in out["tags"] if t["id"] % 4]}

    use_provider(Variant(tag=drop_some))
    a = analyse(green_pdf, "g.pdf")
    assert a.stats["rules_only"] > 0
    assert any("checked with keywords only" in i["message"] for i in a.issues)
    assert (a.rio["tag_method"] == C.DECIDED_RULES).sum() > 0 and (a.eu["tag_method"] == C.DECIDED_RULES).sum() > 0
    assert len(a.rio) == a.stats["lines"]


def multi_page_pdf(pages=6, rows=12):
    doc = pymupdf.open()
    for n in range(pages):
        page = doc.new_page()
        for k in range(rows):
            title = "Solar power programme" if (n, k) == (2, 0) else "Rural service %d-%d" % (n, k)
            page.insert_text((40, 60 + 14 * k), "%s   %d,000.0" % (title, 10 + k), fontsize=9)
    return doc.tobytes()


def test_a_section_that_cannot_be_read_is_reported_and_the_rest_is_kept(use_provider, monkeypatch):
    monkeypatch.setattr(tasks, "make_chunks", lambda doc: documents.make_chunks(doc, 700))

    class OneBadSection(FakeProvider):
        def generate_json(self, system, prompt, schema, attachments=(), max_output_tokens=0, temperature=0.0):
            if "lines" in schema["properties"] and "Solar power programme" in prompt:
                raise AIResponseError("Empty answer")
            return super().generate_json(system, prompt, schema, attachments, max_output_tokens, temperature)

    use_provider(OneBadSection())
    a = analyse(multi_page_pdf(), "long.pdf")
    assert a.stats["sections"] > 1 and a.stats["lines"] > 20
    assert any("could not be read" in i["message"] for i in a.issues)
    assert "solar power programme" not in {t.lower() for t in a.rio["programme"]}


def test_a_budget_without_amounts_is_counted_by_lines(use_provider, green_pdf):
    def no_amounts(out):
        return {"lines": [dict(r, amount="") for r in out["lines"]]}

    use_provider(Variant(extract=no_amounts))
    a = analyse(green_pdf, "g.pdf")
    assert a.rio_summary["basis"] == "lines" and a.rio_summary["has_amount"] is False
    assert any("number of budget lines" in i["message"] for i in a.issues)


def test_cancelling_raises_cancelled_not_a_user_error(fake_ai, green_pdf):
    with pytest.raises(Cancelled):
        analyse(green_pdf, "g.pdf", cancelled=lambda: True)


def test_cancelling_midway_stops_before_tagging(use_provider, green_pdf):
    provider = use_provider(FakeProvider())
    state = {"stop": False}

    def progress(stage, detail=""):
        if stage == C.STAGE_FIND:
            state["stop"] = True

    with pytest.raises(Cancelled):
        analyse_document(green_pdf, "g.pdf", progress, lambda: state["stop"])
    assert not any("tags" in c["schema"]["properties"] for c in provider.calls)


def test_a_very_long_document_is_limited_with_a_notice(use_provider, monkeypatch, green_pdf):
    monkeypatch.setattr(C, "MAX_UNIQUE_LINES", 5)
    use_provider(FakeProvider())
    a = analyse(green_pdf, "g.pdf")
    assert a.stats["lines"] == 5 and any("largest" in i["message"] for i in a.issues)


# ── comparing two budgets ───────────────────────────────────────────────────
@pytest.fixture
def pair(fake_ai, green_pdf, traditional_pdf):
    return analyse(green_pdf, "g.pdf"), analyse(traditional_pdf, "t.pdf")


def test_the_greener_budget_scores_higher(pair):
    a, b = pair
    c = compare_budgets(a, b)
    assert c.scores["A"] > c.scores["B"] and 0 <= c.scores["B"] <= 100 and c.summary == "Fake summary."
    assert set(c.reasons) == {"A", "B"} and all(c.reasons.values())


def test_the_ai_score_cannot_stray_far_from_the_numbers(pair, use_provider):
    a, b = pair

    class Wild(FakeProvider):
        def _score(self, prompt):
            return {"budgets": [{"label": "A", "score": 0, "reason": "low"}, {"label": "B", "score": 100, "reason": "high"}], "summary": "s"}

    use_provider(Wild())
    c = compare_budgets(a, b)
    for key in "AB":
        guard = c.rubric[key]["score"]
        assert abs(c.scores[key] - guard) <= pipeline.SCORE_GUARD
    assert c.scores["A"] > c.scores["B"], "a clearly greener budget must not end up below"


def test_when_scoring_fails_the_numbers_alone_decide(pair, use_provider):
    a, b = pair

    class NoScore(FakeProvider):
        def _score(self, prompt):
            raise AIResponseError("Empty answer")

    use_provider(NoScore())
    c = compare_budgets(a, b)
    assert c.scores == {k: c.rubric[k]["score"] for k in "AB"}
    assert "scores higher" in c.summary and "supports climate goals" in c.reasons["A"]


@pytest.mark.parametrize("error", [AIConfigError("k"), AIQuotaError("q"), Cancelled()])
def test_scoring_problems_that_matter_are_not_hidden(pair, use_provider, error):
    a, b = pair

    class Broken(FakeProvider):
        def _score(self, prompt):
            raise error

    use_provider(Broken())
    with pytest.raises(type(error)):
        compare_budgets(a, b)


def test_equal_budgets_get_a_fair_summary(fake_ai, use_provider, green_pdf):
    a, b = analyse(green_pdf, "a.pdf"), analyse(green_pdf, "b.pdf")

    class Silent(FakeProvider):
        def _score(self, prompt):
            raise AIResponseError("x")

    use_provider(Silent())
    c = compare_budgets(a, b)
    assert c.scores["A"] == c.scores["B"] and c.summary == "Both budgets score the same overall."


def test_the_brief_sent_to_the_ai_has_numbers_not_documents(pair):
    a, _ = pair
    b = brief(a, "A")
    assert b["label"] == "A" and b["weighted_share"].endswith("%") and b["top_green"] and len(b["top_green"]) <= 5
    assert all(len(t) <= 90 for t in b["top_green"])
    assert a.name in b["name"] and "Testland" in b["name"]


# ── optional: real documents, when you have them ────────────────────────────
REAL = os.getenv("CBT_REAL_DOCS", "")


@pytest.mark.skipif(not REAL, reason="set CBT_REAL_DOCS to a folder of real PDFs to try them with the stand-in AI")
@pytest.mark.parametrize("path", sorted(Path(REAL).glob("*.pdf")) if REAL else [])
def test_real_documents_run_through(fake_ai, path):
    a = analyse(path.read_bytes(), path.name)
    assert a.stats["lines"] > 0 and 0 <= a.rio_summary["weighted_share"] <= 1
