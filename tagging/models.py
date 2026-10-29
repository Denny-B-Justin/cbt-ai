"""Small data classes shared by the taggers and the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class LineText:
    """The text of one budget line that the keyword taggers read."""
    title: str = ""
    description: str = ""
    ministry: str = ""
    function_code: str = ""

    @property
    def text(self) -> str:
        return " ".join(p for p in (self.title, self.description, self.ministry) if p).lower()


@dataclass
class RioResult:
    marker: int                      # 0 / 1 / 2 (higher of mitigation and adaptation)
    mitigation: int
    adaptation: int
    method: str
    rationale: str


@dataclass
class EUResult:
    tag: str                         # GREEN | BROWN | NEUTRAL
    objectives: Dict[str, bool]
    primary: str                     # objective key or "none"
    method: str
    rationale: str


@dataclass
class AIVerdict:
    """What the AI decided for one budget line."""
    rio_mitigation: int = 0
    rio_adaptation: int = 0
    eu_objectives: List[str] = field(default_factory=list)
    brown: bool = False
    administrative: bool = False
    confidence: str = "MEDIUM"
    rationale: str = ""

    @property
    def rio_marker(self) -> int:
        return max(self.rio_mitigation, self.rio_adaptation)
