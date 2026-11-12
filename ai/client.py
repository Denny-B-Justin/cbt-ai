"""The one door to the AI: picks the model, paces calls and retries. The provider is ai/llm.py (OpenAI, Anthropic,
Google Gemini or Mistral AI, with the developer's API keys).

A provider only has to offer (the tests swap in a stand-in with the same functions):

    is_configured() -> bool                      at least one model can be used
    available_models() -> list[str]              ids from constants.MODELS that can be used
    generate_json(system, prompt, schema, attachments=(), max_output_tokens=..., temperature=0.0, model=...) -> JSON
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

import constants as C

from . import llm
from .ratelimit import RateLimiter, call_with_retries
from .types import AIConfigError, Attachment

_limiters: dict[str, RateLimiter] = {}         # one per model: providers set their limits per model
_lock = threading.Lock()

# Token estimates, used to keep within the per-minute token budget before the real count is known. They lean high on
# purpose (non-Latin scripts and JSON use more tokens per character); the real count replaces them after each call.
CHARS_PER_TOKEN = 3
ATTACHMENT_BYTES_PER_TOKEN = 60
MIN_OUTPUT_GUESS = 1024


def provider() -> ModuleType:
    return llm


def limiter(model: str) -> RateLimiter:
    with _lock:
        if model not in _limiters:
            _limiters[model] = RateLimiter(C.env_int(C.ENV_AI_RPM, C.DEFAULT_AI_RPM),
                                           C.env_int(C.ENV_AI_TPM, C.DEFAULT_AI_TPM, minimum=0))
        return _limiters[model]


def estimate_tokens(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                    max_output_tokens: int = 16384) -> int:
    """A deliberately high guess at the tokens one call uses: what is sent plus a quarter of the output allowance."""
    sent = (len(system) + len(prompt) + len(json.dumps(schema))) // CHARS_PER_TOKEN
    sent += sum(len(a.data) // ATTACHMENT_BYTES_PER_TOKEN for a in attachments)
    return sent + max(MIN_OUTPUT_GUESS, max_output_tokens // 4)


def is_configured() -> bool:
    try:
        return bool(provider().is_configured())
    except AIConfigError:
        return False


def available_models() -> list[str]:
    try:
        return list(provider().available_models())
    except AIConfigError:
        return []


def default_model() -> str:
    """The model pre-selected in the picker: the first of DEFAULT_MODELS that can be used, else the first that can."""
    ready = available_models()
    return next((m for m in C.DEFAULT_MODELS if m in ready), ready[0] if ready else C.DEFAULT_MODELS[0])


def model_label(model: str | None) -> str:
    m = C.MODELS_BY_ID.get(model or "")
    return m.label if m else (model or "")


def ask_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
             max_output_tokens: int = 16384, cancelled: Callable[[], bool] | None = None, model: str | None = None) -> Any:
    """One answer from the chosen model (the default model when none is given), paced and retried."""
    prov = provider()
    model = model or default_model()
    if model not in C.MODELS_BY_ID:
        raise AIConfigError("Unknown model %r" % model)
    if model not in available_models():
        raise AIConfigError("%s is not set up: %s is missing" % (model, C.ENV_API_KEYS[C.MODELS_BY_ID[model].provider]))
    return call_with_retries(
        lambda: prov.generate_json(system, prompt, schema, attachments=attachments, max_output_tokens=max_output_tokens,
                                   model=model),
        limiter(model), cancelled, tokens=estimate_tokens(system, prompt, schema, attachments, max_output_tokens),
        used=getattr(prov, "last_usage", None))
