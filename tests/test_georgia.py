"""Georgian Taxonomy: its own instructions, the four levels, the arithmetic, and how it sits next to Rio and EU."""

import pandas as pd
import pytest

from ai import prompt, ratelimit, tasks
from ai.types import AIServerError
from tagging.georgia import georgia_frame, summarize_georgia
from tagging.pipeline import analyse_document
from tests.conftest import noop_progress
from tests.fake_llm import FakeProvider
from utils import constants as C


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(ratelimit, "_sleep", lambda seconds, cancelled=None: None)


def row(**kw):
    base = {"q1_ghg_related": False, "q2_mitigation_measure": False, "q3_climate_hazard_related": False,
            "q4_adaptation_measure": False, "climate_level": 0, "livability_floor": False, "service_oriented": False,
            "sector": "Water", "function": "Environmental protection", "confidence": "high", "rationale": "r"}
    return {**base, **kw}


MIT = dict(q1_ghg_related=True, q2_mitigation_measure=True)
ADA = dict(q3_climate_hazard_related=True, q4_adaptation_measure=True)


# ── the verdict ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("given, level", [(100, 100), (70, 70), (40, 40), (20, 20), (37, 40), ("70%", 70), (55, 40),
                                          (0, 20), (None, 20), (250, 100)])
def test_a_climate_tagged_line_always_gets_one_of_the_four_levels(given, level):
    assert tasks.geo_verdict_from_row(row(climate_level=given, **MIT)).level == level


def test_a_line_that_is_not_climate_tagged_has_no_level():
    v = tasks.geo_verdict_from_row(row(climate_level=70, q1_ghg_related=True, q3_climate_hazard_related=True))
    assert (v.mitigation, v.adaptation, v.level) == (False, False, 0)


def test_a_measure_without_its_link_does_not_count():
    v = tasks.geo_verdict_from_row(row(climate_level=100, q2_mitigation_measure=True, q4_adaptation_measure=True))
    assert v.level == 0 and not (v.mitigation or v.adaptation)


def test_service_costs_are_not_tagged():
    v = tasks.geo_verdict_from_row(row(climate_level=100, service_oriented=True, livability_floor=True, **MIT))
    assert v.level == 0 and v.service_oriented and not v.mitigation and not v.floor_only


def test_liveable_wording_alone_counts_as_adaptation_at_level_20():
    v = tasks.geo_verdict_from_row(row(livability_floor=True, climate_level=0))
    assert (v.adaptation, v.mitigation, v.level, v.floor_only) == (True, False, C.GEO_FLOOR_LEVEL, True)


def test_unknown_values_are_made_safe():
    v = tasks.geo_verdict_from_row(row(sector="Space", function="Magic", confidence="sure", **ADA, climate_level=40))
    assert (v.sector, v.function, v.confidence) == ("None", "Not known", C.CONF_MEDIUM)


# ── the instructions stay apart ─────────────────────────────────────────────
def test_the_georgian_instructions_are_separate_from_rio_and_eu():
    assert "Climate Budget Tagging in Georgia" in prompt.GEO_TAG_SYSTEM and "RIO MARKERS" not in prompt.GEO_TAG_SYSTEM
    assert "EU TAXONOMY" not in prompt.GEO_TAG_SYSTEM and "Georgia" not in prompt.TAG_SYSTEM
    assert prompt.GEO_TAG_SYSTEM.rstrip().endswith(prompt.UNTRUSTED)
    for level in C.GEO_LEVELS:
        assert "- %d:" % level in prompt.GEO_TAG_SYSTEM


# ── the arithmetic ──────────────────────────────────────────────────────────
def frame(rows, amounts):
    base = pd.DataFrame({"line": range(1, len(rows) + 1), "page": 1, "code": None, "ministry": ["M1", "M2", "M1", "M2"][:len(rows)],
                         "programme": ["P%d" % i for i in range(len(rows))], "description": None, "function_code": None,
                         "amount": amounts})
    verdicts = {i + 1: tasks.geo_verdict_from_row(r) for i, r in enumerate(rows)}
    return georgia_frame(base, verdicts, list(range(1, len(rows) + 1)))


