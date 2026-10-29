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
ENV_AI_PROVIDER = "AI_PROVIDER"
ENV_GEMINI_KEY = "GEMINI_API_KEY"
ENV_GEMINI_MODEL = "GEMINI_MODEL"
ENV_AI_RPM = "AI_REQUESTS_PER_MINUTE"
ENV_AI_WORKERS = "AI_PARALLEL_CALLS"
ENV_MAX_UPLOAD_MB = "MAX_UPLOAD_MB"
ENV_SESSION_MINUTES = "SESSION_IDLE_MINUTES"
ENV_PORT = "PORT"
ENV_MAX_JOBS = "MAX_RUNNING_ANALYSES"

DEFAULT_AI_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
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
ALLOWED_SUFFIXES = (".pdf", ".docx")
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
KINDS = (KIND_RIO, KIND_EU)
KIND_LABELS = {KIND_RIO: "Rio Markers", KIND_EU: "EU Taxonomy"}

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

RESULT_TABLE_PAGE_SIZE = 15
