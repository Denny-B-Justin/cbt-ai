"""Whole-word, case-insensitive keyword matching (plurals such as 'renewables' also match)."""

from __future__ import annotations

import re
from typing import Iterable, Optional


class KeywordMatcher:
    def __init__(self, words: Iterable[str]):
        self.words = list(dict.fromkeys(w.lower() for w in words))
        forms = list(self.words) + [w[:-1] + "ies" for w in self.words if re.search(r"[^aeiou]y$", w)]   # 'salary' -> 'salaries'
        # longest phrases first so 'renewable energy' wins over 'renewable'
        parts = [re.escape(w) for w in sorted(dict.fromkeys(forms), key=len, reverse=True)]
        self._re = re.compile(r"\b(" + "|".join(parts) + r")(?:s|es)?\b") if parts else None

    def find(self, text: str) -> Optional[str]:
        if not self._re or not text:
            return None
        m = self._re.search(text.lower())
        return m.group(1) if m else None

    def __bool__(self) -> bool:
        return bool(self.words)
