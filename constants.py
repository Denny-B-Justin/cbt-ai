"""Constants the system needs to work: AI models and their settings, limits, processing stages and the tagging method.

What only the pages need (routing, colours, page text) is in page_constants.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# ── AI models ───────────────────────────────────────────────────────────────
# The app calls each provider's own API with the developer's API key. A provider is offered only when its key is set,
# so someone with an OpenAI key alone sees only the OpenAI models.
#   openai     Responses API through the openai SDK               JSON: strict json_schema
#   anthropic  Messages API through the anthropic SDK             JSON: structured outputs (output_config)
#   gemini     Interactions API through the google-genai SDK      JSON: response_format with a JSON schema
#   mistral    Chat Completions through the mistralai SDK         JSON: response_format json_schema
OPENAI, ANTHROPIC, GEMINI, MISTRAL = "openai", "anthropic", "gemini", "mistral"
PROVIDERS = (OPENAI, ANTHROPIC, GEMINI, MISTRAL)
PROVIDER_LABELS = {OPENAI: "OpenAI", ANTHROPIC: "Anthropic", GEMINI: "Google Gemini", MISTRAL: "Mistral AI"}


@dataclass(frozen=True)
class Model:
    id: str          # the model name the provider's API knows (sent as "model")
    label: str       # what people see in the model picker
    provider: str


# Offered in the model picker, in this order: per provider its three latest models, then one older model.
# Checked against the providers' model pages in November 2026; update the ids here when a provider retires a model.
MODELS = (
    Model("gpt-6-astra", "GPT-6 Astra", OPENAI),
    Model("gpt-6.1-sol", "GPT-6.1 Sol", OPENAI),
    Model("gpt-6-luna", "GPT-6 Luna", OPENAI),
    Model("gpt-5.6-luna", "GPT-5.6 Luna (older)", OPENAI),
    Model("claude-opus-5-5", "Claude Opus 5.5", ANTHROPIC),
    Model("claude-sonnet-5-5", "Claude Sonnet 5.5", ANTHROPIC),
    Model("claude-haiku-5-5", "Claude Haiku 5.5", ANTHROPIC),
    Model("claude-haiku-4-5", "Claude Haiku 4.5 (older)", ANTHROPIC),
    Model("gemini-4-argon", "Gemini 4 Argon", GEMINI),
    Model("gemini-3.8-flash", "Gemini 3.8 Flash", GEMINI),
    Model("gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", GEMINI),
    Model("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite (older)", GEMINI),
    Model("mistral-large-latest", "Mistral Large (latest)", MISTRAL),
    Model("mistral-medium-latest", "Mistral Medium (latest)", MISTRAL),
    Model("mistral-small-latest", "Mistral Small (latest)", MISTRAL),
    Model("mistral-large-2512", "Mistral Large 3 (older)", MISTRAL),
)
MODELS_BY_ID = {m.id: m for m in MODELS}
# Pre-selected in the picker: the first of these whose provider has a key (a balance of quality and cost for
# documents with thousands of lines); otherwise the first model that can be used.
DEFAULT_MODELS = ("gpt-6.1-sol", "claude-sonnet-5-5", "gemini-3.8-flash", "mistral-medium-latest")

# ── Environment variables ───────────────────────────────────────────────────
# One API key per provider; set only the ones you have. The names are the ones each provider's own SDK documents.
ENV_API_KEYS = {OPENAI: "OPENAI_API_KEY", ANTHROPIC: "ANTHROPIC_API_KEY", GEMINI: "GEMINI_API_KEY",
                MISTRAL: "MISTRAL_API_KEY"}
ENV_API_KEY_ALIASES = {GEMINI: ("GOOGLE_API_KEY",)}       # also read, as the google-genai SDK does
# Optional: another address for a provider's API (a company proxy, or a local stand-in in the tests).
ENV_BASE_URLS = {OPENAI: "OPENAI_BASE_URL", ANTHROPIC: "ANTHROPIC_BASE_URL", GEMINI: "GEMINI_BASE_URL",
                 MISTRAL: "MISTRAL_BASE_URL"}

ENV_AI_RPM = "AI_REQUESTS_PER_MINUTE"
ENV_AI_TPM = "AI_TOKENS_PER_MINUTE"
ENV_AI_WORKERS = "AI_PARALLEL_CALLS"
ENV_MAX_UPLOAD_MB = "MAX_UPLOAD_MB"
ENV_SESSION_MINUTES = "SESSION_IDLE_MINUTES"
ENV_PORT = "PORT"
ENV_MAX_JOBS = "MAX_RUNNING_ANALYSES"

DEFAULT_AI_RPM = 50               # per model; set it to your account's limits (they differ by provider and tier)
DEFAULT_AI_TPM = 0                # tokens per minute per model; 0 switches the token budget off (429s are still handled)
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
