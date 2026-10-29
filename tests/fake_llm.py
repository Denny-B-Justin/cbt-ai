"""A stand-in for the AI provider, used by the tests. It follows the same interface as ai/gemini.py."""

from __future__ import annotations

import re
import threading
import time
from typing import Any, List, Sequence

from ai.types import Attachment
from tagging.eu_tagger import EUTaxonomyTagger
from tagging.models import LineText
from tagging.rio_tagger import RioMarkerTagger
from utils import constants as C

_NUM = re.compile(r"(\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?)\s*$")


class FakeProvider:
    """Reads 'Title ... 1,234.5' lines as budget lines and tags them with the keyword taggers."""

    def __init__(self, fail_first: int = 0, error: Exception = None, delay: float = 0.0):
        self.delay = delay
        self.calls: List[dict] = []
        self.lock = threading.Lock()
        self.fail_first = fail_first
        self.error = error
        self.rio, self.eu = RioMarkerTagger(), EUTaxonomyTagger()

    # provider interface
    def is_configured(self) -> bool:
        return True

    def model_name(self) -> str:
        return "fake"

    def generate_json(self, system: str, prompt: str, schema: dict, attachments: Sequence[Attachment] = (),
                      max_output_tokens: int = 0, temperature: float = 0.0) -> Any:
        with self.lock:
            self.calls.append({"system": system, "prompt": prompt, "attachments": len(attachments), "schema": schema})
            n = len(self.calls)
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None and n <= self.fail_first:
            raise self.error
        if "tags" in schema["properties"]:
            return self._tag(prompt)
        if "lines" in schema["properties"]:
            return self._extract(prompt)
        if "budgets" in schema["properties"]:
            return self._score(prompt)
        return {"name": "Sample Budget 2025", "country": "Testland", "year": 2025, "currency": "TST", "unit": "units",
                "document_type": "national budget"}

    def _extract(self, prompt: str) -> dict:
        body = prompt.split("<document>", 1)[1].rsplit("</document>", 1)[0]
        page, ministry, out = 1, "", []
        for raw in body.splitlines():
            line = raw.strip()
            m = re.match(r"\[Page (\d+)\]", line)
            if m:
                page = int(m.group(1))
                continue
            if line.lower().startswith("ministry of") and not _NUM.search(line):
                ministry = line
                continue
            m = _NUM.search(line)
            if m and " | " in line:
                cells = [c.strip() for c in line[:m.start()].split(" | ") if c.strip()]
                code = cells.pop(0) if len(cells) > 2 and re.fullmatch(r"[A-Z]?\d{1,4}", cells[0]) else ""
                if cells and cells[0].lower() not in ("code", "programme", "component"):
                    kind = "total" if cells[0].lower().startswith("total") else "programme"
                    out.append({"code": code, "ministry": ministry, "title": cells[0], "description": " ".join(cells[1:]),
                                "function_code": "", "amount": m.group(1), "kind": kind, "page": page})
                continue
            if m and len(line) > len(m.group(1)) + 3:
                title = re.sub(r"[|\s]+$", "", line[:m.start()]).strip(" |")
                if title.lower().startswith("total"):
                    out.append({"code": "", "ministry": "", "title": title, "description": "", "function_code": "",
                                "amount": m.group(1), "kind": "total", "page": page})
                else:
                    out.append({"code": "", "ministry": ministry, "title": title, "description": "", "function_code": "",
                                "amount": m.group(1), "kind": "programme", "page": page})
        return {"lines": out}

    def _tag(self, prompt: str) -> dict:
        body = prompt.split("<document>", 1)[1].rsplit("</document>", 1)[0]
        tags = []
        for raw in body.splitlines():
            m = re.match(r"\[(\d+)\] Title: (.*)", raw)
            if not m:
                continue
            parts = {p.split(": ", 1)[0]: p.split(": ", 1)[1] for p in m.group(2).split(" | ") if ": " in p}
            text = LineText(("Title: " + m.group(2)).split(" | ")[0][7:], parts.get("Description", ""), parts.get("Ministry", ""))
            rio, eu = self.rio.tag(text), self.eu.tag(text)
            admin = rio.method.endswith("EXCLUSION")
            tags.append({"id": int(m.group(1)), "rio_mitigation": 0 if admin else rio.mitigation,
                         "rio_adaptation": 0 if admin else rio.adaptation,
                         "eu_objectives": [] if admin or eu.tag != C.TAG_GREEN else [k for k in C.EU_OBJECTIVES if eu.objectives[k]],
                         "brown": eu.tag == C.TAG_BROWN, "administrative": admin, "confidence": "high",
                         "rationale": "Fake verdict for testing."})
        return {"tags": tags}

    def _score(self, prompt: str) -> dict:
        out = []
        for label, share in re.findall(r"Budget ([AB]):.*?climate-weighted share: ([\d.]+)%", prompt, re.S):
            out.append({"label": label, "score": min(100, int(float(share) * 4)), "reason": "Fake score reason."})
        return {"budgets": out, "summary": "Fake summary."}