def test_climate_parts_follow_the_level_and_split_both_half_and_half():
    df = frame([row(climate_level=70, **MIT, **ADA), row(climate_level=40, **MIT), row(climate_level=20, **ADA), row()],
               [100.0, 50.0, 200.0, 650.0])
    assert list(df["geo_code"]) == [C.GEO_CB, C.GEO_CM, C.GEO_CA, ""]
    assert list(df["mitigation_amount"]) == [35.0, 20.0, 0.0, 0.0] and list(df["adaptation_amount"]) == [35.0, 0.0, 40.0, 0.0]
    assert (df["climate_amount"] <= df["amount"]).all()
    s = summarize_georgia(df)
    assert s["climate"] == pytest.approx(130.0) and s["climate_share"] == pytest.approx(0.13)
    assert s["mitigation_share"] + s["adaptation_share"] == pytest.approx(s["climate_share"])
    assert s["tagged_lines"] == 3 and s["code_lines"] == {C.GEO_CM: 1, C.GEO_CA: 1, C.GEO_CB: 1}
    assert list(s["by_level"].index) == list(C.GEO_LEVELS) and s["by_level"].at[100, "lines"] == 0
    assert sum(s["level_of_climate"][lv] or 0 for lv in C.GEO_LEVELS) == pytest.approx(1.0)
    assert s["by_ministry"]["climate"].sum() == pytest.approx(130.0) and s["floor_lines"].empty


def test_lines_without_a_verdict_are_shown_as_not_assessed():
    df = frame([row(**MIT, climate_level=100), row()], [10.0, 10.0])
    df = georgia_frame(df[["line", "page", "code", "ministry", "programme", "description", "function_code", "amount"]], {}, [1, 2])
    assert set(df["tag_method"]) == {C.GEO_DECIDED_MISSING} and df["climate_amount"].sum() == 0


# ── next to Rio and EU ──────────────────────────────────────────────────────
def test_every_line_gets_a_georgian_tag_in_its_own_calls(fake_ai, green_pdf):
    a = analyse_document(green_pdf, "g.pdf", noop_progress)
    assert list(a.georgia["line"]) == list(a.rio["line"]) and a.georgia["amount"].equals(a.rio["amount"])
    geo_calls = [c for c in fake_ai.calls if "georgia" in c["schema"]["properties"]]
    assert geo_calls and all(c["system"] == prompt.GEO_TAG_SYSTEM for c in geo_calls)
    assert all(c["system"] != prompt.GEO_TAG_SYSTEM for c in fake_ai.calls if "tags" in c["schema"]["properties"])
    assert set(a.georgia.loc[a.georgia["geo_code"] != "", "geo_level"]) <= set(C.GEO_LEVELS)
    assert (a.georgia.loc[a.georgia["geo_code"] == "", "geo_level"] == 0).all()
    assert 0 < a.georgia_summary["climate_share"] < 1


def test_when_the_georgian_pass_fails_rio_and_eu_are_kept(use_provider, green_pdf):
    class NoGeorgia(FakeProvider):
        def generate_json(self, system, prompt_text, schema, attachments=(), max_output_tokens=0, temperature=0.0):
            if "georgia" in schema["properties"]:
                raise AIServerError("503")
            return super().generate_json(system, prompt_text, schema, attachments, max_output_tokens, temperature)

    use_provider(NoGeorgia())
    a = analyse_document(green_pdf, "g.pdf", noop_progress)
    assert a.rio_summary["weighted_share"] > 0 and a.eu_summary["green_share"] > 0
    assert set(a.georgia["tag_method"]) == {C.GEO_DECIDED_MISSING} and a.georgia_summary["climate_share"] == 0
    assert any("Georgian Taxonomy could not be applied" in i["message"] for i in a.issues)
