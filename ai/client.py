"""The one door to the AI provider: picks the provider, paces calls and retries.

A provider module (ai/gemini.py, later ai/claude.py) only has to offer:

    is_configured() -> bool
    model_name() -> str
    generate_json(system, prompt, schema, attachments=(), max_output_tokens=..., temperature=0.0) -> parsed JSON
"""

from __future__ import annotations

import importlib
import os
import threading
from types import ModuleType
from typing import Any, Callable, Optional, Sequence

from utils import constants as C

from .ratelimit import RateLimiter, call_with_retries
from .types import AIConfigError, Attachment

_limiter: Optional[RateLimiter] = None
_lock = threading.Lock()


def provider() -> ModuleType:
    name = (os.getenv(C.ENV_AI_PROVIDER) or C.DEFAULT_AI_PROVIDER).strip().lower()
    try:
        return importlib.import_module("ai." + name)
    except ImportError as exc:
        raise AIConfigError("Unknown AI provider '%s'" % name) from exc


def limiter() -> RateLimiter:
    global _limiter
    with _lock:
        if _limiter is None:
            _limiter = RateLimiter(C.env_int(C.ENV_AI_RPM, C.DEFAULT_AI_RPM))
        return _limiter


def is_configured() -> bool:
    try:
        return bool(provider().is_configured())
    except AIConfigError:
        return False


def ask_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
             max_output_tokens: int = 16384, cancelled: Optional[Callable[[], bool]] = None) -> Any:
    prov = provider()
    if not prov.is_configured():
        raise AIConfigError("No API key is configured")
    return call_with_retries(
        lambda: prov.generate_json(system, prompt, schema, attachments=attachments, max_output_tokens=max_output_tokens),
        limiter(), cancelled)
