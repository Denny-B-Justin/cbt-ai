"""Combine the AI verdict with the keyword check into the final tags of one budget line.

The AI verdict is primary. The keyword check never makes a line greener: it confirms the AI,
lowers confidence when it disagrees, or flags the line for a second look.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils import constants as C

from .models import AIVerdict, EUResult, RioResult

_ORDER = {C.CONF_LOW: 0, C.CONF_MEDIUM: 1, C.CONF_HIGH: 2}


def _cap(conf: str, ceiling: str) -> str:
    return conf if _ORDER[conf] <= _ORDER[ceiling] else ceiling


def _note(ai_text: str, extra: str) -> str:
    ai_text = (ai_text or "").strip()
    return ("%s %s" % (ai_text, extra)).strip() if ai_text else extra


def _objective_text(m: int, a: int) -> str:
    if m and a:
        return "both"
    return "mitigation" if m else "adaptation" if a else "none"


def combine_rio(ai: Optional[AIVerdict], rule: RioResult) -> Dict[str, Any]:
    if ai is None:
        return _rio_row(rule.mitigation, rule.adaptation, C.CONF_LOW, C.DECIDED_RULES,
                        "AI assessment unavailable. Keyword check: " + rule.rationale)
    if ai.administrative:
        conf = C.CONF_HIGH if rule.marker == 0 else C.CONF_MEDIUM
        return _rio_row(0, 0, conf, C.DECIDED_ADMIN, ai.rationale or "Routine administrative cost")

    marker, conf = ai.rio_marker, ai.confidence
    if marker == 0:
        if rule.marker > 0:
            return _rio_row(0, 0, C.CONF_LOW, C.DECIDED_REVIEW,
                            _note(ai.rationale, "The keyword check points to climate relevance: " + rule.rationale))
        decided = C.DECIDED_ADMIN if rule.method.endswith("EXCLUSION") else C.DECIDED_NONE
        return _rio_row(0, 0, conf, decided, ai.rationale or rule.rationale)
    if rule.marker > 0:
        conf = conf if rule.marker == marker else _cap(conf, C.CONF_MEDIUM)
        return _rio_row(ai.rio_mitigation, ai.rio_adaptation, conf, C.DECIDED_CONFIRMED, ai.rationale)
    return _rio_row(ai.rio_mitigation, ai.rio_adaptation, _cap(conf, C.CONF_MEDIUM), C.DECIDED_AI_ONLY, ai.rationale)


def _rio_row(mitigation: int, adaptation: int, conf: str, decided: str, why: str) -> Dict[str, Any]:
    marker = max(mitigation, adaptation)
    return {
        "rio_marker": int(marker), "rio_mitigation": int(mitigation), "rio_adaptation": int(adaptation),
        "climate_tag": C.TAG_GREEN if marker > 0 else C.TAG_NEUTRAL,
        "confidence": conf, "tag_method": decided,
        "environmental_objective": _objective_text(mitigation, adaptation),
        "subcategory": {2: "principal", 1: "significant"}.get(marker),
        "rationale": why,
    }


def combine_eu(ai: Optional[AIVerdict], rule: EUResult) -> Dict[str, Any]:
    if ai is None:
        return _eu_row(rule.tag, [k for k in C.EU_OBJECTIVES if rule.objectives.get(k)], C.CONF_LOW, C.DECIDED_RULES,
                       "AI assessment unavailable. Keyword check: " + rule.rationale)
    if ai.administrative:
        conf = C.CONF_HIGH if rule.tag == C.TAG_NEUTRAL else C.CONF_MEDIUM
        return _eu_row(C.TAG_NEUTRAL, [], conf, C.DECIDED_ADMIN, ai.rationale or "Routine administrative cost")

    conf = ai.confidence
    if ai.brown:
        if rule.tag == C.TAG_GREEN:
            return _eu_row(C.TAG_BROWN, [], C.CONF_LOW, C.DECIDED_REVIEW,
                           _note(ai.rationale, "The keyword check points to a green purpose: " + rule.rationale))
        conf = conf if rule.tag == C.TAG_BROWN else _cap(conf, C.CONF_MEDIUM)
        return _eu_row(C.TAG_BROWN, [], conf, C.DECIDED_BROWN, ai.rationale)

    if ai.eu_objectives:
        objectives = ai.eu_objectives
        if rule.tag == C.TAG_GREEN:
            same = rule.primary == objectives[0]
            return _eu_row(C.TAG_GREEN, objectives, conf if same else _cap(conf, C.CONF_MEDIUM),
                           C.DECIDED_CONFIRMED, ai.rationale)
        if rule.tag == C.TAG_BROWN:
            return _eu_row(C.TAG_GREEN, objectives, C.CONF_LOW, C.DECIDED_REVIEW,
                           _note(ai.rationale, "The keyword check points to a harmful activity: " + rule.rationale))
        return _eu_row(C.TAG_GREEN, objectives, _cap(conf, C.CONF_MEDIUM), C.DECIDED_AI_ONLY, ai.rationale)

    if rule.tag != C.TAG_NEUTRAL:
        return _eu_row(C.TAG_NEUTRAL, [], C.CONF_LOW, C.DECIDED_REVIEW,
                       _note(ai.rationale, "The keyword check points to relevance: " + rule.rationale))
    decided = C.DECIDED_ADMIN if rule.method.endswith("EXCLUSION") else C.DECIDED_NONE
    return _eu_row(C.TAG_NEUTRAL, [], conf, decided, ai.rationale or rule.rationale)


def _eu_row(tag: str, objectives: list, conf: str, decided: str, why: str) -> Dict[str, Any]:
    row: Dict[str, Any] = {C.EU_FLAG_COLUMNS[k]: (k in objectives) for k in C.EU_OBJECTIVES}
    primary = objectives[0] if objectives else "none"
    row.update({
        "eu_primary_objective": primary, "climate_tag": tag, "confidence": conf, "tag_method": decided,
        "environmental_objective": primary, "subcategory": "taxonomy_aligned" if tag == C.TAG_GREEN else None,
        "rationale": why,
    })
    return row
