"""ai/llm.py and the four provider modules against a local stand-in for the OpenAI, Anthropic, Gemini and Mistral
APIs, with the real SDKs: settings, request shape per provider, fallbacks and error handling. No network needed."""

import pytest

import constants as C
from ai import client, llm
from ai.types import AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment
from tests.fake_llm_server import FakeLLMServer, anthropic_body, error_body, gemini_body, mistral_body, openai_body

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
PROVIDERS = list(C.PROVIDERS)
MODEL = {C.OPENAI: "gpt-6.1-sol", C.ANTHROPIC: "claude-sonnet-5-5", C.GEMINI: "gemini-3.8-flash",
         C.MISTRAL: "mistral-medium-latest"}
OK = {C.OPENAI: lambda: openai_body('{"a": 1}'), C.ANTHROPIC: lambda: anthropic_body('{"a": 1}'),
      C.GEMINI: lambda: gemini_body('{"a": 1}'), C.MISTRAL: lambda: mistral_body('{"a": 1}')}
PATH = {C.OPENAI: "/v1/responses", C.ANTHROPIC: "/v1/messages", C.GEMINI: "/interactions", C.MISTRAL: "/v1/chat/completions"}


def reset():
    llm._clients.clear()
    llm._output_cap.clear()
    llm._refused.clear()
    llm._warned.clear()


@pytest.fixture(autouse=True)
def _fresh():
    reset()
    yield
    reset()


def keys(monkeypatch, providers=PROVIDERS, base=None):
    for p in C.PROVIDERS:
        for name in (C.ENV_API_KEYS[p],) + C.ENV_API_KEY_ALIASES.get(p, ()):
            monkeypatch.delenv(name, raising=False)
        if p in providers:
            monkeypatch.setenv(C.ENV_API_KEYS[p], "key-" + p)
        if base is not None:
            monkeypatch.setenv(C.ENV_BASE_URLS[p], base(p))


@pytest.fixture(params=PROVIDERS)
def api(request, monkeypatch):
    srv = FakeLLMServer(OK[request.param]).start()
    keys(monkeypatch, base=srv.base_url)
    srv.provider, srv.model = request.param, MODEL[request.param]
    yield srv
    reset()
    srv.stop()


def ask(api, **kw):
    return llm.generate_json("SYSTEM TEXT", "PROMPT TEXT", SCHEMA, model=api.model, **kw)


# ── settings ────────────────────────────────────────────────────────────────
def test_every_provider_offers_three_latest_models_and_one_older_one():
    for p in C.PROVIDERS:
        models = [m for m in C.MODELS if m.provider == p]
        assert len(models) == 4 and "(older)" in models[-1].label and not any("(older)" in m.label for m in models[:3])
    assert len({m.label for m in C.MODELS}) == len(C.MODELS) and set(C.DEFAULT_MODELS) <= set(C.MODELS_BY_ID)


def test_only_the_providers_with_a_key_are_offered(monkeypatch):
    keys(monkeypatch, providers=[C.OPENAI])
    assert llm.available_models() == ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-luna"]
    assert client.is_configured() and client.default_model() == "gpt-6.1-sol"
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA, model="claude-sonnet-5-5")
    keys(monkeypatch, providers=[C.MISTRAL, C.GEMINI])
    assert {C.MODELS_BY_ID[m].provider for m in llm.available_models()} == {C.GEMINI, C.MISTRAL}
    assert client.default_model() == "gemini-3.8-flash"
    keys(monkeypatch)
    assert llm.available_models() == [m.id for m in C.MODELS] and client.default_model() == C.DEFAULT_MODELS[0]


def test_google_api_key_is_read_for_gemini(monkeypatch):
    keys(monkeypatch, providers=[])
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert llm.available_providers() == [C.GEMINI]


def test_nothing_is_offered_without_a_key(monkeypatch):
    keys(monkeypatch, providers=[])
    assert not llm.is_configured() and not client.is_configured() and client.available_models() == []
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA)


def test_an_unknown_model_is_a_setup_error(monkeypatch):
    keys(monkeypatch)
    with pytest.raises(AIConfigError):
        llm.generate_json("s", "p", SCHEMA, model="gpt-4")
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA, model="gpt-4")


# ── request shape ───────────────────────────────────────────────────────────
def test_every_request_goes_to_the_providers_api_with_its_key(api):
    assert ask(api, attachments=[Attachment("application/pdf", b"%PDF-1.4 data")]) == {"a": 1}
    req = api.requests[-1]
    assert req["path"].endswith(PATH[api.provider])
    key = "key-" + api.provider
    sent = {req["headers"].get("authorization"), req["headers"].get("x-api-key"), req["headers"].get("x-goog-api-key")}
    assert {"Bearer " + key, key} & sent, "the key goes in the header the provider's SDK uses"
    assert llm.last_usage() == 15


