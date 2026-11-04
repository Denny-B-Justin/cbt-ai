"""The AI provider: every model call goes through the Posit mAI Gateway. Works only inside Posit Connect.

Settings (environment variables, set in Posit Connect under Settings -> Runtime -> Environment Variables):
    MAI_BASE_URL   gateway URL, ending in "/"
    MAI_ENDPOINT   mAI endpoint of the model provider, sent as the mai-endpoint query parameter
    MAI_MODEL      model name (optional; without it the default model of the endpoint's provider is used)
Posit Connect sets CONNECT_CONTENT_GUID itself; it is sent as X-Posit-App-Id. No keys or tokens are used.

The model family (from MAI_MODEL, else from MAI_ENDPOINT) decides the wire format:
    gpt-*     OpenAI Responses API through the openai SDK            JSON shape: strict json_schema
    gemini-*  Gemini Interactions API through the google-genai SDK   JSON shape: response_format
    claude-*  Bedrock Converse API over plain HTTP                   JSON shape: one forced tool call
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

from utils import constants as C

from .schemas import load_json
from .types import AIConfigError, AIError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment

log = logging.getLogger(__name__)

GPT, GEMINI, CLAUDE = "gpt", "gemini", "claude"
DEFAULT_MODELS = {GPT: "gpt-6-luna", GEMINI: "gemini-3.8-flash", CLAUDE: "claude-haiku-5-5"}
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
_client = None
_client_key: tuple = ()
_output_cap: int | None = None
_options_ok = {name: True for opts in OPTIONS.values() for name in opts}
_warned: set[str] = set()


class _OutputLimitError(AIResponseError):
    """The model refused the requested number of output tokens."""


# ── settings ────────────────────────────────────────────────────────────────
def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def base_url() -> str:
    url = _env(C.ENV_MAI_BASE_URL)
    return url if not url or url.endswith("/") else url + "/"


def _family_of_model(model: str) -> str:
    m = model.lower()
    if m.startswith(("claude", "us.anthropic.", "anthropic.")):
        return CLAUDE
    if m.startswith("gpt"):
        return GPT
    if m.startswith("gemini"):
        return GEMINI
    return ""


def _family_of_endpoint(endpoint: str) -> str:
    e = endpoint.lower().rstrip("/")
    if "/bedrock/" in e or e.endswith("/converse"):
        return CLAUDE
    if "/openai/" in e or e.endswith("/responses"):
        return GPT
    if "/gemini/" in e or e.endswith("/interactions"):
        return GEMINI
    return ""


def family() -> str:
    """gpt, gemini or claude. MAI_MODEL decides; MAI_ENDPOINT must point at the same provider."""
    by_model, by_endpoint = _family_of_model(_env(C.ENV_MAI_MODEL)), _family_of_endpoint(_env(C.ENV_MAI_ENDPOINT))
    if by_model and by_endpoint and by_model != by_endpoint:
        raise AIConfigError("MAI_MODEL is a %s model but MAI_ENDPOINT is a %s endpoint" % (by_model, by_endpoint))
    if not (by_model or by_endpoint):
        raise AIConfigError("Cannot tell the model provider from MAI_MODEL or MAI_ENDPOINT")
    return by_model or by_endpoint


def model_name() -> str:
    fam, model = family(), _env(C.ENV_MAI_MODEL)
    if fam == CLAUDE:
        if not model:
            m = re.search(r"/model/([^/]+)/converse", _env(C.ENV_MAI_ENDPOINT))
            model = m.group(1) if m and "<" not in m.group(1) else DEFAULT_MODELS[CLAUDE]
        return re.sub(r"^(us\.)?anthropic\.", "", model)
    return model or DEFAULT_MODELS[fam]


def endpoint() -> str:
    """MAI_ENDPOINT; for Claude the model in its path is set to model_name(), so MAI_MODEL picks the model."""
    ep = _env(C.ENV_MAI_ENDPOINT)
    if family() == CLAUDE:
        ep = re.sub(r"/model/[^/]+/converse", lambda _: "/model/us.anthropic.%s/converse" % model_name(), ep)
    return ep


def is_configured() -> bool:
    if not (base_url() and _env(C.ENV_MAI_ENDPOINT) and _env(C.ENV_CONNECT_GUID)):
        return False
    try:
        family()
    except AIConfigError as exc:
        if str(exc) not in _warned:
            _warned.add(str(exc))
            log.warning("mAI settings: %s", exc)
        return False
    return True


def _headers() -> dict:
    return {"X-Posit-App-Id": _env(C.ENV_CONNECT_GUID), "x-source-type": "interactive"}


# ── the one entry point ─────────────────────────────────────────────────────
def generate_json(system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                  max_output_tokens: int = 16384, temperature: float = 0.0) -> Any:
    """One attempt. Returns parsed JSON or raises one of the AI errors in ai/types.py.

    If the model refuses an optional setting or the requested output length, that is adjusted, remembered for
    later calls, and the request is sent again.
    """
    global _output_cap
    fam = family()
    send = {GPT: _gpt, GEMINI: _gemini, CLAUDE: _claude}[fam]
    while True:
        tokens = min(max_output_tokens, _output_cap or max_output_tokens)
        try:
            return send(system, prompt, schema, attachments, tokens, temperature)
        except _OutputLimitError:
            if tokens <= MIN_OUTPUT_TOKENS:
                raise
            with _lock:
                _output_cap = max(MIN_OUTPUT_TOKENS, tokens // 2)
            log.warning("Model refused %d output tokens; continuing with %d", tokens, _output_cap)
        except AIResponseError as exc:
            option = next((name for name, pattern in OPTIONS[fam].items()
                           if _options_ok[name] and re.search(pattern, str(exc), re.I)), None)
            if option is None or exc.too_long:
                raise
            _options_ok[option] = False
            log.warning("Model does not accept the %s setting; continuing without it", option)


def _client_for(fam: str):
    """One client, rebuilt when the settings change. The Gemini client must stay referenced or it closes itself."""
    global _client, _client_key
    key = (fam, base_url(), endpoint(), _env(C.ENV_CONNECT_GUID))
    with _lock:
        if _client is None or _client_key != key:
            _client = {GPT: _new_gpt_client, GEMINI: _new_gemini_client, CLAUDE: _new_http_client}[fam]()
            _client_key = key
        return _client


def _b64(a: Attachment) -> str:
    return base64.b64encode(a.data).decode("ascii")


# ── GPT: OpenAI Responses API ───────────────────────────────────────────────
def _new_gpt_client():
    from openai import OpenAI

    # api_key is not used by the gateway; max_retries=0 because ai/ratelimit.py already paces and retries.
    return OpenAI(base_url=base_url(), api_key="not-used", default_headers=_headers(),
                  default_query={"mai-endpoint": endpoint()}, timeout=TIMEOUT_S, max_retries=0)


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


def _gpt(system, prompt, schema, attachments, tokens, temperature) -> Any:
    # temperature is not sent: GPT-5 class reasoning models do not take it.
    request = dict(model=model_name(), instructions=system, max_output_tokens=tokens,
                   input=[{"role": "user", "content": _gpt_content(prompt, attachments)}],
                   text={"format": {"type": "json_schema", "name": TOOL_NAME, "schema": strict_schema(schema),
                                    "strict": True}})
    if _options_ok["reasoning"]:
        request["reasoning"] = {"effort": "low"}
    try:
        response = _client_for(GPT).responses.create(**request)
    except Exception as exc:
        raise _sdk_error(exc) from exc
    log.debug("mAI usage: %s", getattr(response, "usage", None))
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
def _new_gemini_client():
    from google import genai
    from google.genai import types

    # Retries are switched off (no status code is retryable) because ai/ratelimit.py already paces and retries.
    return genai.Client(api_key="not-used", http_options=types.HttpOptions(
        base_url=base_url().rstrip("/"), api_version="", headers=_headers(), timeout=int(TIMEOUT_S * 1000),
        client_args={"params": {"mai-endpoint": endpoint()}},
        retry_options=types.HttpRetryOptions(attempts=1, http_status_codes=[599])))


def _gemini(system, prompt, schema, attachments, tokens, temperature) -> Any:
    # temperature is not sent: Gemini 3 models are meant to run at their default.
    content = [{"type": "image" if a.mime_type.startswith("image/") else "document", "data": _b64(a),
                "mime_type": a.mime_type} for a in attachments]
    content.append({"type": "text", "text": prompt})
    config: dict[str, Any] = {"max_output_tokens": tokens}
    if _options_ok["thinking"]:
        config["thinking_level"] = "low"
    try:
        response = _client_for(GEMINI).interactions.create(
            model=model_name(), system_instruction=system, input=content, generation_config=config,
            response_format=schema, response_mime_type="application/json")
    except Exception as exc:
        raise _sdk_error(exc) from exc
    log.debug("mAI usage: %s", getattr(response, "usage", None))
    status = str(getattr(response, "status", "") or "")
    text = (getattr(response, "output_text", None) or "").strip()
    if status in ("incomplete", "budget_exceeded"):
        raise AIResponseError("The answer was cut off", truncated=True)
    if not text:
        raise AIResponseError("Empty answer (%s)" % (status or "no output"), blocked=True)
    return load_json(text)


# ── Claude: Bedrock Converse API ────────────────────────────────────────────
def _new_http_client():
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


def _claude(system, prompt, schema, attachments, tokens, temperature) -> Any:
    import httpx

    forced = _options_ok["forced_tool"]
    spec = {"name": TOOL_NAME, "description": "Return the answer in exactly this JSON shape.",
            "inputSchema": {"json": schema}}
    inference: dict[str, Any] = {"maxTokens": tokens}
    if _options_ok["temperature"]:
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
        response = _client_for(CLAUDE).post(base_url() + "converse", params={"mai-endpoint": endpoint()},
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
