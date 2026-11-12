"""ai/mai_llm.py against a local stand-in for the Posit mAI Gateway: settings, request shape per model family,
fallbacks and error handling. No network needed."""

import pytest

import constants as C
from ai import client, mai_llm
from ai.types import AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment
from tests.fake_mai_server import FakeMaiServer, claude_body, error_body, gemini_body, gpt_body

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
QA = "https://azapimqa.worldbank.org/maifactory/"
ENV = {"gpt": "MAI_OPENAI_ENDPOINT", "gemini": "MAI_GEMINI_ENDPOINT", "claude": "MAI_CLAUDE_ENDPOINT"}
TEMPLATES = {"gpt": QA + "openai/responses", "gemini": QA + "gemini/interactions",
             "claude": QA + "bedrock/model/us.anthropic.<model>/converse"}          # as the developer guide writes them
MODEL = {"gpt": "gpt-6-luna", "gemini": "gemini-3.8-flash", "claude": "claude-haiku-5-5"}
ENDPOINTS = {"gpt": TEMPLATES["gpt"], "gemini": TEMPLATES["gemini"],
             "claude": QA + "bedrock/model/us.anthropic.claude-haiku-5-5/converse"}
OK = {"gpt": lambda: gpt_body('{"a": 1}'), "gemini": lambda: gemini_body('{"a": 1}'),
      "claude": lambda: claude_body({"a": 1})}


def reset():
    mai_llm._clients.clear()
    mai_llm._output_cap.clear()
    mai_llm._refused.clear()
    mai_llm._warned.clear()


@pytest.fixture(autouse=True)
def _fresh():
    reset()
    yield
    reset()


def settings(monkeypatch, families=("gpt", "gemini", "claude"), base="https://gw/posit-mai/conversationalai/"):
    monkeypatch.setenv("MAI_BASE_URL", base)
    for fam, name in ENV.items():
        if fam in families:
            monkeypatch.setenv(name, TEMPLATES[fam])
        else:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CONNECT_CONTENT_GUID", "app-guid-1")


@pytest.fixture(params=["gpt", "gemini", "claude"])
def gateway(request, monkeypatch):
    srv = FakeMaiServer(OK[request.param]).start()
    settings(monkeypatch, base=srv.url)
    srv.family = request.param
    srv.model = MODEL[request.param]
    yield srv
    reset()
    srv.stop()


def ask(gateway, **kw):
    return mai_llm.generate_json("SYSTEM TEXT", "PROMPT TEXT", SCHEMA, model=gateway.model, **kw)


# ── settings ────────────────────────────────────────────────────────────────
def test_every_model_of_the_picker_is_on_the_gateways_allowed_list():
    allowed = {"claude-haiku-5-5", "gpt-6-luna", "gpt-5.6-luna", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
               "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"}       # developer guide, section 3
    assert {m.id for m in C.MODELS} <= allowed and C.DEFAULT_MODEL in C.MODELS_BY_ID
    assert len({m.label for m in C.MODELS}) == len(C.MODELS)


def test_each_provider_is_available_only_with_its_own_endpoint(monkeypatch):
    settings(monkeypatch, families=("gemini",))
    assert mai_llm.available_models() == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]
    assert mai_llm.is_configured() and client.is_configured()
    assert client.default_model() == "gemini-3.8-flash", "the default model falls back to the first one set up"
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA, model="gpt-6-luna")
    settings(monkeypatch)
    assert mai_llm.available_models() == [m.id for m in C.MODELS] and client.default_model() == C.DEFAULT_MODEL


def test_the_endpoint_follows_the_chosen_model(monkeypatch):
    settings(monkeypatch)
    assert mai_llm.endpoint("gpt-5.6-luna") == mai_llm.endpoint("gpt-6-luna") == TEMPLATES["gpt"]
    assert mai_llm.endpoint("gemini-3.5-flash-lite") == TEMPLATES["gemini"]
    assert mai_llm.endpoint("claude-haiku-5-5") == ENDPOINTS["claude"]
    monkeypatch.setenv("MAI_CLAUDE_ENDPOINT", QA + "bedrock/model/us.anthropic.claude-old/converse")
    assert mai_llm.endpoint("claude-haiku-5-5") == ENDPOINTS["claude"], "a model already in the path is replaced too"


def test_an_unknown_model_is_a_setup_error(monkeypatch):
    settings(monkeypatch)
    with pytest.raises(AIConfigError):
        mai_llm.generate_json("s", "p", SCHEMA, model="gpt-4")
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA, model="gpt-4")


