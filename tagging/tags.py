"""The tags of every budget line: CBT code, level and the part of the line counted as climate.

The AI answers the handbook's guiding questions and picks a level for each line (ai/tasks.py). Everything here is
arithmetic: the climate part of a line is its amount times level / 100, and a line with both mitigation and adaptation
(CB) is split 50/50, so nothing is counted twice. Lines that are not climate-tagged have no level.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

import constants as C

from .models import Verdict


def _decided(v: Verdict) -> str:
    if v.floor_only:
        return C.DECIDED_FLOOR
    if v.mitigation and v.adaptation:
        return C.DECIDED_BOTH
    if v.mitigation:
        return C.DECIDED_MIT
    if v.adaptation:
        return C.DECIDED_ADP
    if v.service_oriented:
        return C.DECIDED_SERVICE
    if v.q1_ghg_related or v.q3_climate_hazard_related:
        return C.DECIDED_LINK
    return C.DECIDED_NONE


def tag_row(v: Verdict | None) -> dict[str, Any]:
    """The tag columns of one line. No verdict (the AI could not assess it) means not tagged and not assessed."""
    if v is None:
        v = Verdict(confidence=C.CONF_LOW, rationale="This line could not be assessed.")
        decided = C.DECIDED_MISSING
    else:
        decided = _decided(v)
    share = v.level / 100.0
    both = v.mitigation and v.adaptation
    return {
        "cbt_code": C.CB if both else C.CM if v.mitigation else C.CA if v.adaptation else "",
        "climate_level": int(v.level),
        "mitigation_share": share / 2 if both else share if v.mitigation else 0.0,
        "adaptation_share": share / 2 if both else share if v.adaptation else 0.0,
        "sector": v.sector, "function": v.function,
        "q1_ghg_related": v.q1_ghg_related, "q2_mitigation_measure": v.q2_mitigation_measure,
        "q3_climate_hazard_related": v.q3_climate_hazard_related, "q4_adaptation_measure": v.q4_adaptation_measure,
        "service_oriented": v.service_oriented, "confidence": v.confidence, "tag_method": decided, "rationale": v.rationale,
    }


def tagged_frame(base: pd.DataFrame, verdicts: dict[int, Verdict], line_to_id: list[int]) -> pd.DataFrame:
    """One row per budget line: the base columns, the tags and the amounts they count as climate."""
    by_id = {i: tag_row(verdicts.get(i)) for i in sorted(set(line_to_id))}
    df = pd.concat([base, pd.DataFrame([by_id[i] for i in line_to_id])], axis=1)
    df["decided_by"] = df["tag_method"].map(C.DECIDED_LABELS)
    df["mitigation_amount"] = df["amount"] * df["mitigation_share"]
    df["adaptation_amount"] = df["amount"] * df["adaptation_share"]
    df["climate_amount"] = df["mitigation_amount"] + df["adaptation_amount"]
    return df
