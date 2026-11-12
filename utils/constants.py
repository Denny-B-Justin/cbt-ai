"""Names, labels, colours, limits and environment-variable names used across the app."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"

# ── Identity ────────────────────────────────────────────────────────────────
APP_NAME = "Climate Budget Tagging Tool"
APP_TAGLINE = ("Upload a budget document and see how much of it is climate spending, tagged with the Georgian climate "
               "budget tagging method")
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
ENV_AI_TPM = "AI_TOKENS_PER_MINUTE"
ENV_AI_WORKERS = "AI_PARALLEL_CALLS"
ENV_MAX_UPLOAD_MB = "MAX_UPLOAD_MB"
ENV_SESSION_MINUTES = "SESSION_IDLE_MINUTES"
ENV_PORT = "PORT"
ENV_MAX_JOBS = "MAX_RUNNING_ANALYSES"

DEFAULT_AI_RPM = 3500             # the mAI plan's limits: 3,500 requests and 35,000 tokens per minute
DEFAULT_AI_TPM = 35000            # 0 switches the token budget off
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

# ── The method: Climate Budget Tagging in Georgia ──────────────────────────
METHOD_NAME = "Georgian Climate Budget Tagging"
METHOD_SOURCE = ("Climate Budget Tagging in Georgia: Handbook (Ministry of Environmental Protection and Agriculture of "
                 "Georgia and the World Bank, June 2025)")

# A climate-tagged line is classed in one of four levels; the level is the share of the line counted as climate.
# A line that is not climate-tagged has no level (0 in the data).
LEVELS = (100, 70, 40, 20)
LEVEL_LABELS = {100: "Level 100", 70: "Level 70", 40: "Level 40", 20: "Level 20"}
LEVEL_MEANING = {
    100: "Climate is what the line is about: the whole line counts.",
    70: "Most of the line is climate measures.",
    40: "Climate measures are a meaningful part, mixed with other works.",
    20: "A weak or indirect link to climate.",
}
FLOOR_LEVEL = 20                              # liveable / habitable wording only: counted as adaptation at this level

CM, CA, CB = "CM", "CA", "CB"                 # CBT codes: mitigation, adaptation, both
CBT_CODES = (CM, CA, CB)
CODE_LABELS = {CM: "CM mitigation", CA: "CA adaptation", CB: "CB both"}
NOT_TAGGED = "Not climate"

SECTORS = ["Energy", "Transport", "Building", "Industry", "Agriculture", "Waste", "Forest", "Water",
           "Coastal resorts", "Tourism", "Health", "Cross-cutting", "None"]
FUNCTIONS = ["General public services", "Defence", "Public order and safety", "Economic affairs",
             "Environmental protection", "Housing and community amenities", "Health",
             "Recreation, culture and religion", "Education", "Social protection", "Not known"]

# How each tag was decided (the "How each tag was decided" charts and the table's "Decided by" column)
DECIDED_BOTH = "BOTH"
DECIDED_MIT = "MITIGATION"
DECIDED_ADP = "ADAPTATION"
DECIDED_FLOOR = "LIVEABLE"
DECIDED_SERVICE = "SERVICE"
DECIDED_LINK = "LINK_ONLY"
DECIDED_NONE = "NONE"
DECIDED_MISSING = "NOT_ASSESSED"
DECIDED_LABELS = {
    DECIDED_BOTH: "Mitigation and adaptation measures (Q2, Q4)",
    DECIDED_MIT: "Mitigation measure (Q1, Q2)",
    DECIDED_ADP: "Adaptation measure (Q3, Q4)",
    DECIDED_FLOOR: "Liveable or habitable wording only (20% rule)",
    DECIDED_SERVICE: "Service cost, not tagged",
    DECIDED_LINK: "GHG or hazard link, no measure",
    DECIDED_NONE: "No climate relevance",
    DECIDED_MISSING: "Not assessed",
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

COMPARE_COLORS = {"A": "#1B6B3A", "B": "#EB6834"}
MITIGATION_COLOR = "#1B8A5A"
ADAPTATION_COLOR = "#2A78D6"
BOTH_COLOR = "#C2410C"
CODE_COLORS = {CM: MITIGATION_COLOR, CA: ADAPTATION_COLOR, CB: BOTH_COLOR}
LEVEL_COLORS = {100: "#4B2A91", 70: "#7451BE", 40: "#A48CD9", 20: "#CDBEEA"}
METHOD_COLOR = "#5E7A6B"

RESULT_TABLE_PAGE_SIZE = 15
