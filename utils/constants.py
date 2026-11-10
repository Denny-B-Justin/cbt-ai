"""Names, labels, colours, limits and environment-variable names used across the app."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"

# ── Identity ────────────────────────────────────────────────────────────────
APP_NAME = "Climate Budget Tagging Tool"
APP_TAGLINE = "Upload a budget document and see how much of it supports climate goals"
METHODOLOGY_VERSION = "2.0"

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

# ── Environment variables ───────────────────────────────────────────────────
ENV_MAI_BASE_URL = "MAI_BASE_URL"
ENV_MAI_ENDPOINT = "MAI_ENDPOINT"
ENV_MAI_MODEL = "MAI_MODEL"
ENV_CONNECT_GUID = "CONNECT_CONTENT_GUID"     # set by Posit Connect itself, never by hand
ENV_AI_RPM = "AI_REQUESTS_PER_MINUTE"
ENV_AI_WORKERS = "AI_PARALLEL_CALLS"
ENV_MAX_UPLOAD_MB = "MAX_UPLOAD_MB"
ENV_SESSION_MINUTES = "SESSION_IDLE_MINUTES"
ENV_PORT = "PORT"
ENV_MAX_JOBS = "MAX_RUNNING_ANALYSES"

DEFAULT_AI_RPM = 8
DEFAULT_AI_WORKERS = 3
DEFAULT_MAX_UPLOAD_MB = 50
DEFAULT_SESSION_MINUTES = 15
DEFAULT_MAX_JOBS = 8
HEARTBEAT_SECONDS = 20


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


UPLOAD_REJECT_FACTOR = 3        # files above this many times the limit are not even sent to the server


def max_upload_bytes() -> int:
    return env_int(ENV_MAX_UPLOAD_MB, DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024


# ── Documents ───────────────────────────────────────────────────────────────
EXCEL_SUFFIXES = (".xlsx", ".xlsm")
ALLOWED_SUFFIXES = (".pdf", ".docx") + EXCEL_SUFFIXES
CHUNK_CHARS = 28000              # text sent to the AI per reading call
MAX_PAGES = 600
TABLE_PAGE_NUMBERS = 25          # a page with this many amounts is treated as a table page
SCAN_PAGE_CHARS = 120            # a page with less text than this looks like a scan
TAG_BATCH_SIZE = 60              # budget lines tagged per AI call
MAX_UNIQUE_LINES = 2500          # safety limit on lines tagged in one document

# ── Processing stages (shown on the loading bar) ────────────────────────────
STAGE_UPLOAD = "uploading"
STAGE_READ = "reading"
STAGE_FIND = "finding"
STAGE_TAG = "tagging"
STAGE_CALC = "calculating"
STAGE_SCORE = "scoring"
STAGE_LABELS = {
    STAGE_UPLOAD: "Uploading your document",
    STAGE_READ: "Reading the document",
    STAGE_FIND: "Finding the budget lines",
    STAGE_TAG: "Tagging each budget line",
    STAGE_CALC: "Calculating the results",
    STAGE_SCORE: "Scoring the budgets",
}

# ── Tagging vocabulary ──────────────────────────────────────────────────────
RIO_WEIGHTS = {0: 0.0, 1: 0.40, 2: 1.0}      # share of a line counted as climate spending
RIO_LABELS = {0: "Not targeted", 1: "Significant", 2: "Principal"}

EU_OBJECTIVES = ["mitigation", "adaptation", "water", "circular_economy", "pollution", "biodiversity"]
EU_FLAG_COLUMNS = {k: "eu_" + k for k in EU_OBJECTIVES}
EU_LABELS = {
    "mitigation": "Climate change mitigation",
    "adaptation": "Climate change adaptation",
    "water": "Water and marine resources",
    "circular_economy": "Circular economy",
    "pollution": "Pollution prevention",
    "biodiversity": "Biodiversity and ecosystems",
}

KIND_RIO = "rio"
KIND_EU = "eu"
KIND_GEO = "georgia"
KINDS = (KIND_RIO, KIND_EU, KIND_GEO)
KIND_LABELS = {KIND_RIO: "Rio Markers", KIND_EU: "EU Taxonomy", KIND_GEO: "Georgian Taxonomy"}

# Georgian Taxonomy (Climate Budget Tagging in Georgia, Handbook, MEPA and World Bank, June 2025).
# A climate-tagged line is classed in one of four levels; the level is the share of the line counted as climate.
# A line that is not climate-tagged has no level (0 in the data).
GEO_LEVELS = (100, 70, 40, 20)
GEO_LEVEL_LABELS = {100: "Level 100", 70: "Level 70", 40: "Level 40", 20: "Level 20"}
GEO_LEVEL_MEANING = {
    100: "Climate is what the line is about: the whole line counts.",
    70: "Most of the line is climate measures.",
    40: "Climate measures are a meaningful part, mixed with other works.",
    20: "A weak or indirect link to climate.",
}
GEO_FLOOR_LEVEL = 20                          # liveable / habitable wording only: counted as adaptation at this level
GEO_CM, GEO_CA, GEO_CB = "CM", "CA", "CB"
GEO_CODES = (GEO_CM, GEO_CA, GEO_CB)
GEO_CODE_LABELS = {GEO_CM: "CM mitigation", GEO_CA: "CA adaptation", GEO_CB: "CB both"}
GEO_NOT_TAGGED = "Not climate"
GEO_SECTORS = ["Energy", "Transport", "Building", "Industry", "Agriculture", "Waste", "Forest", "Water",
               "Coastal resorts", "Tourism", "Health", "Cross-cutting", "None"]
GEO_FUNCTIONS = ["General public services", "Defence", "Public order and safety", "Economic affairs",
                 "Environmental protection", "Housing and community amenities", "Health",
                 "Recreation, culture and religion", "Education", "Social protection", "Not known"]

GEO_DECIDED_BOTH = "GEO_BOTH"
GEO_DECIDED_MIT = "GEO_MIT"
GEO_DECIDED_ADP = "GEO_ADP"
GEO_DECIDED_FLOOR = "GEO_FLOOR"
GEO_DECIDED_SERVICE = "GEO_SERVICE"
GEO_DECIDED_LINK = "GEO_LINK"
GEO_DECIDED_NONE = "GEO_NONE"
GEO_DECIDED_MISSING = "GEO_MISSING"
GEO_DECIDED_LABELS = {
    GEO_DECIDED_BOTH: "Mitigation and adaptation measures (Q2, Q4)",
    GEO_DECIDED_MIT: "Mitigation measure (Q1, Q2)",
    GEO_DECIDED_ADP: "Adaptation measure (Q3, Q4)",
    GEO_DECIDED_FLOOR: "Liveable or habitable wording only (20% rule)",
    GEO_DECIDED_SERVICE: "Service cost, not tagged",
    GEO_DECIDED_LINK: "GHG or hazard link, no measure",
    GEO_DECIDED_NONE: "No climate relevance",
    GEO_DECIDED_MISSING: "Not assessed",
}

TAG_GREEN, TAG_BROWN, TAG_NEUTRAL = "GREEN", "BROWN", "NEUTRAL"
TAG_LABELS = {TAG_GREEN: "Green", TAG_BROWN: "Brown", TAG_NEUTRAL: "Neutral"}

# How a classification was decided (the "What decided each classification" chart)
DECIDED_CONFIRMED = "CONFIRMED"
DECIDED_AI_ONLY = "AI_ONLY"
DECIDED_NONE = "NOT_RELEVANT"
DECIDED_ADMIN = "ADMIN"
DECIDED_BROWN = "BROWN"
DECIDED_REVIEW = "REVIEW"
DECIDED_RULES = "RULES_ONLY"
DECIDED_LABELS = {
    DECIDED_CONFIRMED: "Confirmed by both checks",
    DECIDED_AI_ONLY: "AI judgement only",
    DECIDED_NONE: "No climate relevance found",
    DECIDED_ADMIN: "Routine administration",
    DECIDED_BROWN: "Fossil or polluting activity",
    DECIDED_REVIEW: "Needs a second look",
    DECIDED_RULES: "Keyword check only",
}

CONF_HIGH, CONF_MEDIUM, CONF_LOW = "HIGH", "MEDIUM", "LOW"

# ── Design tokens (CSS variables live in assets/style.css) ──────────────────
NAVY = "#0F3B2A"
INDIGO = "#1B6B3A"
TEAL = "#8ED1A3"
ORANGE = "#F2B33D"
INK = "#14291F"
INK_SOFT = "#42564C"
INK_MUTE = "#637569"
LINE = "#D3DDD6"
NO_DATA_COLOR = "#C5CCC6"
FONT_STACK = "'Fira Sans', 'Segoe UI', Arial, sans-serif"

GREEN_COLOR = "#2E9E5B"
BROWN_COLOR = "#8B4513"
TAG_COLORS = {TAG_GREEN: GREEN_COLOR, TAG_BROWN: BROWN_COLOR, TAG_NEUTRAL: NO_DATA_COLOR}
RIO_COLORS = {0: NO_DATA_COLOR, 1: "#4FAE6F", 2: "#1B6B3A"}
COMPARE_COLORS = {"A": "#1B6B3A", "B": "#EB6834"}
MITIGATION_COLOR = "#1B8A5A"
ADAPTATION_COLOR = "#2A78D6"
BOTH_COLOR = "#C2410C"
GEO_CODE_COLORS = {GEO_CM: MITIGATION_COLOR, GEO_CA: ADAPTATION_COLOR, GEO_CB: BOTH_COLOR}
GEO_LEVEL_COLORS = {100: "#4B2A91", 70: "#7451BE", 40: "#A48CD9", 20: "#CDBEEA"}
METHOD_COLOR = "#5E7A6B"

RESULT_TABLE_PAGE_SIZE = 15
