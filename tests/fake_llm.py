"""A stand-in for the AI provider, used by the tests. It follows the same interface as ai/mai_llm.py."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Sequence
from typing import Any

from ai.types import Attachment

MITIGATION = ("solar", "wind", "insulation", "efficien", "reforestation", "planting trees", "electric", "renewable",
              "methane", "recycling", "composting")
ADAPTATION = ("flood", "drought", "early warning", "sea wall", "sea-level", "storm", "cyclone", "mangrove", "wetland",
              "disaster", "resilien")
STRONG = ("solar", "wind", "insulation", "reforestation", "electric", "flood", "drought", "early warning", "sea wall",
          "mangrove", "cyclone")
LIVEABLE = ("liveable", "livable", "habitable")
SERVICE = ("salaries", "pensions", "administration", "office", "project management")
SECTOR_WORDS = {"solar": "Energy", "wind": "Energy", "insulation": "Building", "efficien": "Building", "electric": "Transport",
                "reforestation": "Forest", "trees": "Forest", "flood": "Water", "drought": "Agriculture", "irrigation": "Agriculture",
                "recycling": "Waste", "composting": "Waste", "sea": "Coastal resorts", "mangrove": "Coastal resorts", "storm": "Water"}

_NUM = re.compile(r"(\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?)\s*$")


class FakeProvider:
    """Reads 'Title ... 1,234.5' lines as budget lines and answers the guiding questions from a few climate words."""

    def __init__(self, fail_first: int = 0, error: Exception = None, delay: float = 0.0):
        self.delay = delay
        self.calls: list[dict] = []
        self.lock = threading.Lock()
        self.fail_first = fail_first
        self.error = error

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
        body = re.sub(r"<sheet_headings[^>]*>.*?</sheet_headings>", "", body, flags=re.S)   # reference rows, not data
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

    @staticmethod
    def _lines(prompt: str):
        """(id, title, description) of every line in a tagging prompt."""
        body = prompt.split("<document>", 1)[1].rsplit("</document>", 1)[0]
        for raw in body.splitlines():
            m = re.match(r"\[(\d+)\] Title: (.*)", raw)
            if m:
                title, *rest = m.group(2).split(" | ")
                parts = {p.split(": ", 1)[0]: p.split(": ", 1)[1] for p in rest if ": " in p}
                yield int(m.group(1)), title.lower(), parts.get("Description", "").lower()

    def _tag(self, prompt: str) -> dict:
        """Answers the four guiding questions from a few words, the way the handbook examples read."""
        tags = []
        for line_id, title, description in self._lines(prompt):
            text = title + " " + description
            mit = [w for w in MITIGATION if w in text]
            ada = [w for w in ADAPTATION if w in text]
            floor = any(w in text for w in LIVEABLE)
            service = not (mit or ada or floor) and any(w in text for w in SERVICE)
            strong = [w for w in mit + ada if w in STRONG]
            level = 100 if any(w in title for w in strong) else 70 if strong else 40 if mit or ada else 20 if floor else 0
            sector = next((v for k, v in SECTOR_WORDS.items() if k in text), "Cross-cutting") if mit or ada or floor else "None"
            tags.append({"id": line_id, "q1_ghg_related": bool(mit), "q2_mitigation_measure": bool(mit),
                         "q3_climate_hazard_related": bool(ada), "q4_adaptation_measure": bool(ada), "sector": sector,
                         "function": "Environmental protection" if mit or ada else "Not known", "climate_level": level,
                         "livability_floor": floor, "service_oriented": service, "confidence": "high",
                         "rationale": "Fake verdict for testing."})
        return {"tags": tags}

    def _score(self, prompt: str) -> dict:
        out = []
        for label, share in re.findall(r"Budget ([AB]):.*?climate share: ([\d.]+)%", prompt, re.S):
            out.append({"label": label, "score": min(100, int(float(share) * 4)), "reason": "Fake score reason."})
        return {"budgets": out, "summary": "Fake summary."}
