"""Rio Markers keyword check: 0 not targeted, 1 significant, 2 principal (mitigation and adaptation)."""

from __future__ import annotations

from . import keywords as K
from .cofog import ENVIRONMENT_DIVISION, division_of, division_name
from .matcher import KeywordMatcher
from .models import LineText, RioResult

METHOD_PREDETERMINED = "RIO_PREDETERMINED"
METHOD_EXCLUSION = "RIO_EXCLUSION"
METHOD_KEYWORDS = "RIO_MARKER"


class RioMarkerTagger:
    def __init__(self) -> None:
        self.mitigation = KeywordMatcher(K.RIO_MITIGATION)
        self.adaptation = KeywordMatcher(K.RIO_ADAPTATION)
        self.explicit = KeywordMatcher(K.RIO_EXPLICIT)
        self.exclusion = KeywordMatcher(K.EXCLUSION)

    def tag(self, line: LineText) -> RioResult:
        div = division_of(line.function_code)
        if div:
            green = div == ENVIRONMENT_DIVISION
            m = 2 if green else 0
            why = ("Function code %s (%s) is treated as a principal climate objective" % (div, division_name(div))
                   if green else "Function code %s (%s) is typically climate-neutral" % (div, division_name(div)))
            return RioResult(m, m, 0, METHOD_PREDETERMINED, why)

        text = line.text
        hit = self.exclusion.find(text)
        if hit:
            return RioResult(0, 0, 0, METHOD_EXCLUSION, "Administrative term found: '%s'" % hit)

        mit, ada, exp = self.mitigation.find(text), self.adaptation.find(text), self.explicit.find(text)
        mitigation = 2 if (exp and mit) else 1 if mit else 0
        adaptation = 2 if (exp and ada) else 1 if ada else 0
        marker = max(mitigation, adaptation)
        if marker == 0:
            return RioResult(0, 0, 0, METHOD_KEYWORDS, "No climate relevance detected")

        level = "Principal" if marker == 2 else "Significant"
        if mit and ada:
            what = "mitigation and adaptation"
        elif mit:
            what = "mitigation ('%s')" % mit
        else:
            what = "adaptation ('%s')" % ada
        return RioResult(marker, mitigation, adaptation, METHOD_KEYWORDS, "%s %s objective" % (level, what))
