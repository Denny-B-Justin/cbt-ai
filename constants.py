"""Constants the system needs to work: AI models and their settings, limits, processing stages and the tagging method.

What only the pages need (routing, colours, page text) is in page_constants.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ── AI models (Posit mAI Gateway) ───────────────────────────────────────────
# The family decides the wire format and which mai-endpoint a model is sent to:
#   gpt     OpenAI Responses API through the openai SDK
#   gemini  Gemini Interactions API through the google-genai SDK
#   claude  Bedrock Converse API over plain HTTP
GPT, GEMINI, CLAUDE = "gpt", "gemini", "claude"
FAMILY_LABELS = {GPT: "OpenAI", GEMINI: "Google Gemini", CLAUDE: "Anthropic Claude"}


@dataclass(frozen=True)
class Model:
    id: str          # the model name mAI knows (sent as "model"; for Claude it is part of the endpoint path)
    label: str       # what people see in the model picker
    family: str


# Offered in the model picker, in this order. Every one must be on the gateway's list of allowed models.
MODELS = (
    Model("claude-haiku-5-5", "Claude Haiku 5.5", CLAUDE),
    Model("gpt-6-luna", "ChatGPT 6 Luna", GPT),
    Model("gpt-5.6-luna", "ChatGPT 5.6 Luna", GPT),
    Model("gemini-3.8-flash", "Gemini 3.8 Flash", GEMINI),
    Model("gemini-3.7-flash", "Gemini 3.7 Flash", GEMINI),
    Model("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", GEMINI),
)
MODELS_BY_ID = {m.id: m for m in MODELS}
DEFAULT_MODEL = "claude-haiku-5-5"              # pre-selected when its provider is set up; otherwise the first one that is

# ── Environment variables ───────────────────────────────────────────────────
# mAI: the gateway URL, and one mai-endpoint per model provider. A provider without an endpoint is shown as
# "not set up" in the model picker. URLs are never written in the code. MAI_CLAUDE_ENDPOINT may keep "<model>" in its
# path, as the developer guide writes it: the chosen Claude model is put there.
ENV_MAI_BASE_URL = "MAI_BASE_URL"
ENV_MAI_ENDPOINTS = {GPT: "MAI_OPENAI_ENDPOINT", GEMINI: "MAI_GEMINI_ENDPOINT", CLAUDE: "MAI_CLAUDE_ENDPOINT"}
ENV_CONNECT_GUID = "CONNECT_CONTENT_GUID"     # set by Posit Connect itself, never by hand

ENV_AI_RPM = "AI_REQUESTS_PER_MINUTE"
ENV_AI_TPM = "AI_TOKENS_PER_MINUTE"
ENV_AI_WORKERS = "AI_PARALLEL_CALLS"
ENV_MAX_UPLOAD_MB = "MAX_UPLOAD_MB"
ENV_SESSION_MINUTES = "SESSION_IDLE_MINUTES"
ENV_PORT = "PORT"
ENV_MAX_JOBS = "MAX_RUNNING_ANALYSES"

DEFAULT_AI_RPM = 3500             # the mAI plan's limits per model: 3,500 requests and 35,000 tokens per minute
DEFAULT_AI_TPM = 35000            # 0 switches the token budget off
DEFAULT_AI_WORKERS = 3
DEFAULT_MAX_UPLOAD_MB = 50
DEFAULT_SESSION_MINUTES = 15
DEFAULT_MAX_JOBS = 8


def env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


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

# ── Processing stages (their labels are in page_constants.STAGE_LABELS) ─────
STAGE_UPLOAD = "uploading"
STAGE_READ = "reading"
STAGE_FIND = "finding"
STAGE_TAG = "tagging"
STAGE_CALC = "calculating"
STAGE_SCORE = "scoring"

# ── The method: Climate Budget Tagging in Georgia ──────────────────────────
METHOD_SOURCE = ("Climate Budget Tagging in Georgia: Handbook (Ministry of Environmental Protection and Agriculture of "
                 "Georgia and the World Bank, June 2025)")

# A climate-tagged line is classed in one of four levels; the level is the share of the line counted as climate.
# A line that is not climate-tagged has no level (0 in the data).
LEVELS = (100, 70, 40, 20)
LEVEL_LABELS = {100: "Level 100", 70: "Level 70", 40: "Level 40", 20: "Level 20"}
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
