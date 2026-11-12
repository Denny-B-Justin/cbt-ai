"""Headline numbers of a tagged budget, the grouped tables behind its charts, and the fixed scoring rubric."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from utils import constants as C

NOT_GIVEN = "Not given"
HIGH_LEVELS = (100, 70)              # climate is what the line is about, or most of it
SECTOR_MIN_SHARE = 0.01              # a sector counts towards breadth with at least 1 % of the climate spend


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


def summarize(df: pd.DataFrame) -> dict[str, Any]:
    """Shares are by amount when amounts exist, otherwise by number of lines (the user is told)."""
    n = len(df)
    has_amount = bool(df["amount"].notna().any())
    basis = df["amount"].fillna(0.0).astype(float) if has_amount else pd.Series(np.ones(n), index=df.index)
    mit = basis * df["mitigation_share"]
    ada = basis * df["adaptation_share"]
    tagged = df["cbt_code"] != ""
    parts = pd.DataFrame({"lines": 1, "tagged_lines": tagged.astype(int), "budget": basis, "mitigation": mit,
                          "adaptation": ada, "climate": mit + ada}, index=df.index)
    total, climate = float(basis.sum()), float(parts["climate"].sum())

    level_parts = parts[tagged]
    by_level = level_parts.groupby(df.loc[tagged, "climate_level"]).sum().reindex(list(C.LEVELS), fill_value=0.0)
    by_level["lines"] = by_level["lines"].astype(int)
    level_code = (level_parts.assign(level=df["climate_level"], code=df["cbt_code"])
                  .groupby(["level", "code"])[["climate", "lines"]].sum()
                  .reindex(pd.MultiIndex.from_product([list(C.LEVELS), list(C.CBT_CODES)], names=["level", "code"]),
                           fill_value=0))

    def level_split(by: pd.Series) -> pd.DataFrame:
        p = level_parts.assign(key=by[tagged].fillna(NOT_GIVEN).replace("", NOT_GIVEN), level=df.loc[tagged, "climate_level"])
        return p.pivot_table(index="key", columns="level", values="climate", aggfunc="sum", fill_value=0.0) \
                .reindex(columns=list(C.LEVELS), fill_value=0.0)

    methods = parts.groupby(df["decided_by"]).agg(lines=("lines", "sum"), budget=("budget", "sum"))
    is_floor = df["tag_method"] == C.DECIDED_FLOOR
    floor = df.loc[is_floor, ["programme", "ministry"]].assign(budget=basis[is_floor], climate=parts.loc[is_floor, "climate"])
    by_sector = _group(parts[tagged], df.loc[tagged, "sector"]).sort_values("climate", ascending=False)
    level_of_climate = {lv: _share(float(by_level.at[lv, "climate"]), climate) for lv in C.LEVELS}
    climate_sectors = [k for k, v in by_sector["climate"].items() if k != "None" and climate and v / climate >= SECTOR_MIN_SHARE]

    return {
        "lines": n, "has_amount": has_amount, "total_amount": float(df["amount"].fillna(0.0).sum()),
        "amount_lines": int(df["amount"].notna().sum()), "basis": "amount" if has_amount else "lines",
        "total": total, "climate": climate, "mitigation": float(mit.sum()), "adaptation": float(ada.sum()),
        "climate_share": _share(climate, total), "mitigation_share": _share(float(mit.sum()), total),
        "adaptation_share": _share(float(ada.sum()), total),
        "mitigation_of_climate": _share(float(mit.sum()), climate), "adaptation_of_climate": _share(float(ada.sum()), climate),
        "tagged_lines": int(tagged.sum()),
        "code_lines": {c: int((df["cbt_code"] == c).sum()) for c in C.CBT_CODES},
        "level_of_climate": level_of_climate,
        "high_level_share": _share(sum(float(by_level.at[lv, "climate"]) for lv in HIGH_LEVELS), climate),
        "climate_sectors": climate_sectors,
        "by_level": by_level,
        "level_code": level_code,
        "by_sector": by_sector,
        "by_ministry": _group(parts, df["ministry"]).sort_values("climate", ascending=False),
        "by_function": _group(parts, df["function"]).sort_values("climate", ascending=False),
        "sector_levels": level_split(df["sector"]),
        "ministry_levels": level_split(df["ministry"]),
        "by_method": methods.sort_values("lines", ascending=False),
        "floor_lines": floor.sort_values("budget", ascending=False),
    }


def rubric_score(s: dict[str, Any]) -> dict[str, Any]:
    """A fixed 0-100 rubric. The AI scores the budgets itself; this keeps its answer in a sensible range."""
    climate = s.get("climate_share") or 0.0
    mit, ada = s.get("mitigation_share") or 0.0, s.get("adaptation_share") or 0.0

    size = 60.0 * min(1.0, climate / 0.25)
    directness = 20.0 * (s.get("high_level_share") or 0.0)
    balance = 10.0 if (mit >= 0.01 and ada >= 0.01) else 5.0 if (mit >= 0.01 or ada >= 0.01) else 0.0
    breadth = 10.0 * min(1.0, len(s.get("climate_sectors") or []) / 5)
    score = max(0.0, min(100.0, size + directness + balance + breadth))
    return {"score": round(score), "parts": {"size": round(size, 1), "directness": round(directness, 1),
                                              "balance": round(balance, 1), "breadth": round(breadth, 1)}}
