"""Try the real AI with your own key. Not part of the automated tests (they never call the network).

    python tests/live_check.py                  quick check: key, one small call, reading and tagging a sample budget
    python tests/live_check.py --full           also run a complete analysis of the sample (or of --file)
    python tests/live_check.py --file my.pdf    use your own document for the reading and tagging steps
    python tests/live_check.py --fake           run this script against the built-in stand-in (checks the script itself)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from ai import client, tasks                                       # noqa: E402
from ai.types import AIError                                       # noqa: E402
from tagging import pipeline                                       # noqa: E402
from utils import documents                                        # noqa: E402

SAMPLE = ROOT / "docs" / "samples" / "sample_budget_green_focus.pdf"
failures = []


def step(title: str):
    print("\n== %s" % title)
    return time.time()


def done(started: float, note: str = "") -> None:
    print("   ok  (%.1f s)  %s" % (time.time() - started, note))


def fail(message: str) -> None:
    failures.append(message)
    print("   FAILED  %s" % message)


def check_key() -> bool:
    t = step("API key")
    if not client.is_configured():
        fail("No key found. Copy .env.sample to .env and set GEMINI_API_KEY.")
        return False
    prov = client.provider()
    done(t, "provider=%s model=%s" % (prov.__name__.split(".")[-1], prov.model_name()))
    return True


def check_small_call() -> bool:
    t = step("One small call that must return JSON")
    schema = {"type": "object", "properties": {"capital": {"type": "string"}}, "required": ["capital"]}
    try:
        data = client.ask_json("Answer with JSON only.", "What is the capital of France?", schema, max_output_tokens=256)
    except AIError as exc:
        fail("%s: %s" % (type(exc).__name__, exc))
        return False
    ok = isinstance(data, dict) and "paris" in str(data.get("capital", "")).lower()
    done(t, repr(data)) if ok else fail("Unexpected answer: %r" % (data,))
    return ok


def check_reading(path: Path):
    t = step("Reading the budget lines from %s" % path.name)
    try:
        doc = documents.read_document(path.read_bytes(), path.name)
        info = tasks.describe_document(doc)
        result = tasks.extract_budget_lines(doc, info, lambda stage, detail="": None)
    except (AIError, documents.DocumentError) as exc:
        fail("%s: %s" % (type(exc).__name__, exc))
        return None
    done(t, "%d page(s), %d record(s), %d section(s)" % (doc.n_pages, len(result.records), result.sections))
    print("   document: %s | %s | %s | %s %s" % (info.name, info.country, info.year, info.currency, info.unit))
    for r in result.records[:8]:
        print("   - %-40s %12s  [%s]" % (str(r.get("title"))[:40], r.get("amount"), r.get("kind")))
    if not result.records:
        fail("No budget lines were found")
        return None
    return result


def check_tagging(result) -> None:
    t = step("Tagging the first lines")
    items = [{"id": i, "title": r.get("title", ""), "ministry": r.get("ministry", ""), "description": r.get("description", ""),
              "function_code": r.get("function_code", "")}
             for i, r in enumerate([r for r in result.records if r.get("kind") != "total"][:15], start=1)]
    try:
        verdicts = tasks.tag_budget_lines(items, lambda stage, detail="": None)
    except AIError as exc:
        fail("%s: %s" % (type(exc).__name__, exc))
        return
    done(t, "%d of %d lines tagged" % (len(verdicts), len(items)))
    print("   %-38s %4s %4s  %-12s %s" % ("line", "mit", "adp", "EU", "why"))
    for it in items:
        v = verdicts.get(it["id"])
        if v is None:
            print("   %-38s  (no verdict)" % it["title"][:38])
            continue
        eu = "brown" if v.brown else ",".join(v.eu_objectives) or ("admin" if v.administrative else "-")
        print("   %-38s %4d %4d  %-12s %s" % (it["title"][:38], v.rio_mitigation, v.rio_adaptation, eu[:12], v.rationale[:60]))
    if len(verdicts) < len(items):
        fail("%d line(s) came back without a verdict" % (len(items) - len(verdicts)))


def check_full(path: Path) -> None:
    t = step("Complete analysis of %s" % path.name)
    try:
        a = pipeline.analyse_document(path.read_bytes(), path.name, lambda stage, detail="": print("   ... %s %s" % (stage, detail), end="\r"))
        print()
        b = pipeline.analyse_document((ROOT / "docs" / "samples" / "sample_budget_traditional.pdf").read_bytes(), "traditional.pdf",
                                      lambda stage, detail="": None) if path == SAMPLE else a
        comparison = pipeline.compare_budgets(a, b)
    except (pipeline.AnalysisError, AIError) as exc:
        fail("%s: %s" % (type(exc).__name__, exc))
        return
    done(t, "%d lines, %s" % (a.stats["lines"], a.stats["rio_methods"]))
    r, e = a.rio_summary, a.eu_summary
    print("   Rio weighted share %.1f%% | principal %.1f%% | significant %.1f%%" % (
        100 * (r["weighted_share"] or 0), 100 * (r["principal_share"] or 0), 100 * (r["significant_share"] or 0)))
    print("   EU green %.1f%% | brown %.1f%%" % (100 * (e["green_share"] or 0), 100 * (e["brown_share"] or 0)))
    for issue in a.issues:
        print("   note: %s" % issue["message"])
    print("   scores A/B: %s / %s  (numbers alone: %s / %s)" % (
        comparison.scores["A"], comparison.scores["B"], comparison.rubric["A"]["score"], comparison.rubric["B"]["score"]))
    print("   %s" % comparison.summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="run a complete analysis and a comparison")
    parser.add_argument("--file", type=Path, default=SAMPLE, help="a PDF or Word budget (default: the green sample)")
    parser.add_argument("--fake", action="store_true", help="use the built-in stand-in instead of the real service")
    args = parser.parse_args()

    if args.fake:
        from tests.fake_llm import FakeProvider
        fake = FakeProvider()
        client.provider = lambda: fake
        print("Using the stand-in AI: this only checks this script.")
    elif not check_key():
        return 1

    if args.fake or check_small_call():
        result = check_reading(args.file)
        if result:
            check_tagging(result)
        if args.full:
            check_full(args.file)
    print("\n" + ("All checks passed." if not failures else "%d check(s) failed:\n - %s" % (len(failures), "\n - ".join(failures))))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
