"""Shared fixtures. Every test runs with a fast rate limiter, a dummy key and an empty session store."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "docs" / "samples"

os.environ.setdefault("AI_REQUESTS_PER_MINUTE", "60000")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

from ai import client  # noqa: E402
from tests.fake_llm import FakeProvider  # noqa: E402
from utils import session  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("AI_REQUESTS_PER_MINUTE", "60000")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("AI_PARALLEL_CALLS", "2")
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    client._limiter = None
    session.clear_all()
    yield
    client._limiter = None
    session.clear_all()


@pytest.fixture
def fake_ai(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(client, "provider", lambda: provider)
    return provider


@pytest.fixture
def use_provider(monkeypatch):
    def apply(provider):
        monkeypatch.setattr(client, "provider", lambda: provider)
        return provider
    return apply


@pytest.fixture(scope="session")
def green_pdf() -> bytes:
    return (SAMPLES / "sample_budget_green_focus.pdf").read_bytes()


@pytest.fixture(scope="session")
def traditional_pdf() -> bytes:
    return (SAMPLES / "sample_budget_traditional.pdf").read_bytes()


@pytest.fixture(scope="session")
def project_docx() -> bytes:
    return (SAMPLES / "sample_project_budget.docx").read_bytes()


@pytest.fixture(scope="session")
def project_pdf() -> bytes:
    return (SAMPLES / "sample_project_budget.pdf").read_bytes()


def noop_progress(stage, detail=""):
    return None