def test_openai_request_body(api):
    if api.provider != C.OPENAI:
        pytest.skip("OpenAI only")
    ask(api, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = api.requests[-1]["body"]
    assert body["model"] == api.model and body["instructions"] == "SYSTEM TEXT" and body["max_output_tokens"] == 777
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] and fmt["schema"]["additionalProperties"] is False
    parts = body["input"][0]["content"]
    assert parts[0]["type"] == "input_file" and parts[0]["file_data"].startswith("data:application/pdf;base64,")
    assert parts[-1] == {"type": "input_text", "text": "PROMPT TEXT"} and body["reasoning"] == {"effort": "low"}
    assert "temperature" not in body


def test_anthropic_request_body(api):
    if api.provider != C.ANTHROPIC:
        pytest.skip("Anthropic only")
    ask(api, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = api.requests[-1]["body"]
    assert body["model"] == api.model and body["max_tokens"] == 777 and body["system"] == "SYSTEM TEXT"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert "tool_choice" not in body and "temperature" not in body
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERg=="}}
    assert content[-1] == {"type": "text", "text": "PROMPT TEXT"}


def test_gemini_request_body(api):
    if api.provider != C.GEMINI:
        pytest.skip("Gemini only")
    ask(api, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = api.requests[-1]["body"]
    assert body["model"] == api.model and body["system_instruction"] == "SYSTEM TEXT"
    assert body["response_format"] == {"type": "text", "mime_type": "application/json", "schema": SCHEMA}
    assert body["generation_config"] == {"max_output_tokens": 777, "thinking_level": "low"}
    turn = body["input"][0]                                  # the SDK wraps the parts in one user turn
    content = turn["content"] if turn.get("type") == "user_input" else body["input"]
    assert content[0]["type"] == "document" and content[0]["mime_type"] == "application/pdf"
    assert content[-1] == {"type": "text", "text": "PROMPT TEXT"}


def test_mistral_request_body(api):
    if api.provider != C.MISTRAL:
        pytest.skip("Mistral only")
    ask(api, attachments=[Attachment("application/pdf", b"%PDF")], max_output_tokens=777)
    body = api.requests[-1]["body"]
    assert body["model"] == api.model and body["max_tokens"] == 777 and body["temperature"] == 0
    assert body["messages"] == [{"role": "system", "content": "SYSTEM TEXT"}, {"role": "user", "content": "PROMPT TEXT"}], \
        "PDF pages are not sent to Mistral; the extracted text is"
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["properties"] == SCHEMA["properties"]


def test_anthropic_tool_answers_are_read_too(api):
    if api.provider != C.ANTHROPIC:
        pytest.skip("Anthropic only")
    api.queue.append((200, anthropic_body(tool={"a": 2}, stop="tool_use")))
    assert ask(api) == {"a": 2}


def test_a_fenced_json_answer_is_accepted(api):
    fenced = '```json\n{"a": 2}\n```'
    api.queue.append((200, {C.OPENAI: openai_body, C.ANTHROPIC: anthropic_body, C.GEMINI: gemini_body,
                            C.MISTRAL: mistral_body}[api.provider](fenced)))
    assert ask(api) == {"a": 2}


# ── fallbacks ───────────────────────────────────────────────────────────────
REFUSALS = {C.OPENAI: ("Unsupported parameter: 'reasoning.effort' is not supported with this model.", "reasoning"),
            C.GEMINI: ("thinking_level is not supported for this model", "thinking"),
            C.ANTHROPIC: ("output_config.format: structured outputs are not supported for this model", "structured_output")}


def test_a_refused_optional_setting_is_dropped_and_remembered(api):
    if api.provider not in REFUSALS:
        pytest.skip("Mistral has no optional settings")
    message, option = REFUSALS[api.provider]
    api.queue.append((400, error_body(400, message)))
    assert ask(api) == {"a": 1} and len(api.requests) == 2 and not llm._accepts(api.model, option)
    first, second = api.requests[0]["body"], api.requests[1]["body"]
    assert first != second
    ask(api)
    assert api.requests[-1]["body"] == second, "remembered for later calls"


def test_anthropic_falls_back_to_a_forced_tool_and_then_to_plain_json(api):
    if api.provider != C.ANTHROPIC:
        pytest.skip("Anthropic only")
    api.queue += [(400, error_body(400, "output_config is not supported")),
                  (400, error_body(400, "tool_choice: forcing a tool is not supported")),
                  (200, anthropic_body('{"a": 3}'))]
    assert ask(api) == {"a": 3}
    tool_body, plain_body = api.requests[1]["body"], api.requests[2]["body"]
    assert tool_body["tool_choice"] == {"type": "tool", "name": "answer"} and tool_body["tools"][0]["input_schema"] == SCHEMA
    assert "tools" not in plain_body and "JSON object only" in plain_body["system"]


def test_a_refused_output_length_is_halved_and_remembered(api):
    api.queue.append((400, error_body(400, "max_tokens: 32768 > 16000, which is the maximum allowed number of output tokens")))
    assert ask(api, max_output_tokens=32768) == {"a": 1}
    assert llm._output_cap[api.model] == 16384
    ask(api, max_output_tokens=32768)
    assert len(api.requests) == 3


@pytest.mark.parametrize("status,message", [(413, "Request entity too large"),
                                            (400, "Input is too long for requested model."),
                                            (400, "The input token count (1200000) exceeds the maximum number of tokens allowed")])
def test_a_request_too_large_for_the_model_says_so(api, status, message):
    api.queue.append((status, error_body(status, message)))
    with pytest.raises(AIResponseError) as caught:
        ask(api)
    assert caught.value.too_long and len(api.requests) == 1


# ── errors ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status,message,headers,error", [
    (429, "Rate limit reached. Please try again in 12 seconds.", {}, AIRateLimitError),
    (429, "Too many requests", {"Retry-After": "7"}, AIRateLimitError),
    (429, "You exceeded your current quota, please check your plan and billing details.", {}, AIQuotaError),
    (401, "Incorrect API key provided", {}, AIConfigError),
    (403, "Permission denied", {}, AIConfigError),
    (404, "The model does not exist", {}, AIConfigError),
    (500, "Internal error", {}, AIServerError),
    (503, "The model is overloaded", {}, AIServerError),
    (400, "Request contains an invalid argument", {}, AIResponseError),
])
def test_http_errors_become_the_right_error(api, status, message, headers, error):
    api.queue.append((status, error_body(status, message), headers))
    with pytest.raises(error) as caught:
        ask(api)
    assert type(caught.value) is error
    assert len(api.requests) == 1, "the SDKs must not retry on their own; ai/ratelimit.py does"


