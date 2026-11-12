"""tagging/metrics.py: shares, grouped tables and the fixed scoring rubric."""

import numpy as np
import pandas as pd
import pytest

from tagging.metrics import rubric_score, summarize
from tagging.tags import tag_row
from tagging.models import Verdict
from utils import constants as C


def frame(amounts, verdicts, ministries=None, sectors=None):
    rows = []
    for i, v in enumerate(verdicts):
        if v is not None and sectors:
            v.sector = sectors[i]
        rows.append(tag_row(v))
    df = pd.concat([pd.DataFrame({"amount": amounts, "programme": ["P%d" % i for i in range(len(amounts))],
                                  "ministry": ministries or ["M"] * len(amounts)}), pd.DataFrame(rows)], axis=1)
    df["decided_by"] = df["tag_method"].map(C.DECIDED_LABELS)
    return df


def v(level, mit=False, ada=False):
    return Verdict(mitigation=mit, adaptation=ada, level=level, q1_ghg_related=mit, q2_mitigation_measure=mit,
                   q3_climate_hazard_related=ada, q4_adaptation_measure=ada)


def test_shares_by_amount_follow_the_levels():
    s = summarize(frame([100.0, 100.0, 100.0, 100.0], [v(100, mit=True), v(40, ada=True), v(70, mit=True, ada=True), v(0)]))
    assert s["basis"] == "amount" and s["lines"] == 4 and s["tagged_lines"] == 3
    assert s["climate_share"] == pytest.approx((100 + 40 + 70) / 400)
    assert s["mitigation_share"] == pytest.approx((100 + 35) / 400) and s["adaptation_share"] == pytest.approx((40 + 35) / 400)
    assert s["code_lines"] == {C.CM: 1, C.CA: 1, C.CB: 1}
    assert s["high_level_share"] == pytest.approx(170 / 210)


def test_shares_fall_back_to_lines_when_no_amounts_exist():
    s = summarize(frame([np.nan] * 4, [v(100, mit=True), v(20, ada=True), v(0), v(0)]))
    assert s["basis"] == "lines" and not s["has_amount"] and s["climate_share"] == pytest.approx(1.2 / 4)


def test_lines_without_amount_do_not_change_amount_shares():
    a = summarize(frame([100.0, 100.0], [v(100, mit=True), v(0)]))
    b = summarize(frame([100.0, 100.0, np.nan], [v(100, mit=True), v(0), v(100, mit=True)]))
    assert a["climate_share"] == b["climate_share"] == pytest.approx(0.5)


def test_empty_budget_has_no_shares():
    s = summarize(frame([0.0, 0.0], [v(0), v(0)]))
    assert s["climate_share"] is None or s["climate_share"] == 0


def test_groups_add_up_to_the_whole():
    df = frame([100.0, 50.0, 50.0], [v(100, mit=True), v(40, ada=True), v(0)], ministries=["A", "B", None],
               sectors=["Energy", "Water", "None"])
    s = summarize(df)
    assert s["by_ministry"]["climate"].sum() == pytest.approx(s["climate"]) and "Not given" in s["by_ministry"].index
    assert set(s["by_sector"].index) == {"Energy", "Water"} and s["climate_sectors"] == ["Energy", "Water"]
    assert s["by_level"]["climate"].sum() == pytest.approx(s["climate"])
    assert s["level_code"]["climate"].sum() == pytest.approx(s["climate"])
    assert s["by_method"]["lines"].sum() == 3


def summary(climate=0.2, mit=0.15, ada=0.05, high=0.5, sectors=3):
    return {"climate_share": climate, "mitigation_share": mit, "adaptation_share": ada, "high_level_share": high,
            "climate_sectors": ["S%d" % i for i in range(sectors)]}


def test_rubric_is_bounded_and_ordered():
    assert rubric_score(summary(0, 0, 0, 0, 0))["score"] == 0
    assert rubric_score(summary(0.5, 0.3, 0.2, 1.0, 6))["score"] == 100
    assert rubric_score(summary(climate=0.30))["score"] > rubric_score(summary(climate=0.10))["score"]
    assert rubric_score(summary(high=0.9))["score"] > rubric_score(summary(high=0.1))["score"]
    assert rubric_score(summary(sectors=5))["score"] > rubric_score(summary(sectors=1))["score"]
    assert rubric_score(summary(mit=0.1, ada=0.1))["score"] > rubric_score(summary(mit=0.2, ada=0.0))["score"]


def test_rubric_handles_missing_shares():
    assert rubric_score({"climate_share": None, "mitigation_share": None, "adaptation_share": None,
                         "high_level_share": None, "climate_sectors": []})["score"] == 0
