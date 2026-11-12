"""The AI provider: every model call goes through the Posit mAI Gateway. Works only inside Posit Connect.

The person using the app picks the model; constants.MODELS lists the ones offered. Each call gets the model's id.

Settings (environment variables, set in Posit Connect under Settings -> Runtime -> Environment Variables):
    MAI_BASE_URL          gateway URL, ending in "/"
    MAI_OPENAI_ENDPOINT   mai-endpoint for the OpenAI models  (.../maifactory/openai/responses)
    MAI_GEMINI_ENDPOINT   mai-endpoint for the Gemini models  (.../maifactory/gemini/interactions)
    MAI_CLAUDE_ENDPOINT   mai-endpoint for the Claude models  (.../maifactory/bedrock/model/us.anthropic.<model>/converse)
A provider without its endpoint is offered as "not set up". For Claude the chosen model is written into the endpoint
path in place of <model>. Posit Connect sets CONNECT_CONTENT_GUID itself; it is sent as X-Posit-App-Id. No keys or
tokens are used.

The model's family decides the wire format:
    gpt     OpenAI Responses API through the openai SDK            JSON shape: strict json_schema
    gemini  Gemini Interactions API through the google-genai SDK   JSON shape: response_format
    claude  Bedrock Converse API over plain HTTP                   JSON shape: one forced tool call
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import re
import threading
from collections.abc import Sequence
from typing import Any

import constants as C

from .schemas import load_json
from .types import AIConfigError, AIError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment

log = logging.getLogger(__name__)

GPT, GEMINI, CLAUDE = C.GPT, C.GEMINI, C.CLAUDE
TIMEOUT_S = 240.0
MIN_OUTPUT_TOKENS = 4096
TOOL_NAME = "answer"

DOC_FORMATS = {"application/pdf": "pdf", "text/csv": "csv", "text/plain": "txt", "text/html": "html",
               "text/markdown": "md", "application/msword": "doc", "application/vnd.ms-excel": "xls",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx"}
IMAGE_FORMATS = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}

# A 400 whose message says the request is too big for the model (input side) or asks for too many output tokens.
TOO_LONG = re.compile(r"too (long|large|many tokens)|context (length|window)|input token|prompt token|request entity"
                      r"|payload too|exceeds? (the )?(max|limit|size|context)|file size|maximum (context|input|prompt)",
                      re.I)
OUTPUT_LIMIT = re.compile(r"max_?tokens|maxtokens|max_output_tokens|max_completion_tokens|output tokens"
                          r"|maximum tokens you requested", re.I)
# Optional request settings a model may refuse. Each one is dropped (and remembered) the first time it is refused.
OPTIONS = {GPT: {"reasoning": r"reasoning"},
           GEMINI: {"thinking": r"thinking"},
           CLAUDE: {"forced_tool": r"tool_?choice", "temperature": r"temperature"}}

_lock = threading.Lock()
_clients: dict[tuple, Any] = {}                         # one client per (family, gateway, endpoint, app id)
_output_cap: dict[str, int] = {}                        # model -> refused output length, halved
_refused: set[tuple[str, str]] = set()                  # (model, optional setting) the model would not take
_warned: set[str] = set()
_usage = threading.local()                              # tokens of the last attempt in this thread


class _OutputLimitError(AIResponseError):
    """The model refused the requested number of output tokens."""


# ── settings ────────────────────────────────────────────────────────────────
def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def base_url() -> str:
    url = _env(C.ENV_MAI_BASE_URL)
    return url if not url or url.endswith("/") else url + "/"


def model_info(model: str) -> C.Model:
    try:
        return C.MODELS_BY_ID[model]
    except KeyError:
        raise AIConfigError("Unknown model %r; offer it in constants.MODELS first" % model) from None


def endpoint(model: str) -> str:
    """The mai-endpoint of the model's provider. For Claude the model goes into the path, in place of <model>."""
    info = model_info(model)
    ep = _env(C.ENV_MAI_ENDPOINTS[info.family])
    if info.family == CLAUDE:                  # ".../model/us.anthropic.<model>/converse", or with any model in that place
        ep = re.sub(r"/model/[^/]+/converse", lambda _: "/model/us.anthropic.%s/converse" % model, ep)
    return ep


