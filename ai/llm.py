"""The AI provider: calls OpenAI, Anthropic, Google Gemini or Mistral AI directly, with the developer's API keys.

The person using the app picks the model; constants.MODELS lists the ones offered. A provider's models are offered
only when its API key is set (environment variables, see .env.sample):
    OPENAI_API_KEY      OpenAI models
    ANTHROPIC_API_KEY   Anthropic Claude models
    GEMINI_API_KEY      Google Gemini models (GOOGLE_API_KEY is read too)
    MISTRAL_API_KEY     Mistral AI models
Optionally <PROVIDER>_BASE_URL sends a provider's calls to another address (a company proxy, or a local stand-in).

Each provider has its own module (provider_openai, provider_anthropic, provider_gemini, provider_mistral) with the
request and answer handling of its API; what they share is in provider_common.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Sequence
from types import ModuleType
from typing import Any

import constants as C

from . import provider_anthropic, provider_gemini, provider_mistral, provider_openai
from .provider_common import OutputLimitError, last_usage, reset_usage
from .types import AIConfigError, AIResponseError, Attachment

log = logging.getLogger(__name__)

MIN_OUTPUT_TOKENS = 4096
PROVIDER_MODULES: dict[str, ModuleType] = {C.OPENAI: provider_openai, C.ANTHROPIC: provider_anthropic,
                                           C.GEMINI: provider_gemini, C.MISTRAL: provider_mistral}

_lock = threading.Lock()
_clients: dict[tuple, Any] = {}                         # one SDK client per (provider, key, address)
_output_cap: dict[str, int] = {}                        # model -> refused output length, halved
_refused: set[tuple[str, str]] = set()                  # (model, optional setting) the model would not take
_warned: set[str] = set()

__all__ = ["api_key", "available_models", "available_providers", "generate_json", "is_available", "is_configured",
           "last_usage", "model_info"]


# ── settings ────────────────────────────────────────────────────────────────
def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def api_key(provider: str) -> str:
    for name in (C.ENV_API_KEYS[provider],) + C.ENV_API_KEY_ALIASES.get(provider, ()):
        if _env(name):
            return _env(name)
    return ""


def base_url(provider: str) -> str:
    return _env(C.ENV_BASE_URLS[provider])


def model_info(model: str) -> C.Model:
    try:
        return C.MODELS_BY_ID[model]
    except KeyError:
        raise AIConfigError("Unknown model %r; offer it in constants.MODELS first" % model) from None


def available_providers() -> list[str]:
    return [p for p in C.PROVIDERS if api_key(p)]


def is_available(model: str) -> bool:
    return model in C.MODELS_BY_ID and bool(api_key(C.MODELS_BY_ID[model].provider))


def available_models() -> list[str]:
    ready = set(available_providers())
    return [m.id for m in C.MODELS if m.provider in ready]


def is_configured() -> bool:
    """At least one provider has an API key."""
    ok = bool(available_providers())
    if not ok and "settings" not in _warned:
        _warned.add("settings")
        log.warning("No AI provider is set up: set at least one of %s", ", ".join(C.ENV_API_KEYS.values()))
    return ok


def _client_for(provider: str):
    key, url = api_key(provider), base_url(provider)
    with _lock:
        if (provider, key, url) not in _clients:
            _clients[(provider, key, url)] = PROVIDER_MODULES[provider].new_client(key, url)
        return _clients[(provider, key, url)]


def _accepts(model: str, option: str) -> bool:
    return (model, option) not in _refused


# ── the one entry point ─────────────────────────────────────────────────────
def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0, model: str = "") -> Any:
    """One attempt with the chosen model. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    If the model refuses an optional setting or the requested output length, that is adjusted, remembered for
    later calls of the same model, and the request is sent again. temperature is accepted for the interface; the
    current models of every provider run at their own default, except Mistral, which is sent 0.
    """
    provider = model_info(model).provider
    if not api_key(provider):
        raise AIConfigError("%s is not set up: %s is missing" % (model, C.ENV_API_KEYS[provider]))
    module = PROVIDER_MODULES[provider]
    if not module.SUPPORTS_ATTACHMENTS:
        attachments = ()
    reset_usage()
    while True:
        tokens = min(max_output_tokens, _output_cap.get(model, max_output_tokens))
        try:
            return module.send(_client_for(provider), model, system, prompt, schema, attachments, tokens,
                               lambda option: _accepts(model, option))
        except OutputLimitError:
            if tokens <= MIN_OUTPUT_TOKENS:
                raise
            with _lock:
                _output_cap[model] = max(MIN_OUTPUT_TOKENS, tokens // 2)
            log.warning("%s refused %d output tokens; continuing with %d", model, tokens, _output_cap[model])
        except AIResponseError as exc:
            option = next((name for name, pattern in module.OPTIONS.items()
                           if _accepts(model, name) and re.search(pattern, str(exc), re.I)), None)
            if option is None or exc.too_long:
                raise
            _refused.add((model, option))
            log.warning("%s does not accept the %s setting; continuing without it", model, option)
