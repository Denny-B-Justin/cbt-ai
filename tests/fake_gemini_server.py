"""A tiny local server that speaks enough of the Gemini REST API to test ai/gemini.py without a key or network."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Tuple


def ok_body(text: str, finish: str = "STOP") -> Dict[str, Any]:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish, "index": 0}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
            "modelVersion": "fake"}


def error_body(code: int, status: str, message: str, details: list = None) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message, "status": status, "details": details or []}}


class FakeGeminiServer:
    """queue: list of (http_status, json_body). When empty, answers 200 with `default_text`."""

    def __init__(self, default_text: str = '{"ok": true}'):
        self.queue: List[Tuple[int, Dict[str, Any]]] = []
        self.requests: List[Dict[str, Any]] = []
        self.default_text = default_text
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, payload = outer.queue.pop(0) if outer.queue else (200, ok_body(outer.default_text))
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):  # silence
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True)

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def start(self) -> "FakeGeminiServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
