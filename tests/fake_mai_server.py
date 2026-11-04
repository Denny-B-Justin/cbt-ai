"""A tiny local stand-in for the Posit mAI Gateway, enough to test ai/mai_llm.py for GPT, Gemini and Claude offline."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit


def gpt_body(text: str, status: str = "completed", reason: str | None = None) -> dict[str, Any]:
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6-luna", "status": status,
            "incomplete_details": {"reason": reason} if reason else None, "parallel_tool_calls": False,
            "tool_choice": "auto", "tools": [],
            "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}]}


def gemini_body(text: str, status: str = "completed") -> dict[str, Any]:
    return {"id": "int_1", "status": status, "usage": {"total_tokens": 15},
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}] if text else []}


def claude_body(data: Any = None, text: str = "", stop: str = "tool_use") -> dict[str, Any]:
    content = [{"toolUse": {"toolUseId": "t1", "name": "answer", "input": data}}] if data is not None else [{"text": text}]
    return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": stop,
            "usage": {"inputTokens": 10, "outputTokens": 5}}


def error_body(code: int, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


class FakeMaiServer:
    """queue: list of (http_status, json_body[, headers]). When empty, answers 200 with `default()`."""

    PREFIX = "/posit-mai/conversationalai/"

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
    def url(self) -> str:
        return "http://127.0.0.1:%d%s" % (self.httpd.server_address[1], self.PREFIX)

    def start(self) -> FakeMaiServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
