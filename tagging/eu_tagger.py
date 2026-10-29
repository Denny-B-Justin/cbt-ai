"""EU Taxonomy keyword check: six environmental objectives plus a brown (harmful activity) screen."""

from __future__ import annotations

from typing import Dict

from utils import constants as C

from . import keywords as K
from .cofog import ENVIRONMENT_DIVISION, division_of, division_name
from .matcher import KeywordMatcher
from .models import EUResult, LineText

METHOD_PREDETERMINED = "EU_PREDETERMINED"
METHOD_EXCLUSION = "EU_EXCLUSION"
METHOD_BROWN = "EU_BROWN"
METHOD_OBJECTIVES = "EU_TAXONOMY"
METHOD_NONE = "EU_TAXONOMY_NONE"


def _no_objectives() -> Dict[str, bool]:
    return {k: False for k in C.EU_OBJECTIVES}


class EUTaxonomyTagger:
    def __init__(self) -> None:
        self.objectives = {k: KeywordMatcher(K.EU_KEYWORDS[k]) for k in C.EU_OBJECTIVES}
        self.brown = KeywordMatcher(K.EU_BROWN)
        self.exclusion = KeywordMatcher(K.EXCLUSION)

    def tag(self, line: LineText) -> EUResult:
        div = division_of(line.function_code)
        if div:
            if div == ENVIRONMENT_DIVISION:
                obj = _no_objectives()
                obj["mitigation"] = True
                return EUResult(C.TAG_GREEN, obj, "mitigation", METHOD_PREDETERMINED,
                                "Function code 05 (Environmental protection) is treated as aligned")
            return EUResult(C.TAG_NEUTRAL, _no_objectives(), "none", METHOD_PREDETERMINED,
                            "Function code %s (%s) is outside the EU environmental objectives" % (div, division_name(div)))

        text = line.text
        hit = self.exclusion.find(text)
        if hit:
            return EUResult(C.TAG_NEUTRAL, _no_objectives(), "none", METHOD_EXCLUSION,
                            "Administrative term found: '%s'" % hit)

        brown = self.brown.find(text)
        if brown:
            return EUResult(C.TAG_BROWN, _no_objectives(), "none", METHOD_BROWN, "Harmful-activity term found: '%s'" % brown)

        matches = {k: m.find(text) for k, m in self.objectives.items()}
        active = [k for k in C.EU_OBJECTIVES if matches[k]]
        if not active:
            return EUResult(C.TAG_NEUTRAL, _no_objectives(), "none", METHOD_NONE,
                            "No EU environmental objective detected")
        primary = active[0]
        why = "Serves %s ('%s')" % (C.EU_LABELS[primary].lower(), matches[primary])
        if len(active) > 1:
            why += "; also " + ", ".join(C.EU_LABELS[k].lower() for k in active[1:])
        return EUResult(C.TAG_GREEN, {k: bool(matches[k]) for k in C.EU_OBJECTIVES}, primary, METHOD_OBJECTIVES, why)