def test_rate_limit_error_carries_the_advised_wait(api):
    api.queue.append((429, error_body(429, "Too many requests"), {"Retry-After": "37"}))
    with pytest.raises(AIRateLimitError) as caught:
        ask(api)
    assert caught.value.retry_after == 37.0


TRUNCATED = {C.OPENAI: openai_body('{"a": ', status="incomplete", reason="max_output_tokens"),
             C.ANTHROPIC: anthropic_body('{"a": ', stop="max_tokens"),
             C.GEMINI: gemini_body('{"a": ', status="incomplete"),
             C.MISTRAL: mistral_body('{"a": ', finish="length")}
EMPTY = {C.OPENAI: openai_body(""), C.ANTHROPIC: anthropic_body("", stop="refusal"), C.GEMINI: gemini_body(""),
         C.MISTRAL: mistral_body("")}


def test_a_cut_off_answer_is_marked_truncated(api):
    api.queue.append((200, TRUNCATED[api.provider]))
    with pytest.raises(AIResponseError) as caught:
        ask(api)
    assert caught.value.truncated


def test_an_empty_answer_is_an_error(api):
    api.queue.append((200, EMPTY[api.provider]))
    with pytest.raises(AIResponseError):
        ask(api)


def test_an_unreachable_api_is_a_temporary_error(monkeypatch):
    keys(monkeypatch, base=lambda p: "http://127.0.0.1:9/v1" if p == C.OPENAI else "http://127.0.0.1:9")
    for provider in C.PROVIDERS:
        reset()
        with pytest.raises(AIServerError):
            llm.generate_json("s", "p", SCHEMA, model=MODEL[provider])


def test_the_whole_path_through_the_client_uses_the_chosen_model(api):
    assert client.ask_json("s", "p", SCHEMA, model=api.model) == {"a": 1} and len(api.requests) == 1


def test_a_second_model_of_the_same_provider_uses_its_own_name(api):
    other = [m.id for m in C.MODELS if m.provider == api.provider and m.id != api.model][-1]
    llm.generate_json("s", "p", SCHEMA, model=other)
    body = api.requests[-1]["body"]
    assert body["model"] == other
