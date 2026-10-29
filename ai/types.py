"""Small types shared by every AI provider: attachments and errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Attachment:
    mime_type: str
    data: bytes


class Cancelled(Exception):
    """Raised inside a worker when the user left or cancelled."""


class AIError(Exception):
    user_message = "The analysis service had a problem. Please try again in a few minutes."


class AIConfigError(AIError):
    """Missing or invalid key, unknown model, or no permission. Retrying will not help."""
    user_message = "The analysis service is not set up correctly. Please contact the administrator."


class AIQuotaError(AIError):
    """The daily allowance is used up. Retrying will not help."""
    user_message = "The analysis service has reached its daily limit. Please try again later."


class AIRateLimitError(AIError):
    """Too many requests per minute. Wait and retry."""
    user_message = "The analysis service is busy right now. Please try again in a few minutes."

    def __init__(self, message: str = "", retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class AIServerError(AIError):
    """Temporary failure on the provider side or the network. Retry."""
    user_message = "The analysis service is temporarily unavailable. Please try again in a few minutes."


class AIResponseError(AIError):
    """The answer was empty, blocked, cut off or not valid JSON."""

    def __init__(self, message: str = "", truncated: bool = False, blocked: bool = False):
        super().__init__(message)
        self.truncated = truncated
        self.blocked = blocked


@dataclass
class DocInfo:
    """What the AI learned about a document from its first pages."""
    name: str = ""
    country: str = ""
    year: int = 0
    currency: str = ""
    unit: str = "units"
    document_type: str = ""

    @property
    def unit_text(self) -> str:
        words = {"thousands": "thousand", "millions": "million", "billions": "billion"}.get(self.unit, "")
        return " ".join(p for p in (words, self.currency) if p)
