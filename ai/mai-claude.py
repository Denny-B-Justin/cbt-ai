"""mAI provider, Claude models (World Bank gateway, Anthropic Messages API, Azure service-principal sign-in).

Select it with AI_PROVIDER=mai-claude. Offers the same functions as ai/gemini.py.
"""

from __future__ import annotations

import base64
import logging
import re
import threading
from typing import Any, Optional, Sequence

from utils import constants as C

from . import mai_common as mai
from .schemas import load_json
from .types import AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment

log = logging.getLogger(__name__)

_client = None
_client_key: Optional[tuple] = None
_lock = threading.Lock()


def is_configured() -> bool:
    return mai.is_configured(C.ENV_MAI_CLAUDE_BASE_URL)


def model_name() -> str:
    return mai.model_name(C.DEFAULT_MAI_CLAUDE_MODEL)


def _get_client():
    global _client, _client_key
    import anthropic

    token = mai.access_token()
    # The SDK appends /v1/messages, so drop a trailing /v1 (MAI_BASE_URL usually has one for the OpenAI client).
    url = re.sub(r"/v1/?$", "", mai.base_url(C.ENV_MAI_CLAUDE_BASE_URL))
    key = (token, url, tuple(sorted(mai.headers().items())))
    with _lock:
        if _client is None or _client_key != key:
            # auth_token goes out as "Authorization: Bearer". max_retries=0: ai/ratelimit.py already paces and retries.
            _client = anthropic.Anthropic(base_url=url, auth_token=token, default_headers=mai.headers(),
                                          timeout=mai.TIMEOUT_S, max_retries=0)
            _client_key = key
        return _client


def _content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for a in attachments:
        source = {"type": "base64", "media_type": a.mime_type, "data": base64.standard_b64encode(a.data).decode("ascii")}
        parts.append({"type": "image" if a.mime_type.startswith("image/") else "document", "source": source})
    parts.append({"type": "text", "text": prompt})
    return parts


def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    temperature is accepted for interface compatibility; current Claude models reject sampling settings.
    """
    request = dict(
        model=model_name(), system=system, max_tokens=max_output_tokens,
        messages=[{"role": "user", "content": _content(prompt, attachments)}],
        output_config={"format": {"type": "json_schema", "schema": mai.strict_schema(schema)}})
    response = _call(request)
    log.debug("mAI usage: %s", getattr(response, "usage", None))
    return _parse(response)


def _call(request: dict):
    import anthropic

    try:
        return _get_client().messages.create(**request)
    except anthropic.RateLimitError as exc:
        raise _map_rate_limit(exc) from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
        raise AIConfigError("mAI rejected the request (%s): %s" % (exc.status_code, _message(exc))) from exc
    except anthropic.InternalServerError as exc:
        raise AIServerError("mAI server error %s" % exc.status_code) from exc
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
        raise AIServerError("Network problem talking to mAI: %s" % type(exc).__name__) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code in (408, 409) or exc.status_code >= 500:
            raise AIServerError(_message(exc)) from exc
        raise AIResponseError("mAI could not handle the request (%s): %s" % (exc.status_code, _message(exc))) from exc


def _message(exc) -> str:
    return " ".join(str(getattr(exc, "message", "") or exc).split())[:300]


def _map_rate_limit(exc) -> Exception:
    message = _message(exc)
    if re.search(r"quota|per day|daily", message, re.I):
        return AIQuotaError("Quota used up: " + message)
    retry = None
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        retry = float(headers.get("retry-after")) if headers.get("retry-after") else None
    except ValueError:
        pass
    return AIRateLimitError(message, retry)


def _parse(response) -> Any:
    reason = getattr(response, "stop_reason", "") or ""
    if reason == "max_tokens":
        raise AIResponseError("The answer was cut off", truncated=True)
    text = "".join(b.text for b in (getattr(response, "content", None) or []) if getattr(b, "type", "") == "text").strip()
    if not text:
        raise AIResponseError("Empty answer (%s)" % (reason or "no content"), blocked=reason == "refusal")
    return load_json(text)
