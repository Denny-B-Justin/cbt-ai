"""Turn the raw lines found by the AI into one clean list of budget lines.

The same money can appear several times in a budget document (by programme, by function, by ministry, by
cost type, in totals). This module keeps one consistent view so amounts are never counted twice.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

KIND_PRIORITY = ["programme", "function", "ministry"]
KIND_NAMES = {"programme": "programme and project lines", "function": "lines by function",
              "ministry": "ministry-level lines"}
DROPPED_KINDS = {"category", "total"}
MIN_LINES_FOR_VIEW = 3
MAX_DESCRIPTION = 700
_NULLS = {"", "nan", "none", "null", "n/a", "na", "-", "--", "–", "—", "…"}


@dataclass
class Line:
    title: str
    code: str = ""
    ministry: str = ""
    description: str = ""
    function_code: str = ""
    amount: Optional[float] = None
    kind: str = "programme"
    page: int = 0
    order: int = 0

    @property
    def code_tokens(self) -> Tuple[str, ...]:
        """'05 01 00 00' and '05 01' are the same level of the code tree, so trailing zero parts are dropped."""
        tokens = [t for t in re.split(r"[^0-9A-Za-z]+", self.code.lower()) if t]
        while len(tokens) > 1 and set(tokens[-1]) == {"0"}:
            tokens.pop()
        return tuple(tokens)

    @property
    def specific_code(self) -> bool:
        """A code with at least four digits is treated as a real budget classification code."""
        return sum(ch.isdigit() for ch in self.code) >= 4


@dataclass
class Selection:
    lines: List[Line]
    stats: Dict[str, int] = field(default_factory=dict)
    issues: List[Dict[str, str]] = field(default_factory=list)


# ── amounts and text ────────────────────────────────────────────────────────
def parse_amount(raw: Any) -> Optional[float]:
    """'1,234.5', '1.234,5', '(500)', '-12', 1200 -> numbers; anything unreadable -> None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(float(raw)) else None
    s = str(raw).strip()
    if s.lower() in _NULLS:
        return None
    negative = (s.startswith("(") and s.rstrip().endswith(")")) or s[:1] in ("-", "−", "–")
    m = re.search(r"\d[\d.,\s  ']*", s)
    if not m:
        return None
    num = re.sub(r"[\s  ']", "", m.group(0)).rstrip(".,")
    if "," in num and "." in num:
        dec = "," if num.rfind(",") > num.rfind(".") else "."
        num = num.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in num:
        num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", num) else num.replace(",", ".")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    try:
        value = float(num)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return -value if negative else value


def _text(v: Any, limit: int = 400) -> str:
    s = " ".join(str(v or "").split())
    return "" if s.lower() in _NULLS else s[:limit]


def clean_records(records: List[Dict[str, Any]]) -> List[Line]:
    out: List[Line] = []
    for i, r in enumerate(records):
        title, desc = _text(r.get("title"), 300), _text(r.get("description"), MAX_DESCRIPTION)
        if not title and desc:
            title = desc[:80]
        if not title:
            continue
        kind = _text(r.get("kind")).lower()
        try:
            page = int(r.get("page") or 0)
        except (TypeError, ValueError):
            page = 0
        out.append(Line(title=title, code=_text(r.get("code"), 40), ministry=_text(r.get("ministry"), 200),
                        description=desc, function_code=_text(r.get("function_code"), 60),
                        amount=parse_amount(r.get("amount")),
                        kind=kind if kind in KIND_PRIORITY + list(DROPPED_KINDS) else "programme",
                        page=page, order=i))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-zÀ-￿]+", " ", s.lower()).strip()


# ── selecting one consistent view ───────────────────────────────────────────
def _merge_group(group: List[Line]) -> Line:
    best_kind = min((g.kind for g in group), key=lambda k: KIND_PRIORITY.index(k) if k in KIND_PRIORITY else 99)
    amounts = [g.amount for g in group if g.amount is not None]
    seen, desc = set(), []
    for g in group:
        d = g.description
        if d and _norm(d) not in seen:
            seen.add(_norm(d))
            desc.append(d)
    first = group[0]
    return Line(
        title=max((g.title for g in group), key=len), code=first.code,
        ministry=next((g.ministry for g in group if g.ministry), ""),
        description=" ".join(desc)[:MAX_DESCRIPTION],
        function_code=next((g.function_code for g in group if g.function_code), ""),
        amount=max(amounts, key=abs) if amounts else None, kind=best_kind,
        page=min((g.page for g in group if g.page), default=first.page), order=min(g.order for g in group))


