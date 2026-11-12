"""Constants only the pages need: names, routing, page text, the loading bar, colours. System constants are in constants.py."""

from __future__ import annotations

import constants as C

# ── Identity ────────────────────────────────────────────────────────────────
APP_NAME = "Climate Budget Tagging Tool"
APP_TAGLINE = ("Upload a budget document and see how much of it is climate spending, tagged with the Georgian climate "
               "budget tagging method")

# ── Pages (query-string routing keeps the app working behind a sub-path) ────
PAGE_HOME = "home"
PAGE_EVALUATE = "evaluate"
PAGE_COMPARE = "compare"
PAGE_METHODOLOGY = "methodology"
PAGES = [
    (PAGE_HOME, "Home", "?page=home"),
    (PAGE_EVALUATE, "Evaluate Budget", "?page=evaluate"),
    (PAGE_COMPARE, "Compare Budget", "?page=compare"),
    (PAGE_METHODOLOGY, "Methodology", "?page=methodology"),
]
DEFAULT_PAGE = PAGE_HOME

UPLOAD_REJECT_FACTOR = 3        # files above this many times the limit are not even sent to the server
RESULT_TABLE_PAGE_SIZE = 15

# ── Model picker ────────────────────────────────────────────────────────────
MODEL_PICKER_LABEL = "AI model"
MODEL_PICKER_HINT = "The AI assistant that reads and tags the budget."
MODEL_NOT_SET_UP = "not set up"

# ── Loading bar ─────────────────────────────────────────────────────────────
STAGE_LABELS = {
    C.STAGE_UPLOAD: "Uploading your document",
    C.STAGE_READ: "Reading the document",
    C.STAGE_FIND: "Finding the budget lines",
    C.STAGE_TAG: "Tagging each budget line",
    C.STAGE_CALC: "Calculating the results",
    C.STAGE_SCORE: "Scoring the budgets",
}

# ── Methodology page ────────────────────────────────────────────────────────
LEVEL_MEANING = {
    100: "Climate is what the line is about: the whole line counts.",
    70: "Most of the line is climate measures.",
    40: "Climate measures are a meaningful part, mixed with other works.",
    20: "A weak or indirect link to climate.",
}

# ── Design tokens (CSS variables live in assets/style.css) ──────────────────
INK = "#14291F"
INK_SOFT = "#42564C"
INK_MUTE = "#637569"
LINE = "#D3DDD6"
NO_DATA_COLOR = "#C5CCC6"
FONT_STACK = "'Fira Sans', 'Segoe UI', Arial, sans-serif"

COMPARE_COLORS = {"A": "#1B6B3A", "B": "#EB6834"}
MITIGATION_COLOR = "#1B8A5A"
ADAPTATION_COLOR = "#2A78D6"
BOTH_COLOR = "#C2410C"
CODE_COLORS = {C.CM: MITIGATION_COLOR, C.CA: ADAPTATION_COLOR, C.CB: BOTH_COLOR}
LEVEL_COLORS = {100: "#4B2A91", 70: "#7451BE", 40: "#A48CD9", 20: "#CDBEEA"}
METHOD_COLOR = "#5E7A6B"
