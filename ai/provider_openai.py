"""OpenAI: the Responses API through the openai SDK, with strict JSON-schema output.

    client.responses.create(model=..., instructions=..., input=[...], max_output_tokens=...,
                            text={"format": {"type": "json_schema", "name": ..., "schema": ..., "strict": True}},
                            reasoning={"effort": "low"})

PDFs go inline as {"type": "input_file", "filename": ..., "file_data": "data:application/pdf;base64,..."}.
temperature is not sent: the current models are reasoning models.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .provider_common import TIMEOUT_S, TOOL_NAME, b64, record_usage, sdk_error, strict_schema
from .schemas import load_json
from .types import AIResponseError, Attachment

# Optional request settings a model may refuse: name -> words in the refusal. A refused one is dropped and remembered.
OPTIONS = {"reasoning": r"reasoning"}
SUPPORTS_ATTACHMENTS = True


def new_client(api_key: str, base_url: str = ""):
    from openai import OpenAI

    # max_retries=0 because ai/ratelimit.py already paces and retries.
    return OpenAI(api_key=api_key, base_url=base_url or None, timeout=TIMEOUT_S, max_retries=0)


def _content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for i, a in enumerate(attachments):
        url = "data:{};base64,{}".format(a.mime_type, b64(a))
        if a.mime_type.startswith("image/"):
            parts.append({"type": "input_image", "image_url": url})
        else:
            parts.append({"type": "input_file", "filename": "attachment-%d.pdf" % (i + 1), "file_data": url})
    parts.append({"type": "input_text", "text": prompt})
    return parts


def send(client, model: str, system: str, prompt: str, schema: dict, attachments: Sequence[Attachment], tokens: int,
         accepts: Callable[[str], bool]) -> Any:
    request = dict(model=model, instructions=system, max_output_tokens=tokens,
                   input=[{"role": "user", "content": _content(prompt, attachments)}],
                   text={"format": {"type": "json_schema", "name": TOOL_NAME, "schema": strict_schema(schema),
                                    "strict": True}})
    if accepts("reasoning"):
        request["reasoning"] = {"effort": "low"}
    try:
        response = client.responses.create(**request)
    except Exception as exc:
        raise sdk_error(exc) from exc
    record_usage(getattr(response, "usage", None))
    status = getattr(response, "status", "") or ""
    reason = getattr(getattr(response, "incomplete_details", None), "reason", "") or ""
    if status == "incomplete" and reason == "max_output_tokens":
        raise AIResponseError("The answer was cut off", truncated=True)
    refused = any(getattr(c, "type", "") == "refusal"
                  for item in (getattr(response, "output", None) or [])
                  for c in (getattr(item, "content", None) or []))
    text = (getattr(response, "output_text", None) or "").strip()
    if not text:
        raise AIResponseError("Empty answer (%s)" % (reason or status or "no output"),
                              blocked=refused or reason == "content_filter")
    return load_json(text)