def is_available(model: str) -> bool:
    """The gateway, the app id and the endpoint of this model's provider are all set."""
    return model in C.MODELS_BY_ID and bool(base_url() and _env(C.ENV_CONNECT_GUID) and endpoint(model))


def available_models() -> list[str]:
    return [m.id for m in C.MODELS if is_available(m.id)]


def is_configured() -> bool:
    """At least one model can be used."""
    ok = bool(available_models())
    if not ok and "settings" not in _warned:
        _warned.add("settings")
        log.warning("mAI settings: %s, %s and at least one of %s are needed", C.ENV_MAI_BASE_URL, C.ENV_CONNECT_GUID,
                    ", ".join(C.ENV_MAI_ENDPOINTS.values()))
    return ok


def _headers() -> dict:
    return {"X-Posit-App-Id": _env(C.ENV_CONNECT_GUID), "x-source-type": "interactive"}


# ── tokens used ─────────────────────────────────────────────────────────────
def _field(obj: Any, *names: str) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _record_usage(usage: Any) -> None:
    """Total tokens from a GPT, Gemini or Claude usage block; nothing if the reply did not say."""
    if usage is None:
        return
    total = _field(usage, "total_tokens", "totalTokens", "total_token_count")
    if total is None:
        parts = [_field(usage, "input_tokens", "inputTokens", "prompt_token_count", "total_input_tokens"),
                 _field(usage, "output_tokens", "outputTokens", "candidates_token_count", "total_output_tokens")]
        total = sum(parts) if any(p is not None for p in parts) else None
    if total is not None:
        _usage.tokens = int(total)


def last_usage() -> int | None:
    """Tokens the last call in this thread used, as the model reported them (None if unknown)."""
    return getattr(_usage, "tokens", None)


# ── the one entry point ─────────────────────────────────────────────────────
def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0, model: str = C.DEFAULT_MODEL) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    If the model refuses an optional setting or the requested output length, that is adjusted, remembered for
    later calls of the same model, and the request is sent again.
    """
    fam = model_info(model).family
    if not is_available(model):
        raise AIConfigError("%s is not set up: %s is missing" % (model, C.ENV_MAI_ENDPOINTS[fam]))
    send = {GPT: _gpt, GEMINI: _gemini, CLAUDE: _claude}[fam]
    _usage.tokens = None
    while True:
        tokens = min(max_output_tokens, _output_cap.get(model, max_output_tokens))
        try:
            return send(model, system, prompt, schema, attachments, tokens, temperature)
        except _OutputLimitError:
            if tokens <= MIN_OUTPUT_TOKENS:
                raise
            with _lock:
                _output_cap[model] = max(MIN_OUTPUT_TOKENS, tokens // 2)
            log.warning("%s refused %d output tokens; continuing with %d", model, tokens, _output_cap[model])
        except AIResponseError as exc:
            option = next((name for name, pattern in OPTIONS[fam].items()
                           if _accepts(model, name) and re.search(pattern, str(exc), re.I)), None)
            if option is None or exc.too_long:
                raise
            _refused.add((model, option))
            log.warning("%s does not accept the %s setting; continuing without it", model, option)


def _accepts(model: str, option: str) -> bool:
    return (model, option) not in _refused


def _client_for(model: str):
    """One client per provider and settings, kept for later calls. The Gemini client must stay referenced or it
    closes itself. Claude's client is plain HTTP: the endpoint goes with each request, so all Claude models share it."""
    fam = model_info(model).family
    ep = endpoint(model)
    key = (fam, base_url(), ep if fam != CLAUDE else "", _env(C.ENV_CONNECT_GUID))
    with _lock:
        if key not in _clients:
            _clients[key] = {GPT: _new_gpt_client, GEMINI: _new_gemini_client, CLAUDE: _new_http_client}[fam](ep)
        return _clients[key]


def _b64(a: Attachment) -> str:
    return base64.b64encode(a.data).decode("ascii")


