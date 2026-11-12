"""Tagging: consistent verdicts, the four levels, the tagging instructions and the climate arithmetic of every line."""

import pandas as pd
import pytest

import constants as C
from ai import prompt, ratelimit, tasks
from tagging.metrics import summarize
from tagging.tags import tagged_frame
from tagging.pipeline import analyse_document
from tests.conftest import noop_progress


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
    assert tasks.verdict_from_row(row(climate_level=given, **MIT)).level == level


def test_a_line_that_is_not_climate_tagged_has_no_level():
    v = tasks.verdict_from_row(row(climate_level=70, q1_ghg_related=True, q3_climate_hazard_related=True))
    assert (v.mitigation, v.adaptation, v.level) == (False, False, 0)


def test_a_measure_without_its_link_does_not_count():
    v = tasks.verdict_from_row(row(climate_level=100, q2_mitigation_measure=True, q4_adaptation_measure=True))
    assert v.level == 0 and not (v.mitigation or v.adaptation)


def test_service_costs_are_not_tagged():
    v = tasks.verdict_from_row(row(climate_level=100, service_oriented=True, livability_floor=True, **MIT))
    assert v.level == 0 and v.service_oriented and not v.mitigation and not v.floor_only


def test_liveable_wording_alone_counts_as_adaptation_at_level_20():
    v = tasks.verdict_from_row(row(livability_floor=True, climate_level=0))
    assert (v.adaptation, v.mitigation, v.level, v.floor_only) == (True, False, C.FLOOR_LEVEL, True)


def test_unknown_values_are_made_safe():
    v = tasks.verdict_from_row(row(sector="Space", function="Magic", confidence="sure", **ADA, climate_level=40))
    assert (v.sector, v.function, v.confidence) == ("None", "Not known", C.CONF_MEDIUM)


# ── the instructions ────────────────────────────────────────────────────────
def test_the_tagging_instructions_follow_the_handbook():
    assert "Climate Budget Tagging in Georgia" in prompt.TAG_SYSTEM
    assert prompt.TAG_SYSTEM.rstrip().endswith(prompt.UNTRUSTED)
    for words in ("q1_ghg_related", "q4_adaptation_measure", "SERVICE-ORIENTED COSTS", "livability_floor"):
        assert words in prompt.TAG_SYSTEM
    for level in C.LEVELS:
        assert "- %d:" % level in prompt.TAG_SYSTEM


# ── the arithmetic ──────────────────────────────────────────────────────────
def frame(rows, amounts):
    base = pd.DataFrame({"line": range(1, len(rows) + 1), "page": 1, "code": None, "ministry": ["M1", "M2", "M1", "M2"][:len(rows)],
                         "programme": ["P%d" % i for i in range(len(rows))], "description": None, "function_code": None,
                         "amount": amounts})
    verdicts = {i + 1: tasks.verdict_from_row(r) for i, r in enumerate(rows)}
    return tagged_frame(base, verdicts, list(range(1, len(rows) + 1)))


def test_climate_parts_follow_the_level_and_split_both_half_and_half():
    df = frame([row(climate_level=70, **MIT, **ADA), row(climate_level=40, **MIT), row(climate_level=20, **ADA), row()],
               [100.0, 50.0, 200.0, 650.0])
    assert list(df["cbt_code"]) == [C.CB, C.CM, C.CA, ""]
    assert list(df["mitigation_amount"]) == [35.0, 20.0, 0.0, 0.0] and list(df["adaptation_amount"]) == [35.0, 0.0, 40.0, 0.0]
    assert (df["climate_amount"] <= df["amount"]).all()
    s = summarize(df)
    assert s["climate"] == pytest.approx(130.0) and s["climate_share"] == pytest.approx(0.13)
    assert s["mitigation_share"] + s["adaptation_share"] == pytest.approx(s["climate_share"])
    assert s["tagged_lines"] == 3 and s["code_lines"] == {C.CM: 1, C.CA: 1, C.CB: 1}
    assert list(s["by_level"].index) == list(C.LEVELS) and s["by_level"].at[100, "lines"] == 0
    assert sum(s["level_of_climate"][lv] or 0 for lv in C.LEVELS) == pytest.approx(1.0)
    assert s["by_ministry"]["climate"].sum() == pytest.approx(130.0) and s["floor_lines"].empty


def test_lines_without_a_verdict_are_shown_as_not_assessed():
    df = frame([row(**MIT, climate_level=100), row()], [10.0, 10.0])
    df = tagged_frame(df[["line", "page", "code", "ministry", "programme", "description", "function_code", "amount"]], {}, [1, 2])
    assert set(df["tag_method"]) == {C.DECIDED_MISSING} and df["climate_amount"].sum() == 0


# ── a whole document ────────────────────────────────────────────────────────
def test_every_line_gets_a_code_and_level_from_the_tagging_instructions(fake_ai, green_pdf):
    a = analyse_document(green_pdf, "g.pdf", noop_progress)
    tag_calls = [c for c in fake_ai.calls if "tags" in c["schema"]["properties"]]
    assert tag_calls and all(c["system"] == prompt.TAG_SYSTEM for c in tag_calls)
    assert set(a.lines.loc[a.lines["cbt_code"] != "", "climate_level"]) <= set(C.LEVELS)
    assert (a.lines.loc[a.lines["cbt_code"] == "", "climate_level"] == 0).all()
    assert 0 < a.summary["climate_share"] < 1