def test_base_url_gets_its_trailing_slash(monkeypatch):
    settings(monkeypatch, base="https://gw/posit-mai/conversationalai")
    assert mai_llm.base_url() == "https://gw/posit-mai/conversationalai/"


@pytest.mark.parametrize("missing", ["MAI_BASE_URL", "CONNECT_CONTENT_GUID"])
def test_not_configured_without_each_required_setting(monkeypatch, missing):
    settings(monkeypatch)
    monkeypatch.delenv(missing)
    assert not mai_llm.is_configured() and not client.is_configured() and client.available_models() == []
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA)


def test_not_configured_without_any_endpoint(monkeypatch):
    settings(monkeypatch, families=())
    assert not mai_llm.is_configured() and not client.is_configured()


# ── request shape ───────────────────────────────────────────────────────────
def test_every_request_carries_the_app_id_and_the_endpoint(gateway):
    assert ask(gateway, attachments=[Attachment("application/pdf", b"%PDF-1.4 data")]) == {"a": 1}
    req = gateway.requests[-1]
    assert req["path"].endswith({"gpt": "/responses", "gemini": "/interactions", "claude": "/converse"}[gateway.family])
    assert req["path"].startswith(FakeMaiServer.PREFIX)
    assert req["query"]["mai-endpoint"] == ENDPOINTS[gateway.family]
    assert req["headers"]["x-posit-app-id"] == "app-guid-1" and req["headers"]["x-source-type"] == "interactive"
    assert req["headers"]["content-type"].startswith("application/json")
    if gateway.family == "claude":
        assert "authorization" not in req["headers"]


def test_gpt_request_body(gateway):
    if gateway.family != "gpt":
        pytest.skip("GPT only")
    ask(gateway, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = gateway.requests[-1]["body"]
    assert body["model"] == gateway.model and body["instructions"] == "SYSTEM TEXT" and body["max_output_tokens"] == 777
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] and fmt["schema"]["additionalProperties"] is False
    parts = body["input"][0]["content"]
    assert parts[0]["type"] == "input_file" and parts[0]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[-1] == {"type": "input_text", "text": "PROMPT TEXT"} and body["reasoning"] == {"effort": "low"}


def test_gemini_request_body(gateway):
    if gateway.family != "gemini":
        pytest.skip("Gemini only")
    ask(gateway, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = gateway.requests[-1]["body"]
    assert body["model"] == gateway.model and body["system_instruction"] == "SYSTEM TEXT"
    assert body["response_format"] == SCHEMA and body["response_mime_type"] == "application/json"
    assert body["generation_config"] == {"max_output_tokens": 777, "thinking_level": "low"}
    content = body["input"][0]["content"]
    assert content[0]["type"] == "document" and content[0]["mime_type"] == "application/pdf"
    assert content[-1] == {"type": "text", "text": "PROMPT TEXT"}


def test_claude_request_body(gateway):
    if gateway.family != "claude":
        pytest.skip("Claude only")
    ask(gateway, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = gateway.requests[-1]["body"]
    assert body["inferenceConfig"] == {"maxTokens": 777, "temperature": 0.0}
    assert body["toolConfig"]["toolChoice"] == {"tool": {"name": "answer"}}
    assert body["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"] == SCHEMA
    content = body["messages"][0]["content"]
    assert content[0]["document"]["format"] == "pdf" and content[-1] == {"text": "PROMPT TEXT"}


def test_claude_answer_as_plain_json_text_is_accepted(gateway):
    if gateway.family != "claude":
        pytest.skip("Claude only")
    gateway.queue.append((200, claude_body(text='```json\n{"a": 2}\n```', stop="end_turn")))
    assert ask(gateway) == {"a": 2}


# ── fallbacks ───────────────────────────────────────────────────────────────
REFUSALS = {"gpt": ("Unsupported parameter: 'reasoning.effort' is not supported with this model.", "reasoning"),
            "gemini": ("thinking_level is not supported for this model", "thinking"),
            "claude": ("The model returned the following errors: toolChoice is not supported", "forced_tool")}


def test_a_refused_optional_setting_is_dropped_and_remembered(gateway):
    message, option = REFUSALS[gateway.family]
    gateway.queue.append((400, error_body(400, message)))
    assert ask(gateway) == {"a": 1} and len(gateway.requests) == 2 and not mai_llm._accepts(gateway.model, option)
    first, second = gateway.requests[0]["body"], gateway.requests[1]["body"]
    assert first != second
    ask(gateway)
    assert gateway.requests[-1]["body"] == second, "remembered for later calls"


def test_a_refused_output_length_is_halved_and_remembered(gateway):
    gateway.queue.append((400, error_body(400, "max_tokens: 32768 > 16000, which is the maximum allowed number of output tokens")))
    assert ask(gateway, max_output_tokens=32768) == {"a": 1}
    assert mai_llm._output_cap[gateway.model] == 16384
    ask(gateway, max_output_tokens=32768)
    assert len(gateway.requests) == 3


@pytest.mark.parametrize("status,message", [(413, "Request entity too large"),
                                            (400, "Input is too long for requested model."),
                                            (400, "The input token count (1200000) exceeds the maximum number of tokens allowed")])
def test_a_request_too_large_for_the_model_says_so(gateway, status, message):
    gateway.queue.append((status, error_body(status, message)))
    with pytest.raises(AIResponseError) as caught:
        ask(gateway)
    assert caught.value.too_long and len(gateway.requests) == 1


# ── errors ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status,message,headers,error", [
    (429, "Rate limit is exceeded. Try again in 12 seconds.", {}, AIRateLimitError),
    (429, "Too many requests", {"Retry-After": "7"}, AIRateLimitError),
    (429, "Out of call volume quota. Quota will be replenished in 05:12:00.", {}, AIQuotaError),
    (403, "Model not allowed for Posit applications.", {}, AIConfigError),
    (403, "Invalid Posit application ID.", {}, AIConfigError),
    (403, "Access denied / Forbidden", {}, AIConfigError),
    (400, "Missing required header: 'X-Posit-App-Id'", {}, AIConfigError),
    (404, "Resource not found", {}, AIConfigError),
    (500, "Internal error", {}, AIServerError),
    (503, "The model is overloaded", {}, AIServerError),
    (400, "Request contains an invalid argument", {}, AIResponseError),
])
def test_http_errors_become_the_right_error(gateway, status, message, headers, error):
    gateway.queue.append((status, error_body(status, message), headers))
    with pytest.raises(error) as caught:
        ask(gateway)
    assert type(caught.value) is error
    assert len(gateway.requests) == 1, "the SDKs must not retry on their own; ai/ratelimit.py does"


