"""JSON shapes the AI must answer in, plus a tolerant JSON loader."""

from __future__ import annotations

import json
import re
from typing import Any

from utils import constants as C

from .types import AIResponseError

LINE_KINDS = ["programme", "function", "ministry", "category", "total"]

DESCRIBE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "country": {"type": "string"}, "year": {"type": "integer"},
        "currency": {"type": "string"}, "unit": {"type": "string", "enum": ["units", "thousands", "millions", "billions"]},
        "document_type": {"type": "string"},
    },
    "required": ["name", "country", "year", "currency", "unit", "document_type"],
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"lines": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "code": {"type": "string"}, "ministry": {"type": "string"}, "title": {"type": "string"},
            "description": {"type": "string"}, "function_code": {"type": "string"}, "amount": {"type": "string"},
            "kind": {"type": "string", "enum": LINE_KINDS}, "page": {"type": "integer"},
        },
        "required": ["code", "ministry", "title", "description", "function_code", "amount", "kind", "page"],
    }}},
    "required": ["lines"],
}

TAG_SCHEMA = {
    "type": "object",
    "properties": {"tags": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "rio_mitigation": {"type": "integer"}, "rio_adaptation": {"type": "integer"},
            "eu_objectives": {"type": "array", "items": {"type": "string", "enum": C.EU_OBJECTIVES}},
            "brown": {"type": "boolean"}, "administrative": {"type": "boolean"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "rationale": {"type": "string"},
        },
        "required": ["id", "rio_mitigation", "rio_adaptation", "eu_objectives", "brown", "administrative",
                     "confidence", "rationale"],
    }}},
    "required": ["tags"],
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "budgets": {"type": "array", "items": {
            "type": "object",
            "properties": {"label": {"type": "string", "enum": ["A", "B"]}, "score": {"type": "integer"},
                           "reason": {"type": "string"}},
            "required": ["label", "score", "reason"]}},
        "summary": {"type": "string"},
    },
    "required": ["budgets", "summary"],
}


def load_json(text: str) -> Any:
    """Parse the model's answer, tolerating code fences and stray text around the JSON."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        pass
    opens = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    start, end = (min(opens) if opens else -1), max(text.rfind("}"), text.rfind("]"))
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    raise AIResponseError("The answer was not valid JSON", truncated=text.count("{") > text.count("}"))
