"""Small data classes shared by the taggers and the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    objectives: dict[str, bool]
    primary: str                     # objective key or "none"
    method: str
    rationale: str


@dataclass
class AIVerdict:
    """What the AI decided for one budget line."""
    rio_mitigation: int = 0
    rio_adaptation: int = 0
    eu_objectives: list[str] = field(default_factory=list)
    brown: bool = False
    administrative: bool = False
    confidence: str = "MEDIUM"
    rationale: str = ""

    @property
    def rio_marker(self) -> int:
        return max(self.rio_mitigation, self.rio_adaptation)


@dataclass
class GeoVerdict:
    """What the AI decided for one budget line with the Georgian method, already made consistent.

    level is one of 100, 70, 40, 20 for a climate-tagged line (mitigation or adaptation) and 0 otherwise.
    """
    q1_ghg_related: bool = False
    q2_mitigation_measure: bool = False
    q3_climate_hazard_related: bool = False
    q4_adaptation_measure: bool = False
    mitigation: bool = False
    adaptation: bool = False
    level: int = 0
    floor_only: bool = False
    service_oriented: bool = False
    sector: str = "None"
    function: str = "Not known"
    confidence: str = "MEDIUM"
    rationale: str = ""