def test_rate_limit_error_carries_the_advised_wait(gateway):
    gateway.queue.append((429, error_body(429, "Too many requests"), {"Retry-After": "37"}))
    with pytest.raises(AIRateLimitError) as caught:
        ask(gateway)
    assert caught.value.retry_after == 37.0


TRUNCATED = {"gpt": gpt_body('{"a": ', status="incomplete", reason="max_output_tokens"),
             "gemini": gemini_body('{"a": ', status="incomplete"),
             "claude": claude_body(text='{"a": ', stop="max_tokens")}
EMPTY = {"gpt": gpt_body(""), "gemini": gemini_body(""), "claude": claude_body(text="", stop="content_filtered")}


def test_a_cut_off_answer_is_marked_truncated(gateway):
    gateway.queue.append((200, TRUNCATED[gateway.family]))
    with pytest.raises(AIResponseError) as caught:
        ask(gateway)
    assert caught.value.truncated


def test_an_empty_answer_is_an_error(gateway):
    gateway.queue.append((200, EMPTY[gateway.family]))
    with pytest.raises(AIResponseError):
        ask(gateway)


def test_unreachable_gateway_is_a_temporary_error(monkeypatch):
    for family in ("gpt", "gemini", "claude"):
        reset()
        settings(monkeypatch, base="http://127.0.0.1:9/posit-mai/conversationalai/")
        with pytest.raises(AIServerError):
            mai_llm.generate_json("s", "p", SCHEMA, model=MODEL[family])


def test_the_whole_path_through_the_client_uses_the_gateway(gateway):
    assert client.ask_json("s", "p", SCHEMA, model=gateway.model) == {"a": 1} and len(gateway.requests) == 1
    assert gateway.requests[-1]["query"]["mai-endpoint"] == ENDPOINTS[gateway.family]


def test_a_second_model_of_the_same_provider_uses_its_own_name(gateway):
    other = {"gpt": "gpt-5.6-luna", "gemini": "gemini-3.5-flash-lite", "claude": "claude-haiku-5-5"}[gateway.family]
    mai_llm.generate_json("s", "p", SCHEMA, model=other)
    req = gateway.requests[-1]
    if gateway.family == "claude":
        assert req["query"]["mai-endpoint"] == ENDPOINTS["claude"]
    else:
        assert req["body"]["model"] == other
