"""Gemini provider (Google AI Studio API key). To use another model family, add ai/claude.py with the same functions."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any, Optional, Sequence

from utils import constants as C

from .schemas import load_json
from .types import AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment

log = logging.getLogger(__name__)

ENV_BASE_URL = "GEMINI_BASE_URL"
ENV_THINKING = "GEMINI_THINKING_LEVEL"
TIMEOUT_MS = 180_000

_client = None
_client_key: Optional[str] = None
_lock = threading.Lock()
_thinking_ok = True


def _api_key() -> str:
    return (os.getenv(C.ENV_GEMINI_KEY) or os.getenv("GOOGLE_API_KEY") or "").strip()


def is_configured() -> bool:
    return bool(_api_key())


def model_name() -> str:
    return (os.getenv(C.ENV_GEMINI_MODEL) or C.DEFAULT_GEMINI_MODEL).strip()


def _get_client():
    global _client, _client_key
    from google import genai
    from google.genai import types

    key = _api_key()
    with _lock:
        if _client is None or _client_key != key:
            opts = types.HttpOptions(timeout=TIMEOUT_MS, base_url=os.getenv(ENV_BASE_URL) or None)
            _client = genai.Client(api_key=key, http_options=opts)
            _client_key = key
        return _client


def _thinking_config(types):
    level = (os.getenv(ENV_THINKING) or "low").strip().lower()
    if not _thinking_ok or level in ("", "off", "none", "default"):
        return None
    mapping = {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
    if level not in mapping:
        return None
    return types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, mapping[level]))


def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py."""
    global _thinking_ok
    from google.genai import types

    parts = [types.Part.from_bytes(data=a.data, mime_type=a.mime_type) for a in attachments]
    parts.append(types.Part.from_text(text=prompt))
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperature, max_output_tokens=max_output_tokens,
        response_mime_type="application/json", response_json_schema=schema,
        thinking_config=_thinking_config(types))
    try:
        response = _call(parts, config)
    except AIResponseError as exc:
        if "thinking" in str(exc).lower() and config.thinking_config is not None:
            log.warning("Model does not accept the thinking setting; continuing without it")
            _thinking_ok = False
            config.thinking_config = None
            response = _call(parts, config)
        else:
            raise
    return _parse(response)


def _call(parts, config):
    from google.genai import errors
    import httpx

    try:
        return _get_client().models.generate_content(model=model_name(), contents=parts, config=config)
    except errors.ClientError as exc:
        raise _map_client_error(exc) from exc
    except errors.ServerError as exc:
        raise AIServerError("Gemini server error %s" % getattr(exc, "code", "")) from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise AIServerError("Network problem talking to Gemini: %s" % type(exc).__name__) from exc


def _retry_seconds(details: Any) -> Optional[float]:
    text = json.dumps(details, default=str) if details is not None else ""
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', text) or re.search(r"retry in ([\d.]+)\s*s", text, re.I)
    return float(m.group(1)) if m else None


def _map_client_error(exc) -> Exception:
    code = getattr(exc, "code", 0)
    message = " ".join(str(getattr(exc, "message", "") or exc).split())[:300]
    details = getattr(exc, "details", None)
    if code == 429:
        blob = json.dumps(details, default=str) if details is not None else ""
        if "PerDay" in blob or "per day" in blob.lower():
            return AIQuotaError("Daily quota used up: " + message)
        return AIRateLimitError(message, _retry_seconds(details))
    if code in (401, 403, 404) or (code == 400 and re.search(r"api key|API_KEY|not found|permission", message, re.I)):
        return AIConfigError("Gemini rejected the request (%s): %s" % (code, message))
    if code in (408, 409):
        return AIServerError(message)
    return AIResponseError("Gemini could not handle the request (%s): %s" % (code, message))


def _parse(response) -> Any:
    candidates = getattr(response, "candidates", None) or []
    reason = ""
    if candidates:
        fr = getattr(candidates[0], "finish_reason", None)
        reason = str(getattr(fr, "name", fr) or "")
    text = (getattr(response, "text", None) or "").strip() if candidates else ""
    if reason == "MAX_TOKENS":
        raise AIResponseError("The answer was cut off", truncated=True)
    if not text:
        blocked = reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION") or not candidates
        raise AIResponseError("Empty answer (%s)" % (reason or "no candidates"), blocked=blocked)
    return load_json(text)
