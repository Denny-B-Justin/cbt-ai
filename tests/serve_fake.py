"""Starts the app with a stand-in AI, so every screen can be tried without a key or a network."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AI_REQUESTS_PER_MINUTE", "6000")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from ai import client  # noqa: E402
from tests.fake_llm import FakeProvider  # noqa: E402

FAKE = FakeProvider(delay=float(os.getenv("FAKE_DELAY", "0")))
client.provider = lambda: FAKE

import app  # noqa: E402

if __name__ == "__main__":
    app.app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8050")), debug=False)
