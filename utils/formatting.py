"""Number and text formatting helpers."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def is_missing(v: Any) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def fmt_int(v: Any) -> str:
    return "-" if is_missing(v) else "{:,.0f}".format(float(v))


def fmt_pct(v: Any, digits: int = 1) -> str:
    return "-" if is_missing(v) else ("{:.%df}%%" % digits).format(float(v) * 100.0)


def fmt_amount(v: Any, unit: Optional[str] = None) -> str:
    """12 345 678 -> '12.3M'; an optional unit text is appended."""
    if is_missing(v):
        return "-"
    x = float(v)
    a = abs(x)
    body = "{:,.0f}".format(x)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            body = "{:.1f}{}".format(x / div, suffix)
            break
    return "%s %s" % (body, unit) if unit else body


def plural(n: int, one: str, many: Optional[str] = None) -> str:
    return "%s %s" % (fmt_int(n), one if int(n) == 1 else (many or one + "s"))


def short_text(text: Any, limit: int = 60) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def fmt_money(v: Any, currency: str = "", unit: str = "units") -> str:
    """Amounts as written in a document: '12,345 million GEL' for scaled documents, '12.3M GEL' otherwise."""
    if is_missing(v):
        return "-"
    word = {"thousands": "thousand", "millions": "million", "billions": "billion"}.get(unit)
    if word:
        x = float(v)
        body = "{:,.0f}".format(x) if abs(x) >= 1000 else "{:,.1f}".format(x)
        return " ".join(p for p in (body, word, currency) if p)
    return fmt_amount(v, currency or None)
