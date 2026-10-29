"""The AI is primary. The keyword check can confirm it, lower its confidence or ask for a second look - never make it greener."""

import pytest

from tagging.models import AIVerdict, EUResult, RioResult
from tagging.reconcile import combine_eu, combine_rio
from utils import constants as C


def rio_rule(mit=0, ada=0, method="RIO_MARKER"):
    return RioResult(max(mit, ada), mit, ada, method, "keyword note")


def eu_rule(tag=C.TAG_NEUTRAL, objectives=(), method="EU_TAXONOMY"):
    flags = {k: k in objectives for k in C.EU_OBJECTIVES}
    return EUResult(tag, flags, objectives[0] if objectives else "none", method, "keyword note")


def verdict(**kw):
    base = dict(rio_mitigation=0, rio_adaptation=0, eu_objectives=[], brown=False, administrative=False, confidence=C.CONF_HIGH, rationale="AI note")
    base.update(kw)
    return AIVerdict(**base)


def test_without_an_ai_answer_the_keyword_check_decides_with_low_confidence():
    r = combine_rio(None, rio_rule(mit=2))
    assert (r["rio_marker"], r["tag_method"], r["confidence"]) == (2, C.DECIDED_RULES, C.CONF_LOW) and "unavailable" in r["rationale"]
    e = combine_eu(None, eu_rule(C.TAG_GREEN, ["water"]))
    assert (e["climate_tag"], e["eu_water"], e["tag_method"], e["confidence"]) == (C.TAG_GREEN, True, C.DECIDED_RULES, C.CONF_LOW)


def test_administrative_lines_score_zero_everywhere():
    v = verdict(administrative=True, rio_mitigation=2)
    r, e = combine_rio(v, rio_rule(0)), combine_eu(v, eu_rule())
    assert (r["rio_marker"], r["tag_method"], r["confidence"]) == (0, C.DECIDED_ADMIN, C.CONF_HIGH)
    assert (e["climate_tag"], e["tag_method"]) == (C.TAG_NEUTRAL, C.DECIDED_ADMIN) and not any(e[C.EU_FLAG_COLUMNS[k]] for k in C.EU_OBJECTIVES)
    assert combine_rio(v, rio_rule(2))["confidence"] == C.CONF_MEDIUM, "keywords see climate in an 'administrative' line: less sure"


@pytest.mark.parametrize("ai_mit,ai_ada,rule_mit,rule_ada,marker,decided,conf", [
    (2, 0, 2, 0, 2, C.DECIDED_CONFIRMED, C.CONF_HIGH),      # both agree
    (2, 0, 1, 0, 2, C.DECIDED_CONFIRMED, C.CONF_MEDIUM),    # both see climate, but not at the same level
    (1, 0, 0, 0, 1, C.DECIDED_AI_ONLY, C.CONF_MEDIUM),      # only the AI sees climate
    (0, 2, 0, 1, 2, C.DECIDED_CONFIRMED, C.CONF_MEDIUM),
    (0, 0, 0, 0, 0, C.DECIDED_NONE, C.CONF_HIGH),           # neither sees climate
    (0, 0, 1, 0, 0, C.DECIDED_REVIEW, C.CONF_LOW),          # only the keywords see climate: not counted, flagged
])
def test_rio_reconciliation(ai_mit, ai_ada, rule_mit, rule_ada, marker, decided, conf):
    r = combine_rio(verdict(rio_mitigation=ai_mit, rio_adaptation=ai_ada), rio_rule(rule_mit, rule_ada))
    assert (r["rio_marker"], r["tag_method"], r["confidence"]) == (marker, decided, conf)
    assert r["climate_tag"] == (C.TAG_GREEN if marker else C.TAG_NEUTRAL)
    assert r["rio_marker"] <= max(ai_mit, ai_ada), "keywords never raise the marker"


def test_rio_rows_carry_the_columns_the_pages_need():
    r = combine_rio(verdict(rio_mitigation=2, rio_adaptation=1), rio_rule(2))
    assert r["environmental_objective"] == "both" and r["subcategory"] == "principal" and r["rationale"] == "AI note"
    assert combine_rio(verdict(rio_adaptation=1), rio_rule(0, 1))["subcategory"] == "significant"


def test_eu_green_needs_the_ai_to_name_an_objective():
    e = combine_eu(verdict(eu_objectives=["water", "pollution"]), eu_rule(C.TAG_GREEN, ["water"]))
    assert (e["climate_tag"], e["eu_primary_objective"], e["tag_method"], e["confidence"]) == (C.TAG_GREEN, "water", C.DECIDED_CONFIRMED, C.CONF_HIGH)
    assert e["eu_water"] and e["eu_pollution"] and not e["eu_mitigation"]
    e = combine_eu(verdict(eu_objectives=["water"]), eu_rule(C.TAG_GREEN, ["mitigation"]))
    assert e["confidence"] == C.CONF_MEDIUM, "different main objective: less sure"
    e = combine_eu(verdict(eu_objectives=["water"]), eu_rule())
    assert (e["tag_method"], e["confidence"], e["climate_tag"]) == (C.DECIDED_AI_ONLY, C.CONF_MEDIUM, C.TAG_GREEN)


def test_eu_keywords_alone_never_make_a_line_green():
    e = combine_eu(verdict(), eu_rule(C.TAG_GREEN, ["mitigation"]))
    assert (e["climate_tag"], e["tag_method"], e["confidence"]) == (C.TAG_NEUTRAL, C.DECIDED_REVIEW, C.CONF_LOW)
    assert combine_eu(verdict(), eu_rule())["tag_method"] == C.DECIDED_NONE


def test_brown_lines_serve_no_objective():
    e = combine_eu(verdict(brown=True, eu_objectives=["mitigation"]), eu_rule(C.TAG_BROWN))
    assert (e["climate_tag"], e["tag_method"], e["confidence"]) == (C.TAG_BROWN, C.DECIDED_BROWN, C.CONF_HIGH)
    e = combine_eu(verdict(brown=True), eu_rule())
    assert (e["tag_method"], e["confidence"]) == (C.DECIDED_BROWN, C.CONF_MEDIUM)
    e = combine_eu(verdict(brown=True), eu_rule(C.TAG_GREEN, ["mitigation"]))
    assert (e["climate_tag"], e["tag_method"]) == (C.TAG_BROWN, C.DECIDED_REVIEW)


def test_a_green_ai_answer_against_a_brown_keyword_check_is_flagged():
    e = combine_eu(verdict(eu_objectives=["mitigation"]), eu_rule(C.TAG_BROWN))
    assert (e["tag_method"], e["confidence"]) == (C.DECIDED_REVIEW, C.CONF_LOW)