# ── GPT: OpenAI Responses API ───────────────────────────────────────────────
def _new_gpt_client(mai_endpoint: str):
    from openai import OpenAI

    # api_key is not used by the gateway; max_retries=0 because ai/ratelimit.py already paces and retries.
    return OpenAI(base_url=base_url(), api_key="not-used", default_headers=_headers(),
                  default_query={"mai-endpoint": mai_endpoint}, timeout=TIMEOUT_S, max_retries=0)


def _gpt_content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for i, a in enumerate(attachments):
        url = "data:{};base64,{}".format(a.mime_type, _b64(a))
        if a.mime_type.startswith("image/"):
            parts.append({"type": "input_image", "image_url": url})
        else:
            parts.append({"type": "input_file", "filename": "attachment-%d.pdf" % (i + 1), "file_data": url})
    parts.append({"type": "input_text", "text": prompt})
    return parts


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


def _gpt(model, system, prompt, schema, attachments, tokens, temperature) -> Any:
    # temperature is not sent: GPT-5 class reasoning models do not take it.
    request = dict(model=model, instructions=system, max_output_tokens=tokens,
                   input=[{"role": "user", "content": _gpt_content(prompt, attachments)}],
                   text={"format": {"type": "json_schema", "name": TOOL_NAME, "schema": strict_schema(schema),
                                    "strict": True}})
    if _accepts(model, "reasoning"):
        request["reasoning"] = {"effort": "low"}
    try:
        response = _client_for(model).responses.create(**request)
    except Exception as exc:
        raise _sdk_error(exc) from exc
    log.debug("mAI usage: %s", getattr(response, "usage", None))
    _record_usage(getattr(response, "usage", None))
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


# ── Gemini: Interactions API ────────────────────────────────────────────────
def _new_gemini_client(mai_endpoint: str):
    from google import genai
    from google.genai import types

    # Retries are switched off (no status code is retryable) because ai/ratelimit.py already paces and retries.
    return genai.Client(api_key="not-used", http_options=types.HttpOptions(
        base_url=base_url().rstrip("/"), api_version="", headers=_headers(), timeout=int(TIMEOUT_S * 1000),
        client_args={"params": {"mai-endpoint": mai_endpoint}},
        retry_options=types.HttpRetryOptions(attempts=1, http_status_codes=[599])))


def _gemini(model, system, prompt, schema, attachments, tokens, temperature) -> Any:
    # temperature is not sent: Gemini 3 models are meant to run at their default.
    content = [{"type": "image" if a.mime_type.startswith("image/") else "document", "data": _b64(a),
                "mime_type": a.mime_type} for a in attachments]
    content.append({"type": "text", "text": prompt})
    config: dict[str, Any] = {"max_output_tokens": tokens}
    if _accepts(model, "thinking"):
        config["thinking_level"] = "low"
    try:
        response = _client_for(model).interactions.create(
            model=model, system_instruction=system, input=content, generation_config=config,
            response_format=schema, response_mime_type="application/json")
    except Exception as exc:
        raise _sdk_error(exc) from exc
    log.debug("mAI usage: %s", getattr(response, "usage", None))
    _record_usage(getattr(response, "usage", None))
    status = str(getattr(response, "status", "") or "")
    text = (getattr(response, "output_text", None) or "").strip()
    if status in ("incomplete", "budget_exceeded"):
        raise AIResponseError("The answer was cut off", truncated=True)
    if not text:
        raise AIResponseError("Empty answer (%s)" % (status or "no output"), blocked=True)
    return load_json(text)


# ── Claude: Bedrock Converse API ────────────────────────────────────────────
def _new_http_client(_mai_endpoint: str = ""):
    import httpx

    return httpx.Client(timeout=TIMEOUT_S)


def _claude_content(prompt: str, attachments: Sequence[Attachment]) -> list:
    parts = []
    for i, a in enumerate(attachments):
        if a.mime_type in IMAGE_FORMATS:
            parts.append({"image": {"format": IMAGE_FORMATS[a.mime_type], "source": {"bytes": _b64(a)}}})
        else:
            parts.append({"document": {"format": DOC_FORMATS.get(a.mime_type, "pdf"), "name": "attachment %d" % (i + 1),
                                       "source": {"bytes": _b64(a)}}})
    parts.append({"text": prompt})
    return parts


