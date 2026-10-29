"""Headline numbers of a tagged budget, and the fallback scoring rubric used to keep AI scores in range."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from utils import constants as C


def _share(num: float, den: float) -> Optional[float]:
    return float(num) / float(den) if den and den > 0 and np.isfinite(den) else None


def summarize(kind: str, df: pd.DataFrame) -> Dict[str, Any]:
    """Shares are by amount when amounts exist, otherwise by number of lines."""
    n = len(df)
    amt = df["amount"].fillna(0.0).astype(float)
    has_amount = bool(df["amount"].notna().any())
    basis = amt if has_amount else pd.Series(np.ones(n), index=df.index)
    total = float(basis.sum())
    out: Dict[str, Any] = {
        "lines": n, "has_amount": has_amount, "total_amount": float(amt.sum()),
        "amount_lines": int(df["amount"].notna().sum()), "basis": "amount" if has_amount else "lines",
    }
    if kind == C.KIND_RIO:
        w = df["rio_marker"].map(C.RIO_WEIGHTS).astype(float)
        out["weighted_share"] = _share(float((basis * w).sum()), total)
        out["principal_share"] = _share(float(basis[df["rio_marker"] == 2].sum()), total)
        out["significant_share"] = _share(float(basis[df["rio_marker"] == 1].sum()), total)
        out["mitigation_share"] = _share(float(basis[df["rio_mitigation"] > 0].sum()), total)
        out["adaptation_share"] = _share(float(basis[df["rio_adaptation"] > 0].sum()), total)
        out["tagged_lines"] = int((df["rio_marker"] > 0).sum())
    else:
        green, brown = df["climate_tag"] == C.TAG_GREEN, df["climate_tag"] == C.TAG_BROWN
        out["green_share"] = _share(float(basis[green].sum()), total)
        out["brown_share"] = _share(float(basis[brown].sum()), total)
        out["tagged_lines"] = int(green.sum())
        out["by_tag"] = {t: float(basis[df["climate_tag"] == t].sum()) for t in C.TAG_COLORS}
        out["by_objective"] = {k: float(basis[df[C.EU_FLAG_COLUMNS[k]]].sum()) for k in C.EU_OBJECTIVES}
        out["objective_shares"] = {k: _share(v, total) for k, v in out["by_objective"].items()}
    out["by_method"] = df["tag_method"].value_counts().to_dict()
    return out


def rubric_score(rio: Dict[str, Any], eu: Dict[str, Any]) -> Dict[str, Any]:
    """A fixed 0-100 rubric. The AI scores the budgets itself; this keeps its answer in a sensible range."""
    weighted = rio.get("weighted_share") or 0.0
    principal, significant = rio.get("principal_share") or 0.0, rio.get("significant_share") or 0.0
    mit, ada = rio.get("mitigation_share") or 0.0, rio.get("adaptation_share") or 0.0
    objectives = sum(1 for v in (eu.get("objective_shares") or {}).values() if (v or 0) >= 0.01)
    brown = eu.get("brown_share") or 0.0

    size = 60.0 * min(1.0, weighted / 0.25)
    directness = 15.0 * (principal / (principal + significant)) if (principal + significant) > 0 else 0.0
    balance = 10.0 if (mit >= 0.01 and ada >= 0.01) else 5.0 if (mit >= 0.01 or ada >= 0.01) else 0.0
    breadth = 15.0 * objectives / len(C.EU_OBJECTIVES)
    harm = -min(25.0, 25.0 * brown / 0.10)
    score = max(0.0, min(100.0, size + directness + balance + breadth + harm))
    return {"score": round(score), "parts": {"size": round(size, 1), "directness": round(directness, 1),
                                              "balance": round(balance, 1), "breadth": round(breadth, 1),
                                              "harm": round(harm, 1)}}
