"""The one door to the AI: paces calls and retries. The provider is ai/mai_llm.py (Posit mAI Gateway).

A provider only has to offer (the tests swap in a stand-in with the same functions):

    is_configured() -> bool
    model_name() -> str
    generate_json(system, prompt, schema, attachments=(), max_output_tokens=..., temperature=0.0) -> parsed JSON
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

from utils import constants as C

from . import mai_llm
from .ratelimit import RateLimiter, call_with_retries
from .types import AIConfigError, Attachment

_limiter: RateLimiter | None = None
_lock = threading.Lock()

# Token estimates, used to keep within the per-minute token budget before the real count is known. They lean high on
# purpose (non-Latin scripts and JSON use more tokens per character); the real count replaces them after each call.
CHARS_PER_TOKEN = 3
ATTACHMENT_BYTES_PER_TOKEN = 60
MIN_OUTPUT_GUESS = 1024


def provider() -> ModuleType:
    return mai_llm


def limiter() -> RateLimiter:
    global _limiter
    with _lock:
        if _limiter is None:
            _limiter = RateLimiter(C.env_int(C.ENV_AI_RPM, C.DEFAULT_AI_RPM),
                                   C.env_int(C.ENV_AI_TPM, C.DEFAULT_AI_TPM, minimum=0))
        return _limiter


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


def ask_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
             max_output_tokens: int = 16384, cancelled: Callable[[], bool] | None = None) -> Any:
    prov = provider()
    if not prov.is_configured():
        raise AIConfigError("The mAI settings are missing (MAI_BASE_URL, MAI_ENDPOINT, or not running on Posit Connect)")
    return call_with_retries(
        lambda: prov.generate_json(system, prompt, schema, attachments=attachments, max_output_tokens=max_output_tokens),
        limiter(), cancelled, tokens=estimate_tokens(system, prompt, schema, attachments, max_output_tokens),
        used=getattr(prov, "last_usage", None))