def _claude(model, system, prompt, schema, attachments, tokens, temperature) -> Any:
    import httpx

    forced = _accepts(model, "forced_tool")
    spec = {"name": TOOL_NAME, "description": "Return the answer in exactly this JSON shape.",
            "inputSchema": {"json": schema}}
    inference: dict[str, Any] = {"maxTokens": tokens}
    if _accepts(model, "temperature"):
        inference["temperature"] = temperature
    payload = {
        "system": [{"text": system + "\n\nAlways reply by calling the %s tool. If you cannot, reply with the JSON "
                                     "object only." % TOOL_NAME}],
        "messages": [{"role": "user", "content": _claude_content(prompt, attachments)}],
        "inferenceConfig": inference,
        "toolConfig": {"tools": [{"toolSpec": spec}],
                       "toolChoice": {"tool": {"name": TOOL_NAME}} if forced else {"auto": {}}},
    }
    try:
        response = _client_for(model).post(base_url() + "converse", params={"mai-endpoint": endpoint(model)},
                                            headers=dict(_headers(), **{"Content-Type": "application/json"}),
                                            json=payload)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise AIServerError("Network problem talking to mAI: %s" % type(exc).__name__) from exc
    if response.status_code != 200:
        raise _status_error(response.status_code, _body_message(response), response.headers)
    try:
        result = response.json()
    except ValueError as exc:
        raise AIServerError("mAI sent a reply that is not JSON") from exc
    log.debug("mAI usage: %s", result.get("usage"))
    _record_usage(result.get("usage"))
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
        raise AIResponseError("Empty answer (%s)" % (reason or "no content"),
                              blocked=reason in ("content_filtered", "guardrail_intervened"))
    return load_json(text)


# ── errors ──────────────────────────────────────────────────────────────────
def _short(text: Any) -> str:
    return " ".join(str(text).split())[:300]


def _body_message(response) -> str:
    try:
        body = response.json()
        error = body.get("error")
        text = (body.get("message") or body.get("Message") or (error.get("message") if isinstance(error, dict) else error)
                or json.dumps(body))
    except (ValueError, AttributeError):
        text = response.text
    return _short(text)


def _sdk_error(exc: Exception) -> Exception:
    """Map an exception from the openai or google-genai SDK. Both carry status_code and response on HTTP errors."""
    import httpx

    if isinstance(exc, AIError):
        return exc
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        response = getattr(exc, "response", None)
        return _status_error(status, _short(getattr(exc, "message", "") or exc), getattr(response, "headers", None) or {})
    name = type(exc).__name__
    if "Timeout" in name or "Connection" in name or isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return AIServerError("Network problem talking to mAI: %s" % name)
    return exc


def _retry_after(headers, message: str) -> float | None:
    try:
        if headers.get("retry-after-ms"):
            return float(headers["retry-after-ms"]) / 1000
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        pass
    m = re.search(r"(?:retry|try again) (?:after|in) (\d+(?:\.\d+)?) ?s", message, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"replenished in (\d+):(\d\d):(\d\d)", message, re.I)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return None


def _status_error(code: int, message: str, headers) -> Exception:
    if code == 413 or (code == 400 and TOO_LONG.search(message)):
        return AIResponseError("The request was too large for the model: " + message, too_long=True)
    if code == 400 and OUTPUT_LIMIT.search(message):
        return _OutputLimitError(message)
    if code == 429:
        retry = _retry_after(headers, message)
        if re.search(r"insufficient_quota|per day|daily|quota", message, re.I) and (retry is None or retry > 300):
            return AIQuotaError("Quota used up: " + message)
        return AIRateLimitError(message, retry)
    if code in (401, 403, 404) or (code == 400 and re.search(r"missing required (header|parameter)", message, re.I)):
        return AIConfigError("mAI rejected the request ({}): {}".format(code, message))
    if code in (408, 409, 425) or code >= 500:
        return AIServerError("mAI server error {}: {}".format(code, message))
    return AIResponseError("mAI could not handle the request ({}): {}".format(code, message))
