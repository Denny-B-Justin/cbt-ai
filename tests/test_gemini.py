"""ai/gemini.py against a local stand-in for the Gemini web API: request shape and error handling, no key or network needed."""

import json

import pytest

from ai import client, gemini
from ai.types import (AIConfigError, AIQuotaError, AIRateLimitError, AIResponseError, AIServerError, Attachment)
from tests.fake_gemini_server import FakeGeminiServer, error_body, ok_body

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


@pytest.fixture
def server(monkeypatch):
    srv = FakeGeminiServer('{"a": 1}').start()
    monkeypatch.setenv("GEMINI_BASE_URL", srv.url)
    monkeypatch.setenv("GEMINI_API_KEY", "key-123")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    gemini._client, gemini._client_key, gemini._thinking_ok = None, None, True
    yield srv
    srv.stop()
    gemini._client, gemini._client_key, gemini._thinking_ok = None, None, True


def ask(**kw):
    return gemini.generate_json("SYSTEM TEXT", "PROMPT TEXT", SCHEMA, **kw)


def test_request_carries_the_key_model_schema_and_attachments(server):
    assert ask(attachments=[Attachment("application/pdf", b"%PDF-1.4 data")], max_output_tokens=777) == {"a": 1}
    req = server.requests[-1]
    assert req["path"] == "/v1beta/models/gemini-3.6-flash:generateContent" and req["headers"]["x-goog-api-key"] == "key-123"
    body = req["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "SYSTEM TEXT"
    parts = body["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mime_type"] == "application/pdf" and parts[-1]["text"] == "PROMPT TEXT"
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"] == SCHEMA
    assert cfg["maxOutputTokens"] == 777 and cfg["temperature"] == 0.0


def test_model_comes_from_the_environment(server, monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    ask()
    assert "/models/gemini-custom:" in server.requests[-1]["path"]


def test_configuration_checks(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert not gemini.is_configured() and not client.is_configured()
    with pytest.raises(AIConfigError):
        client.ask_json("s", "p", SCHEMA)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert gemini.is_configured() and client.is_configured()


def test_unknown_provider_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "nonexistent")
    assert not client.is_configured()
    with pytest.raises(AIConfigError):
        client.provider()


def test_json_inside_code_fences_is_accepted(server):
    server.queue.append((200, ok_body('```json\n{"a": 2}\n```')))
    assert ask() == {"a": 2}


def test_thinking_setting_is_dropped_when_the_model_rejects_it(server):
    server.queue.append((400, error_body(400, "INVALID_ARGUMENT", "Thinking level is not supported by this model")))
    assert ask() == {"a": 1}
    assert "thinkingConfig" in server.requests[0]["body"]["generationConfig"]
    assert "thinkingConfig" not in server.requests[1]["body"]["generationConfig"]
    ask()
    assert "thinkingConfig" not in server.requests[-1]["body"]["generationConfig"], "remembered for later calls"


def test_thinking_can_be_turned_off(server, monkeypatch):
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "off")
    ask()
    assert "thinkingConfig" not in server.requests[-1]["body"]["generationConfig"]


RETRY = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]
DAILY = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
          "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]


@pytest.mark.parametrize("status,body,error", [
    (429, error_body(429, "RESOURCE_EXHAUSTED", "Quota exceeded for requests per minute", RETRY), AIRateLimitError),
    (429, error_body(429, "RESOURCE_EXHAUSTED", "Quota exceeded", DAILY), AIQuotaError),
    (401, error_body(401, "UNAUTHENTICATED", "Invalid credentials"), AIConfigError),
    (403, error_body(403, "PERMISSION_DENIED", "API key not valid"), AIConfigError),
    (404, error_body(404, "NOT_FOUND", "models/x is not found"), AIConfigError),
    (400, error_body(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."), AIConfigError),
    (500, error_body(500, "INTERNAL", "Internal error"), AIServerError),
    (503, error_body(503, "UNAVAILABLE", "The model is overloaded"), AIServerError),
    (400, error_body(400, "INVALID_ARGUMENT", "Request contains an invalid argument"), AIResponseError),
])
def test_http_errors_become_the_right_error(server, status, body, error):
    server.queue.append((status, body))
    with pytest.raises(error) as caught:
        ask()
    assert type(caught.value) is error


def test_rate_limit_error_carries_the_advised_wait(server):
    server.queue.append((429, error_body(429, "RESOURCE_EXHAUSTED", "Quota exceeded", RETRY)))
    with pytest.raises(AIRateLimitError) as caught:
        ask()
    assert caught.value.retry_after == 37.0


@pytest.mark.parametrize("payload,truncated,blocked", [
    (ok_body('{"a": ', finish="MAX_TOKENS"), True, False),
    (ok_body("", finish="SAFETY"), False, True),
    ({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}, False, True),
    (ok_body("not json at all"), False, False),
    (ok_body('{"a": [1, 2'), True, False),
])
def test_unusable_answers_say_why(server, payload, truncated, blocked):
    server.queue.append((200, payload))
    with pytest.raises(AIResponseError) as caught:
        ask()
    assert (caught.value.truncated, caught.value.blocked) == (truncated, blocked)


def test_every_error_has_a_message_fit_for_the_screen():
    for error in (AIConfigError, AIQuotaError, AIRateLimitError, AIServerError, AIResponseError):
        text = error().user_message
        assert text and not any(w in text.lower() for w in ("gemini", "api", "token", "json", "traceback"))


def test_the_whole_path_through_the_client_uses_the_server(server):
    assert client.ask_json("s", "p", SCHEMA) == {"a": 1} and len(server.requests) == 1
    assert json.dumps(server.requests[0]["body"]["generationConfig"]["responseJsonSchema"]) == json.dumps(SCHEMA)