def _merge_by_code(lines: List[Line]) -> Tuple[List[Line], int]:
    groups: Dict[Tuple[str, ...], List[Line]] = {}
    loose: List[Line] = []
    for ln in lines:
        (groups.setdefault(ln.code_tokens, []) if ln.specific_code else loose).append(ln)
    merged = [_merge_group(g) for g in groups.values()]
    return loose + merged, len(lines) - len(loose) - len(merged)


def _is_prefix(a: Tuple[str, ...], b: Tuple[str, ...]) -> bool:
    return len(a) < len(b) and b[:len(a)] == a


def _hierarchy(lines: List[Line]) -> Tuple[List[Line], int, int]:
    """Drop parent lines whose amount is the sum of coded children with amounts; fold description-only children
    into the nearest coded parent that has an amount."""
    coded = [ln for ln in lines if ln.specific_code]
    subtotals = {id(p) for p in coded if p.amount is not None and
                 any(_is_prefix(p.code_tokens, c.code_tokens) and c.amount is not None for c in coded)}
    keep_parents = [p for p in coded if p.amount is not None and id(p) not in subtotals]
    folded_ids: set = set()
    extra: Dict[int, List[str]] = {}
    for c in coded:
        if c.amount is not None or id(c) in subtotals:
            continue
        parents = [p for p in keep_parents if _is_prefix(p.code_tokens, c.code_tokens)]
        if parents:
            parent = max(parents, key=lambda p: len(p.code_tokens))
            note = c.title + (": " + c.description if c.description else "")
            extra.setdefault(id(parent), []).append(note)
            folded_ids.add(id(c))
    out: List[Line] = []
    for ln in lines:
        if id(ln) in subtotals or id(ln) in folded_ids:
            continue
        if id(ln) in extra:
            more = "Includes: " + "; ".join(extra[id(ln)])
            ln = replace(ln, description=(ln.description + " " + more).strip()[:MAX_DESCRIPTION])
        out.append(ln)
    return out, len(subtotals), len(folded_ids)


def _dedupe(lines: List[Line]) -> Tuple[List[Line], int]:
    seen, out = set(), []
    for ln in lines:
        key = (_norm(ln.title), _norm(ln.ministry), ln.amount) if not ln.specific_code else (ln.code_tokens,)
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return out, len(lines) - len(out)


def choose_view(lines: List[Line]) -> Tuple[List[Line], Optional[str]]:
    """Keep one kind of line. Programmes are preferred, then functions, then ministries."""
    counts = {k: sum(1 for ln in lines if ln.kind == k) for k in KIND_PRIORITY}
    chosen = next((k for k in KIND_PRIORITY if counts[k] >= MIN_LINES_FOR_VIEW), None)
    if chosen is None:
        chosen = max(KIND_PRIORITY, key=lambda k: (counts[k], -KIND_PRIORITY.index(k)))
    return [ln for ln in lines if ln.kind == chosen], chosen


def select_lines(records: List[Dict[str, Any]]) -> Selection:
    lines = clean_records(records)
    stats = {"found": len(lines)}
    kept = [ln for ln in lines if ln.kind not in DROPPED_KINDS]
    stats["totals_and_categories"] = len(lines) - len(kept)
    for ln in kept:                                   # money that is not a positive amount cannot be a share of the budget
        if ln.amount is not None and ln.amount < 0:
            ln.amount = None
            stats["negative_amounts"] = stats.get("negative_amounts", 0) + 1

    merged, n_merged = _merge_by_code(kept)
    merged.sort(key=lambda ln: ln.order)
    view, chosen = choose_view(merged)
    other_kinds = len(merged) - len(view)
    view, n_sub, n_fold = _hierarchy(view)
    view, n_dup = _dedupe(view)
    view.sort(key=lambda ln: (ln.page, ln.order))
    stats.update(merged_by_code=n_merged, other_views=other_kinds, subtotals=n_sub, folded=n_fold,
                 duplicates=n_dup, lines=len(view))

    issues: List[Dict[str, str]] = []
    if chosen and other_kinds >= MIN_LINES_FOR_VIEW:
        issues.append({"level": "info", "message":
                       "The document shows the budget in more than one way. To avoid counting the same money twice, "
                       "the results use the %s." % KIND_NAMES[chosen]})
    if stats.get("negative_amounts"):
        issues.append({"level": "info", "message":
                       "%d line(s) with negative amounts were left out of the amount-based shares." % stats["negative_amounts"]})
    return Selection(view, stats, issues)
