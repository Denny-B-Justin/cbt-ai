"""Anthropic: the Messages API through the anthropic SDK.

    client.messages.create(model=..., max_tokens=..., system=..., messages=[...],
                           output_config={"format": {"type": "json_schema", "schema": ...}})

Structured outputs (output_config) are generally available on the current models, which also reject a forced tool
call. If a model refuses output_config, the call falls back to one forced tool call, and if that is refused too, to
plain JSON text. Each refusal is remembered for that model. PDFs go inline as
{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": ...}}.
temperature is not sent: the current models do not take sampling parameters.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .provider_common import TIMEOUT_S, TOOL_NAME, b64, record_usage, sdk_error, strict_schema
from .schemas import load_json
from .types import AIResponseError, Attachment

OPTIONS = {"structured_output": r"output_config|output_format|json_schema|structured output",
           "forced_tool": r"tool_choice"}
SUPPORTS_ATTACHMENTS = True
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")


def new_client(api_key: str, base_url: str = ""):
    from anthropic import Anthropic

    # max_retries=0 because ai/ratelimit.py already paces and retries.
    return Anthropic(api_key=api_key, base_url=base_url or None, timeout=TIMEOUT_S, max_retries=0)


def _content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for a in attachments:
        kind = "image" if a.mime_type in IMAGE_TYPES else "document"
        parts.append({"type": kind, "source": {"type": "base64", "media_type": a.mime_type, "data": b64(a)}})
    parts.append({"type": "text", "text": prompt})
    return parts


def send(client, model: str, system: str, prompt: str, schema: dict, attachments: Sequence[Attachment], tokens: int,
         accepts: Callable[[str], bool]) -> Any:
    request: dict[str, Any] = dict(model=model, max_tokens=tokens, system=system,
                                   messages=[{"role": "user", "content": _content(prompt, attachments)}])
    if accepts("structured_output"):
        request["output_config"] = {"format": {"type": "json_schema", "schema": strict_schema(schema)}}
    elif accepts("forced_tool"):
        request["tools"] = [{"name": TOOL_NAME, "description": "Return the answer in exactly this JSON shape.",
                             "input_schema": schema}]
        request["tool_choice"] = {"type": "tool", "name": TOOL_NAME}
    else:
        request["system"] = system + "\n\nReply with the JSON object only, with no text before or after it."
    try:
        response = client.messages.create(**request)
    except Exception as exc:
        raise sdk_error(exc) from exc
    record_usage(getattr(response, "usage", None))
    reason = getattr(response, "stop_reason", "") or ""
    if reason == "max_tokens":
        raise AIResponseError("The answer was cut off", truncated=True)
    blocks = getattr(response, "content", None) or []
    for block in blocks:
        if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == TOOL_NAME:
            data = getattr(block, "input", None)
            return load_json(data) if isinstance(data, str) else data
    text = "".join(getattr(b, "text", "") or "" for b in blocks if getattr(b, "type", "") == "text").strip()
    if not text:
        raise AIResponseError("Empty answer (%s)" % (reason or "no content"), blocked=reason == "refusal")
    return load_json(text)
