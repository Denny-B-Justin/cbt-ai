"""mAI provider, Claude models (World Bank gateway to Amazon Bedrock's Converse API, Azure service-principal sign-in).

Select it with AI_PROVIDER=mai-claude. Offers the same functions as ai/gemini.py.
Each call is POST {MAI_CLAUDE_BASE_URL}/model/{MAI_LLM}/converse with the Azure token as a Bearer header.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from typing import Any, Sequence

from utils import constants as C

from . import mai_common as mai
from .schemas import load_json
from .types import AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment

log = logging.getLogger(__name__)

TOOL_NAME = "answer"
DOC_FORMATS = {"application/pdf": "pdf", "text/csv": "csv", "text/plain": "txt", "text/html": "html",
               "text/markdown": "md", "application/msword": "doc", "application/vnd.ms-excel": "xls",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}
IMAGE_FORMATS = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}

_client = None
_lock = threading.Lock()
_forced_tool_ok = True


def is_configured() -> bool:
    return mai.is_configured(C.ENV_MAI_CLAUDE_BASE_URL)


def model_name() -> str:
    return mai.model_name(C.DEFAULT_MAI_CLAUDE_MODEL)


def _get_client():
    global _client
    import httpx

    with _lock:
        if _client is None:
            _client = httpx.Client(timeout=mai.TIMEOUT_S)
        return _client


def _url() -> str:
    return "%s/model/%s/converse" % (mai.base_url(C.ENV_MAI_CLAUDE_BASE_URL).rstrip("/"), model_name())


def _content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for i, a in enumerate(attachments):
        data = base64.b64encode(a.data).decode("ascii")
        if a.mime_type in IMAGE_FORMATS:
            parts.append({"image": {"format": IMAGE_FORMATS[a.mime_type], "source": {"bytes": data}}})
        else:
            parts.append({"document": {"format": DOC_FORMATS.get(a.mime_type, "pdf"), "name": "attachment %d" % (i + 1),
                                       "source": {"bytes": data}}})
    parts.append({"text": prompt})
    return parts


def _tool_config(schema: dict, forced: bool) -> dict:
    spec = {"name": TOOL_NAME, "description": "Return the answer in exactly this JSON shape.",
            "inputSchema": {"json": schema}}
    return {"tools": [{"toolSpec": spec}], "toolChoice": {"tool": {"name": TOOL_NAME}} if forced else {"auto": {}}}


def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    The JSON shape is enforced by making the model call one tool whose input schema is the task's schema.
    """
    global _forced_tool_ok
    payload = {
        "system": [{"text": system + "\n\nAlways reply by calling the %s tool." % TOOL_NAME}],
        "messages": [{"role": "user", "content": _content(prompt, attachments)}],
        "inferenceConfig": {"maxTokens": max_output_tokens, "temperature": temperature},
        "toolConfig": _tool_config(schema, _forced_tool_ok),
    }
    try:
        result = _call(payload)
    except AIResponseError as exc:
        # Newer Claude models reject a forced tool choice; let the model pick the tool itself instead.
        if _forced_tool_ok and re.search(r"tool_?choice", str(exc), re.I):
            log.warning("Model does not accept a forced tool choice; continuing with auto")
            _forced_tool_ok = False
            payload["toolConfig"] = _tool_config(schema, False)
            result = _call(payload)
        elif "temperature" in str(exc).lower() and "temperature" in payload["inferenceConfig"]:
            payload["inferenceConfig"].pop("temperature")
            result = _call(payload)
        else:
            raise
    log.debug("mAI usage: %s", result.get("usage"))
    return _parse(result)


def _call(payload: dict) -> dict:
    import httpx

    headers = dict(mai.headers(), Authorization="Bearer " + mai.access_token())
    try:
        response = _get_client().post(_url(), json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise AIServerError("Network problem talking to mAI: %s" % type(exc).__name__) from exc
    if response.status_code != 200:
        raise _map_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise AIServerError("mAI sent a reply that is not JSON") from exc


def _error_message(response) -> str:
    try:
        body = response.json()
        text = body.get("message") or body.get("Message") or body.get("error") or json.dumps(body)
    except ValueError:
        text = response.text
    return " ".join(str(text).split())[:300]


def _map_error(response) -> Exception:
    code = response.status_code
    message = _error_message(response)
    if code == 429:
        if re.search(r"quota|per day|daily", message, re.I):
            return AIQuotaError("Quota used up: " + message)
        try:
            retry = float(response.headers["retry-after"])
        except (KeyError, ValueError):
            retry = None
        return AIRateLimitError(message, retry)
    if code in (401, 403, 404):
        return AIConfigError("mAI rejected the request (%s): %s" % (code, message))
    if code in (408, 409) or code >= 500:
        return AIServerError("mAI server error %s: %s" % (code, message))
    return AIResponseError("mAI could not handle the request (%s): %s" % (code, message))


def _parse(result: dict) -> Any:
    reason = result.get("stopReason") or ""
    if reason == "max_tokens":
        raise AIResponseError("The answer was cut off", truncated=True)
    content = ((result.get("output") or {}).get("message") or {}).get("content") or []
    for block in content:
        tool = block.get("toolUse")
        if tool and tool.get("name") == TOOL_NAME:
            data = tool.get("input")
            return load_json(data) if isinstance(data, str) else data
    text = "".join(block.get("text", "") for block in content).strip()
    if not text:
        blocked = reason in ("content_filtered", "guardrail_intervened")
        raise AIResponseError("Empty answer (%s)" % (reason or "no content"), blocked=blocked)
    return load_json(text)
