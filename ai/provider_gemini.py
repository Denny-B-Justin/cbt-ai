"""Google Gemini: the Interactions API through the google-genai SDK (the Gemini API docs' current pattern).

    client.interactions.create(model=..., system_instruction=..., input=[...],
                               response_format={"type": "text", "mime_type": "application/json", "schema": ...},
                               generation_config={"max_output_tokens": ..., "thinking_level": "low"})

PDFs go inline as {"type": "document", "data": <base64>, "mime_type": "application/pdf"}. An answer cut off by the
output limit comes back with status "incomplete". temperature is not sent: Gemini 3 and later run at their default.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .provider_common import TIMEOUT_S, b64, record_usage, sdk_error
from .schemas import load_json
from .types import AIResponseError, Attachment

OPTIONS = {"thinking": r"thinking"}
SUPPORTS_ATTACHMENTS = True


def new_client(api_key: str, base_url: str = ""):
    from google import genai
    from google.genai import types

    # Retries are switched off (no status code is retryable) because ai/ratelimit.py already paces and retries.
    options = dict(timeout=int(TIMEOUT_S * 1000), retry_options=types.HttpRetryOptions(attempts=1, http_status_codes=[599]))
    if base_url:
        options["base_url"] = base_url
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(**options))


def send(client, model: str, system: str, prompt: str, schema: dict, attachments: Sequence[Attachment], tokens: int,
         accepts: Callable[[str], bool]) -> Any:
    content = [{"type": "image" if a.mime_type.startswith("image/") else "document", "data": b64(a),
                "mime_type": a.mime_type} for a in attachments]
    content.append({"type": "text", "text": prompt})
    config: dict[str, Any] = {"max_output_tokens": tokens}
    if accepts("thinking"):
        config["thinking_level"] = "low"
    try:
        response = client.interactions.create(
            model=model, system_instruction=system, input=content, generation_config=config,
            response_format={"type": "text", "mime_type": "application/json", "schema": schema})
    except Exception as exc:
        raise sdk_error(exc) from exc
    record_usage(getattr(response, "usage", None))
    status = str(getattr(response, "status", "") or "")
    text = (getattr(response, "output_text", None) or "").strip()
    if status in ("incomplete", "requires_continuation"):
        raise AIResponseError("The answer was cut off", truncated=True)
    if not text:
        raise AIResponseError("Empty answer (%s)" % (status or "no output"), blocked=status != "completed")
    return load_json(text)
