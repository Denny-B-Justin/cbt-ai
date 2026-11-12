"""The AI's verdict on one budget line, shared by ai/tasks.py and the tagging code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Verdict:
    """What the AI decided for one budget line with the Georgian method, already made consistent.

    mitigation is Q1 and Q2, adaptation is Q3 and Q4. level is one of 100, 70, 40, 20 for a climate-tagged line
    (mitigation or adaptation) and 0 otherwise.
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
