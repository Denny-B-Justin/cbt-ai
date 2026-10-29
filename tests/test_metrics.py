import numpy as np
import pandas as pd
import pytest

from tagging.metrics import rubric_score, summarize
from utils import constants as C


def rio_frame(amounts, markers, mit=None, ada=None):
    markers = list(markers)
    return pd.DataFrame({"amount": amounts, "rio_marker": markers, "rio_mitigation": mit or markers, "rio_adaptation": ada or [0] * len(markers),
                         "tag_method": ["RIO_MARKER"] * len(markers)})


def eu_frame(amounts, tags, objectives=None):
    n = len(amounts)
    df = pd.DataFrame({"amount": amounts, "climate_tag": tags, "tag_method": ["EU_TAXONOMY"] * n})
    for k in C.EU_OBJECTIVES:
        df[C.EU_FLAG_COLUMNS[k]] = [(objectives or {}).get(i) == k for i in range(n)]
    return df


def test_rio_shares_by_amount():
    s = summarize(C.KIND_RIO, rio_frame([100.0, 50.0, 50.0], [2, 1, 0]))
    assert s["basis"] == "amount" and s["lines"] == 3 and s["tagged_lines"] == 2
    assert s["weighted_share"] == pytest.approx((100 + 0.4 * 50) / 200)
    assert s["principal_share"] == pytest.approx(0.5) and s["significant_share"] == pytest.approx(0.25)
    assert s["mitigation_share"] == pytest.approx(0.75) and s["adaptation_share"] == 0


def test_shares_fall_back_to_lines_when_no_amounts_exist():
    s = summarize(C.KIND_RIO, rio_frame([np.nan] * 4, [2, 1, 0, 0]))
    assert s["basis"] == "lines" and not s["has_amount"] and s["weighted_share"] == pytest.approx((1 + 0.4) / 4)


def test_lines_without_amount_do_not_change_amount_shares():
    a = summarize(C.KIND_RIO, rio_frame([100.0, 100.0], [2, 0]))
    b = summarize(C.KIND_RIO, rio_frame([100.0, 100.0, np.nan], [2, 0, 2]))
    assert a["weighted_share"] == b["weighted_share"] == pytest.approx(0.5)


def test_empty_budget_has_no_shares():
    s = summarize(C.KIND_RIO, rio_frame([0.0, 0.0], [0, 0]))
    assert s["weighted_share"] is None or s["weighted_share"] == 0


def test_eu_shares_and_objectives():
    df = eu_frame([60.0, 20.0, 20.0], [C.TAG_GREEN, C.TAG_BROWN, C.TAG_NEUTRAL], {0: "water"})
    s = summarize(C.KIND_EU, df)
    assert s["green_share"] == pytest.approx(0.6) and s["brown_share"] == pytest.approx(0.2)
    assert s["objective_shares"]["water"] == pytest.approx(0.6) and s["objective_shares"]["adaptation"] == 0
    assert sum(s["by_tag"].values()) == pytest.approx(100.0)


def summaries(weighted=0.2, principal=0.1, significant=0.25, mit=0.2, ada=0.05, brown=0.0, objectives=3):
    rio = {"weighted_share": weighted, "principal_share": principal, "significant_share": significant, "mitigation_share": mit, "adaptation_share": ada}
    eu = {"brown_share": brown, "objective_shares": {k: (0.1 if i < objectives else 0.0) for i, k in enumerate(C.EU_OBJECTIVES)}}
    return rio, eu


def test_rubric_is_bounded_and_ordered():
    assert rubric_score(*summaries(0, 0, 0, 0, 0, 0, 0))["score"] == 0
    top = rubric_score(*summaries(0.5, 0.5, 0, 0.4, 0.3, 0, 6))["score"]
    assert 95 <= top <= 100
    assert rubric_score(*summaries(weighted=0.30))["score"] > rubric_score(*summaries(weighted=0.10))["score"]
    assert rubric_score(*summaries(principal=0.2, significant=0.05))["score"] > rubric_score(*summaries(principal=0.05, significant=0.2))["score"]
    assert rubric_score(*summaries(brown=0.10))["score"] < rubric_score(*summaries(brown=0.0))["score"]
    assert rubric_score(*summaries(objectives=6))["score"] > rubric_score(*summaries(objectives=1))["score"]
    assert rubric_score(*summaries(mit=0.2, ada=0.1))["score"] > rubric_score(*summaries(mit=0.3, ada=0.0))["score"]


def test_rubric_handles_missing_shares():
    rio = {"weighted_share": None, "principal_share": None, "significant_share": None, "mitigation_share": None, "adaptation_share": None}
    assert rubric_score(rio, {"brown_share": None, "objective_shares": {}})["score"] == 0
