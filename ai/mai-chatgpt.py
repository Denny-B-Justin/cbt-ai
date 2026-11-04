"""mAI provider, GPT models (World Bank gateway, OpenAI Responses API, Azure service-principal sign-in).

Select it with AI_PROVIDER=mai-chatgpt. Offers the same functions as ai/gemini.py.
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
    return mai.is_configured()


def model_name() -> str:
    return mai.model_name(C.DEFAULT_MAI_GPT_MODEL)


def _get_client():
    global _client, _client_key
    from openai import OpenAI

    token = mai.access_token()
    key = (token, mai.base_url(), tuple(sorted(mai.headers().items())))
    with _lock:
        if _client is None or _client_key != key:
            # max_retries=0: ai/ratelimit.py already paces and retries.
            _client = OpenAI(base_url=mai.base_url(), api_key=token, default_headers=mai.headers(),
                             timeout=mai.TIMEOUT_S, max_retries=0)
            _client_key = key
        return _client


def _content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for i, a in enumerate(attachments):
        data = base64.b64encode(a.data).decode("ascii")
        if a.mime_type.startswith("image/"):
            parts.append({"type": "input_image", "image_url": "data:%s;base64,%s" % (a.mime_type, data)})
        else:
            parts.append({"type": "input_file", "filename": "attachment-%d.pdf" % (i + 1),
                          "file_data": "data:%s;base64,%s" % (a.mime_type, data)})
    parts.append({"type": "input_text", "text": prompt})
    return parts


def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    temperature is accepted for interface compatibility; GPT-5 reasoning models do not take it.
    """
    request = dict(
        model=model_name(), instructions=system, max_output_tokens=max_output_tokens,
        input=[{"role": "user", "content": _content(prompt, attachments)}],
        text={"format": {"type": "json_schema", "name": "answer", "schema": mai.strict_schema(schema),
                         "strict": True}})
    response = _call(request)
    log.debug("mAI usage: %s", getattr(response, "usage", None))
    return _parse(response)


def _call(request: dict):
    import openai

    try:
        return _get_client().responses.create(**request)
    except openai.RateLimitError as exc:
        raise _map_rate_limit(exc) from exc
    except (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError) as exc:
        raise AIConfigError("mAI rejected the request (%s): %s" % (exc.status_code, _message(exc))) from exc
    except openai.InternalServerError as exc:
        raise AIServerError("mAI server error %s" % exc.status_code) from exc
    except (openai.APITimeoutError, openai.APIConnectionError) as exc:
        raise AIServerError("Network problem talking to mAI: %s" % type(exc).__name__) from exc
    except openai.APIStatusError as exc:
        if exc.status_code in (408, 409):
            raise AIServerError(_message(exc)) from exc
        raise AIResponseError("mAI could not handle the request (%s): %s" % (exc.status_code, _message(exc))) from exc


def _message(exc) -> str:
    return " ".join(str(getattr(exc, "message", "") or exc).split())[:300]


def _map_rate_limit(exc) -> Exception:
    message = _message(exc)
    if "insufficient_quota" in message or re.search(r"per day|daily", message, re.I):
        return AIQuotaError("Quota used up: " + message)
    retry = None
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        retry = float(headers.get("retry-after")) if headers.get("retry-after") else None
    except ValueError:
        pass
    return AIRateLimitError(message, retry)


def _parse(response) -> Any:
    status = getattr(response, "status", "") or ""
    reason = getattr(getattr(response, "incomplete_details", None), "reason", "") or ""
    if status == "incomplete" and reason == "max_output_tokens":
        raise AIResponseError("The answer was cut off", truncated=True)
    refused = any(getattr(c, "type", "") == "refusal"
                  for item in (getattr(response, "output", None) or [])
                  for c in (getattr(item, "content", None) or []))
    text = (getattr(response, "output_text", None) or "").strip()
    if not text:
        blocked = refused or reason == "content_filter"
        raise AIResponseError("Empty answer (%s)" % (reason or status or "no output"), blocked=blocked)
    return load_json(text)
