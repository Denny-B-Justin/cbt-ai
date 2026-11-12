"""What the four provider modules share: the JSON-schema helper, token usage, and turning SDK errors into ai/types.py errors."""

from __future__ import annotations

import base64
import copy
import json
import re
import threading
from typing import Any

from .types import AIError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, AIConfigError, Attachment

TIMEOUT_S = 240.0
TOOL_NAME = "answer"

# A 400 whose message says the request is too big for the model (input side) or asks for too many output tokens.
TOO_LONG = re.compile(r"too (long|large|many tokens)|context (length|window)|input token|prompt token|request entity"
                      r"|payload too|exceeds? (the )?(max|limit|size|context)|file size|maximum (context|input|prompt)",
                      re.I)
OUTPUT_LIMIT = re.compile(r"max_?tokens|maxtokens|max_output_tokens|max_completion_tokens|output tokens"
                          r"|maximum tokens you requested", re.I)

_usage = threading.local()                              # tokens of the last attempt in this thread


class OutputLimitError(AIResponseError):
    """The model refused the requested number of output tokens."""


def b64(a: Attachment) -> str:
    return base64.b64encode(a.data).decode("ascii")


def strict_schema(schema: dict) -> dict:
    """Copy of the schema with additionalProperties=false on every object, as strict structured output requires."""
    schema = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


# ── tokens used ─────────────────────────────────────────────────────────────
def _field(obj: Any, *names: str) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def reset_usage() -> None:
    _usage.tokens = None


def record_usage(usage: Any) -> None:
    """Total tokens from an OpenAI, Anthropic, Gemini or Mistral usage block; nothing if the reply did not say."""
    if usage is None:
        return
    total = _field(usage, "total_tokens", "totalTokens")
    if total is None:
        parts = [_field(usage, "input_tokens", "prompt_tokens", "total_input_tokens"),
                 _field(usage, "output_tokens", "completion_tokens", "total_output_tokens")]
        total = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
    if total is not None:
        _usage.tokens = int(total)


def last_usage() -> int | None:
    return getattr(_usage, "tokens", None)


# ── errors ──────────────────────────────────────────────────────────────────
def short(text: Any) -> str:
    return " ".join(str(text).split())[:300]


def _message(exc: Exception) -> str:
    """The provider's own error text: the JSON body's message when there is one."""
    body = getattr(exc, "body", None)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            pass
    if isinstance(body, dict):
        error = body.get("error", body)
        text = error.get("message") if isinstance(error, dict) else error
        if text:
            return short(text)
    return short(getattr(exc, "message", "") or exc)


def retry_after(headers, message: str) -> float | None:
    try:
        if headers and headers.get("retry-after-ms"):
            return float(headers["retry-after-ms"]) / 1000
        if headers and headers.get("retry-after"):
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        pass
    m = re.search(r"(?:retry|try again) (?:after|in) (\d+(?:\.\d+)?) ?s", message, re.I)
    return float(m.group(1)) if m else None


def status_error(code: int, message: str, headers) -> Exception:
    if code == 413 or (code == 400 and TOO_LONG.search(message)):
        return AIResponseError("The request was too large for the model: " + message, too_long=True)
    if code == 400 and OUTPUT_LIMIT.search(message):
        return OutputLimitError(message)
    if code == 429:
        wait = retry_after(headers, message)
        if re.search(r"insufficient_quota|exceeded your current quota|credit balance|per day|daily|billing", message, re.I) \
                and (wait is None or wait > 300):
            return AIQuotaError("Quota or credit used up: " + message)
        return AIRateLimitError(message, wait)
    if code in (401, 403, 404):
        return AIConfigError("The provider rejected the request ({}): {}".format(code, message))
    if code == 402:
        return AIQuotaError("Payment required: " + message)
    if code in (408, 409, 425) or code >= 500:
        return AIServerError("Provider server error {}: {}".format(code, message))
    return AIResponseError("The provider could not handle the request ({}): {}".format(code, message))


def sdk_error(exc: Exception) -> Exception:
    """Map an exception from the openai, anthropic, google-genai or mistralai SDK to an ai/types.py error.

    openai, anthropic and mistralai errors carry status_code; google-genai's APIError carries code."""
    if isinstance(exc, AIError):
        return exc
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int) and type(exc).__module__.startswith("google.genai"):
        status = getattr(exc, "code", None)
    if isinstance(status, int):
        response = getattr(exc, "response", None) or getattr(exc, "raw_response", None)
        headers = getattr(exc, "headers", None) or getattr(response, "headers", None) or {}
        return status_error(status, _message(exc), headers)
    name = type(exc).__name__
    if any(word in name for word in ("Timeout", "Connect", "Network", "NoResponse", "RemoteProtocol", "ReadError")):
        return AIServerError("Network problem talking to the AI provider: %s" % name)
    return exc
