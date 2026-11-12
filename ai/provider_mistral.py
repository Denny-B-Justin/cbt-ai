"""Mistral AI: Chat Completions through the mistralai SDK, with JSON-schema output.

    from mistralai.client import Mistral, models
    client.chat.complete(model=..., messages=[...], max_tokens=..., temperature=0,
                         response_format=models.ResponseFormat(type="json_schema",
                             json_schema=models.JSONSchema(name=..., schema_definition=..., strict=True)))

The SDK sends schema_definition as "schema". Mistral's chat models take documents only as public URLs, so attached
PDF pages are not sent: the extracted text of the same pages is (it always is, for every provider).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .provider_common import TIMEOUT_S, TOOL_NAME, record_usage, sdk_error, strict_schema
from .schemas import load_json
from .types import AIResponseError, Attachment

OPTIONS: dict[str, str] = {}
SUPPORTS_ATTACHMENTS = False


def new_client(api_key: str, base_url: str = ""):
    from mistralai.client import Mistral

    # The SDK retries only when given a RetryConfig; none is given, because ai/ratelimit.py already paces and retries.
    return Mistral(api_key=api_key, server_url=base_url or None, timeout_ms=int(TIMEOUT_S * 1000))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(getattr(chunk, "text", "") or "" for chunk in content or [])


def send(client, model: str, system: str, prompt: str, schema: dict, attachments: Sequence[Attachment], tokens: int,
         accepts: Callable[[str], bool]) -> Any:
    from mistralai.client import models

    response_format = models.ResponseFormat(type="json_schema", json_schema=models.JSONSchema(
        name=TOOL_NAME, schema_definition=strict_schema(schema), strict=True))
    try:
        response = client.chat.complete(model=model, max_tokens=tokens, temperature=0, response_format=response_format,
                                        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
    except Exception as exc:
        raise sdk_error(exc) from exc
    record_usage(getattr(response, "usage", None))
    choice = (getattr(response, "choices", None) or [None])[0]
    reason = str(getattr(choice, "finish_reason", "") or "")
    if reason in ("length", "model_length"):
        raise AIResponseError("The answer was cut off", truncated=True)
    text = _text(getattr(getattr(choice, "message", None), "content", None)).strip()
    if not text:
        raise AIResponseError("Empty answer (%s)" % (reason or "no output"), blocked=reason == "error")
    return load_json(text)
