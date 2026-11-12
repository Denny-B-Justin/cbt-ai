"""A tiny local stand-in for the OpenAI, Anthropic, Gemini and Mistral APIs, enough to test ai/llm.py and the four
provider modules offline with the real SDKs. Point a provider at it with <PROVIDER>_BASE_URL (see base_url())."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


def openai_body(text: str, status: str = "completed", reason: str | None = None) -> dict[str, Any]:
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6.1-sol", "status": status,
            "incomplete_details": {"reason": reason} if reason else None, "parallel_tool_calls": False,
            "tool_choice": "auto", "tools": [], "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}


def anthropic_body(text: str = "", tool: Any = None, stop: str = "end_turn") -> dict[str, Any]:
    content = [{"type": "tool_use", "id": "toolu_1", "name": "answer", "input": tool}] if tool is not None \
        else ([{"type": "text", "text": text}] if text else [])
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}}


def gemini_body(text: str, status: str = "completed") -> dict[str, Any]:
    return {"id": "int_1", "status": status, "usage": {"total_tokens": 15},
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}] if text else []}


def mistral_body(text: str, finish: str = "stop") -> dict[str, Any]:
    return {"id": "cmpl_1", "object": "chat.completion", "model": "mistral-medium-latest", "created": 0,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def error_body(code: int, message: str) -> dict[str, Any]:
    """Every provider puts its message at error.message (Mistral also at the top level)."""
    return {"type": "error", "error": {"code": code, "type": "error", "message": message}, "message": message}


class FakeLLMServer:
    """queue: list of (http_status, json_body[, headers]). When empty, answers 200 with `default()`."""

    def __init__(self, default):
        self.queue: list[tuple] = []
        self.requests: list[dict[str, Any]] = []
        self.default = default
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                url = urlsplit(self.path)
                outer.requests.append({"path": url.path, "query": {k: v[0] for k, v in parse_qs(url.query).items()},
                                       "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                item = outer.queue.pop(0) if outer.queue else (200, outer.default())
                status, payload, headers = (item + ({},))[:3]
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # silence
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True)

    @property
    def root(self) -> str:
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def base_url(self, provider: str) -> str:
        """What <PROVIDER>_BASE_URL is set to: the openai SDK expects the /v1 in its base URL, the others add it."""
        return self.root + "/v1" if provider == "openai" else self.root

    def start(self) -> FakeLLMServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
