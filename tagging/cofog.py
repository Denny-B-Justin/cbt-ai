"""COFOG function divisions with a pre-determined tag (carried over from the earlier rule-based tool)."""

from __future__ import annotations

import re
from typing import Optional

_NEUTRAL = {
    "01": "General public services",
    "02": "Defence",
    "03": "Public order and safety",
    "07": "Health",
    "09": "Education",
    "10": "Social protection",
}
ENVIRONMENT_DIVISION = "05"

_CODE_RE = re.compile(r"^\s*(\d{2})(?:00)?(?!\d)")


def division_of(function_code: Optional[str]) -> Optional[str]:
    """'05', '0500' and '05 Environmental protection' give '05'; '051' or '0501' give None."""
    if not function_code:
        return None
    m = _CODE_RE.match(str(function_code))
    if not m:
        return None
    div = m.group(1)
    return div if div in _NEUTRAL or div == ENVIRONMENT_DIVISION else None


def division_name(div: str) -> str:
    return "Environmental protection" if div == ENVIRONMENT_DIVISION else _NEUTRAL.get(div, "")
