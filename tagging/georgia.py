"""Georgian Taxonomy: tagged line rows and the headline numbers behind its charts.

The AI answers the handbook's guiding questions and picks a level for each line (ai/tasks.py). Everything here is
arithmetic: the climate part of a line is its amount times level / 100, and a line with both mitigation and adaptation
(CB) is split 50/50, so nothing is counted twice. Lines that are not climate-tagged have no level.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from utils import constants as C

from .models import GeoVerdict

NOT_GIVEN = "Not given"


def _decided(v: GeoVerdict) -> str:
    if v.floor_only:
        return C.GEO_DECIDED_FLOOR
    if v.mitigation and v.adaptation:
        return C.GEO_DECIDED_BOTH
    if v.mitigation:
        return C.GEO_DECIDED_MIT
    if v.adaptation:
        return C.GEO_DECIDED_ADP
    if v.service_oriented:
        return C.GEO_DECIDED_SERVICE
    if v.q1_ghg_related or v.q3_climate_hazard_related:
        return C.GEO_DECIDED_LINK
    return C.GEO_DECIDED_NONE


def geo_row(v: GeoVerdict | None) -> dict[str, Any]:
    if v is None:
        v = GeoVerdict(confidence=C.CONF_LOW, rationale="This line could not be assessed with the Georgian method.")
        decided = C.GEO_DECIDED_MISSING
    else:
        decided = _decided(v)
    share = v.level / 100.0
    both = v.mitigation and v.adaptation
    return {
        "geo_code": C.GEO_CB if both else C.GEO_CM if v.mitigation else C.GEO_CA if v.adaptation else "",
        "geo_level": int(v.level),
        "geo_mitigation_share": share / 2 if both else share if v.mitigation else 0.0,
        "geo_adaptation_share": share / 2 if both else share if v.adaptation else 0.0,
        "geo_sector": v.sector, "geo_function": v.function,
        "q1_ghg_related": v.q1_ghg_related, "q2_mitigation_measure": v.q2_mitigation_measure,
        "q3_climate_hazard_related": v.q3_climate_hazard_related, "q4_adaptation_measure": v.q4_adaptation_measure,
        "service_oriented": v.service_oriented, "confidence": v.confidence, "tag_method": decided, "rationale": v.rationale,
    }


def georgia_frame(base: pd.DataFrame, verdicts: dict[int, GeoVerdict], line_to_id: list[int]) -> pd.DataFrame:
    """One row per budget line: the base columns, the Georgian tags and the amounts they count as climate."""
    by_id = {i: geo_row(verdicts.get(i)) for i in sorted(set(line_to_id))}
    df = pd.concat([base, pd.DataFrame([by_id[i] for i in line_to_id])], axis=1)
    df["decided_by"] = df["tag_method"].map(C.GEO_DECIDED_LABELS)
    df["mitigation_amount"] = df["amount"] * df["geo_mitigation_share"]
    df["adaptation_amount"] = df["amount"] * df["geo_adaptation_share"]
    df["climate_amount"] = df["mitigation_amount"] + df["adaptation_amount"]
    return df


def _share(num: Any, den: Any) -> Any:
    """num / den, elementwise for series; None (or NaN in a series) where den is not positive."""
    if isinstance(den, pd.Series):
        return (num / den.where(den > 0)).astype(float)
    return float(num) / float(den) if den and den > 0 and np.isfinite(den) else None


def _group(parts: pd.DataFrame, by: pd.Series) -> pd.DataFrame:
    g = parts.groupby(by.fillna(NOT_GIVEN).replace("", NOT_GIVEN), sort=False).sum()
    g["climate_share"] = _share(g["climate"], g["budget"])
    g["mitigation_share"] = _share(g["mitigation"], g["budget"])
    g["adaptation_share"] = _share(g["adaptation"], g["budget"])
    return g


def summarize_georgia(df: pd.DataFrame) -> dict[str, Any]:
    """Shares are by amount when amounts exist, otherwise by number of lines (as for the other two taxonomies)."""
    n = len(df)
    has_amount = bool(df["amount"].notna().any())
    basis = df["amount"].fillna(0.0).astype(float) if has_amount else pd.Series(np.ones(n), index=df.index)
    mit = basis * df["geo_mitigation_share"]
    ada = basis * df["geo_adaptation_share"]
    tagged = df["geo_code"] != ""
    parts = pd.DataFrame({"lines": 1, "tagged_lines": tagged.astype(int), "budget": basis, "mitigation": mit,
                          "adaptation": ada, "climate": mit + ada}, index=df.index)
    total, climate = float(basis.sum()), float(parts["climate"].sum())

    level_parts = parts[tagged]
    by_level = level_parts.groupby(df.loc[tagged, "geo_level"]).sum().reindex(list(C.GEO_LEVELS), fill_value=0.0)
    by_level["lines"] = by_level["lines"].astype(int)
    level_code = (level_parts.assign(level=df["geo_level"], code=df["geo_code"])
                  .groupby(["level", "code"])[["climate", "lines"]].sum()
                  .reindex(pd.MultiIndex.from_product([list(C.GEO_LEVELS), list(C.GEO_CODES)], names=["level", "code"]),
                           fill_value=0))

    def level_split(by: pd.Series) -> pd.DataFrame:
        p = level_parts.assign(key=by[tagged].fillna(NOT_GIVEN).replace("", NOT_GIVEN), level=df.loc[tagged, "geo_level"])
        return p.pivot_table(index="key", columns="level", values="climate", aggfunc="sum", fill_value=0.0) \
                .reindex(columns=list(C.GEO_LEVELS), fill_value=0.0)

    methods = parts.groupby(df["decided_by"]).agg(lines=("lines", "sum"), budget=("budget", "sum"))
    is_floor = df["tag_method"] == C.GEO_DECIDED_FLOOR
    floor = df.loc[is_floor, ["programme", "ministry"]].assign(_budget=basis[is_floor], _climate=parts.loc[is_floor, "climate"])

    return {
        "lines": n, "has_amount": has_amount, "total_amount": float(df["amount"].fillna(0.0).sum()),
        "amount_lines": int(df["amount"].notna().sum()), "basis": "amount" if has_amount else "lines",
        "total": total, "climate": climate, "mitigation": float(mit.sum()), "adaptation": float(ada.sum()),
        "climate_share": _share(climate, total), "mitigation_share": _share(float(mit.sum()), total),
        "adaptation_share": _share(float(ada.sum()), total),
        "mitigation_of_climate": _share(float(mit.sum()), climate), "adaptation_of_climate": _share(float(ada.sum()), climate),
        "tagged_lines": int(tagged.sum()),
        "code_lines": {c: int((df["geo_code"] == c).sum()) for c in C.GEO_CODES},
        "level_of_climate": {lv: _share(float(by_level.at[lv, "climate"]), climate) for lv in C.GEO_LEVELS},
        "by_level": by_level,
        "level_code": level_code,
        "by_sector": _group(parts[tagged], df.loc[tagged, "geo_sector"]).sort_values("climate", ascending=False),
        "by_ministry": _group(parts, df["ministry"]).sort_values("climate", ascending=False),
        "by_function": _group(parts, df["geo_function"]).sort_values("climate", ascending=False),
        "sector_levels": level_split(df["geo_sector"]),
        "ministry_levels": level_split(df["ministry"]),
        "by_method": methods.sort_values("lines", ascending=False),
        "floor_lines": floor.sort_values("_budget", ascending=False).rename(columns={"_budget": "budget", "_climate": "climate"}),
    }
