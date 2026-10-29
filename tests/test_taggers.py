import pytest

from tagging.cofog import division_name, division_of
from tagging.eu_tagger import EUTaxonomyTagger
from tagging.matcher import KeywordMatcher
from tagging.models import LineText
from tagging.rio_tagger import RioMarkerTagger
from utils import constants as C

RIO, EU = RioMarkerTagger(), EUTaxonomyTagger()


def line(title, function_code="", ministry="", description=""):
    return LineText(title, description, ministry, function_code)


@pytest.mark.parametrize("words,text,found", [
    (["solar"], "Solar power", "solar"), (["solar"], "solars", "solar"), (["salary"], "Salaries of staff", "salaries"),
    (["energy efficiency"], "Energy efficiencies", "energy efficiencies"), (["solar"], "isolar", None), (["solar"], "", None),
    (["renewable", "renewable energy"], "renewable energy plan", "renewable energy"),
])
def test_keyword_matcher_matches_whole_words_and_plurals(words, text, found):
    assert KeywordMatcher(words).find(text) == found


@pytest.mark.parametrize("title,marker,mit,ada", [
    ("Solar power plant", 1, 1, 0),
    ("Solar power plant under the NDC", 2, 2, 0),
    ("Flood protection and climate adaptation", 2, 0, 2),
    ("Primary schools", 0, 0, 0),
])
def test_rio_keyword_levels(title, marker, mit, ada):
    r = RIO.tag(line(title))
    assert (r.marker, r.mitigation, r.adaptation) == (marker, mit, ada)


def test_rio_marker_is_the_higher_of_the_two_scores():
    r = RIO.tag(line("Solar power plant and flood protection works"))
    assert r.marker == max(r.mitigation, r.adaptation) and r.marker > 0


def test_administrative_lines_are_excluded():
    r = RIO.tag(line("Salaries of ministry staff"))
    assert (r.marker, r.method) == (0, "RIO_EXCLUSION") and EU.tag(line("Salaries of ministry staff")).tag == C.TAG_NEUTRAL


def test_function_codes_decide_before_keywords():
    assert (division_of("05"), division_of("0500"), division_of("0905"), division_of("")) == ("05", "05", None, None)
    assert division_name("05").lower().startswith("environmental")
    r, e = RIO.tag(line("Anything at all", "05")), EU.tag(line("Anything at all", "05"))
    assert r.marker == 2 and r.method == "RIO_PREDETERMINED" and e.tag == C.TAG_GREEN and e.primary == "mitigation"
    r, e = RIO.tag(line("Solar power plant", "09")), EU.tag(line("Solar power plant", "09"))
    assert r.marker == 0 and e.tag == C.TAG_NEUTRAL, "a neutral function code overrides the words"


@pytest.mark.parametrize("title,tag,objective", [
    ("Solar power plant", C.TAG_GREEN, "mitigation"),
    ("Flood protection and climate adaptation", C.TAG_GREEN, "adaptation"),
    ("Wastewater treatment plant", C.TAG_GREEN, "water"),
    ("National parks and wildlife", C.TAG_GREEN, "biodiversity"),
    ("Coal-fired power station upgrade", C.TAG_BROWN, "none"),
    ("Primary schools", C.TAG_NEUTRAL, "none"),
])
def test_eu_tags(title, tag, objective):
    e = EU.tag(line(title))
    assert (e.tag, e.primary) == (tag, objective)
    assert set(e.objectives) == set(C.EU_OBJECTIVES)
    assert (not any(e.objectives.values())) == (tag != C.TAG_GREEN)
