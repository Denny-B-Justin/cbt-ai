"""Try the real AI through the mAI gateway. Not part of the automated tests (they never call the network).

Run it on Posit Connect (for example from a Connect-hosted session): the gateway refuses local machines.

    python tests/live_check.py                  quick check: settings, one small call, reading and tagging a sample budget
    python tests/live_check.py --full           also run a complete analysis of the sample (or of --file)
    python tests/live_check.py --file my.pdf    use your own document for the reading and tagging steps
    python tests/live_check.py --model gemini-3.8-flash   use this model (default: the one the model picker pre-selects)
    python tests/live_check.py --every-model    first send one small call to every model that is set up
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

import constants as C                                              # noqa: E402
from ai import client, tasks                                       # noqa: E402
from ai.types import AIError                                       # noqa: E402
from tagging import pipeline                                       # noqa: E402
from utils import documents                                        # noqa: E402

SAMPLE = ROOT / "docs" / "samples" / "sample_budget_green_focus.pdf"
failures = []
MODEL = ""                                                         # set from --model in main()


def step(title: str):
    print("\n== %s" % title)
    return time.time()


def done(started: float, note: str = "") -> None:
    print("   ok  ({:.1f} s)  {}".format(time.time() - started, note))


def fail(message: str) -> None:
    failures.append(message)
    print("   FAILED  %s" % message)


def check_key() -> bool:
    t = step("mAI settings")
    if not client.is_configured():
        fail("Set %s and at least one of %s, and run this on Posit Connect (%s is missing otherwise)."
             % (C.ENV_MAI_BASE_URL, ", ".join(C.ENV_MAI_ENDPOINTS.values()), C.ENV_CONNECT_GUID))
        return False
    ready = client.available_models()
    for m in C.MODELS:
        print("   %-24s %s" % (m.label, "set up" if m.id in ready else "not set up (%s missing)" % C.ENV_MAI_ENDPOINTS[m.family]))
    if MODEL not in ready:
        fail("%s is not set up" % MODEL)
        return False
    done(t, "using %s" % client.model_label(MODEL))
    return True


def check_small_call(model: str = "") -> bool:
    model = model or MODEL
    t = step("One small call that must return JSON (%s)" % client.model_label(model))
    schema = {"type": "object", "properties": {"capital": {"type": "string"}}, "required": ["capital"]}
    try:
        data = client.ask_json("Answer with JSON only.", "What is the capital of France?", schema, max_output_tokens=256,
                               model=model)
    except AIError as exc:
        fail("{}: {}".format(type(exc).__name__, exc))
        return False
    ok = isinstance(data, dict) and "paris" in str(data.get("capital", "")).lower()
    done(t, repr(data)) if ok else fail("Unexpected answer: {!r}".format(data))
    return ok


def check_reading(path: Path):
    t = step("Reading the budget lines from %s" % path.name)
    try:
        doc = documents.read_document(path.read_bytes(), path.name)
        info = tasks.describe_document(doc, model=MODEL)
        result = tasks.extract_budget_lines(doc, info, lambda stage, detail="": None, model=MODEL)
    except (AIError, documents.DocumentError) as exc:
        fail("{}: {}".format(type(exc).__name__, exc))
        return None
    done(t, "%d page(s), %d record(s), %d section(s)" % (doc.n_pages, len(result.records), result.sections))
    print("   document: {} | {} | {} | {} {}".format(info.name, info.country, info.year, info.currency, info.unit))
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
        verdicts = tasks.tag_budget_lines(items, lambda stage, detail="": None, model=MODEL)
    except AIError as exc:
        fail("{}: {}".format(type(exc).__name__, exc))
        return
    done(t, "%d of %d lines tagged" % (len(verdicts), len(items)))
    print("   %-38s %4s %5s  %-14s %s" % ("line", "code", "level", "sector", "why"))
    for it in items:
        v = verdicts.get(it["id"])
        if v is None:
            print("   %-38s  (no verdict)" % it["title"][:38])
            continue
        code = "CB" if v.mitigation and v.adaptation else "CM" if v.mitigation else "CA" if v.adaptation else "-"
        print("   %-38s %4s %5s  %-14s %s" % (it["title"][:38], code, v.level or "-", v.sector[:14], v.rationale[:60]))
    if len(verdicts) < len(items):
        fail("%d line(s) came back without a verdict" % (len(items) - len(verdicts)))


def check_full(path: Path) -> None:
    t = step("Complete analysis of %s" % path.name)
    try:
        a = pipeline.analyse_document(path.read_bytes(), path.name, lambda stage, detail="": print("   ... {} {}".format(stage, detail), end="\r"),
                                      model=MODEL)
        print()
        b = pipeline.analyse_document((ROOT / "docs" / "samples" / "sample_budget_traditional.pdf").read_bytes(), "traditional.pdf",
                                      lambda stage, detail="": None, model=MODEL) if path == SAMPLE else a
        comparison = pipeline.compare_budgets(a, b)
    except (pipeline.AnalysisError, AIError) as exc:
        fail("{}: {}".format(type(exc).__name__, exc))
        return
    s = a.summary
    done(t, "%d lines, %d climate-tagged (CM %d, CA %d, CB %d)" % (a.stats["lines"], s["tagged_lines"], s["code_lines"]["CM"],
                                                                 s["code_lines"]["CA"], s["code_lines"]["CB"]))
    print("   climate share {:.1f}% | mitigation {:.1f}% | adaptation {:.1f}%".format(
        100 * (s["climate_share"] or 0), 100 * (s["mitigation_share"] or 0), 100 * (s["adaptation_share"] or 0)))
    print("   climate spend by level: " + " | ".join("{} {:.0f}%".format(lv, 100 * (s["level_of_climate"][lv] or 0)) for lv in (100, 70, 40, 20)))
    for issue in a.issues:
        print("   note: %s" % issue["message"])
    print("   scores A/B: {} / {}  (numbers alone: {} / {})".format(
        comparison.scores["A"], comparison.scores["B"], comparison.rubric["A"]["score"], comparison.rubric["B"]["score"]))
    print("   %s" % comparison.summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="run a complete analysis and a comparison")
    parser.add_argument("--file", type=Path, default=SAMPLE, help="a PDF, Word or Excel budget (default: the climate-focused sample)")
    parser.add_argument("--model", choices=[m.id for m in C.MODELS], help="the model to use (default: the pre-selected one)")
    parser.add_argument("--every-model", action="store_true", help="first send one small call to every model that is set up")
    parser.add_argument("--fake", action="store_true", help="use the built-in stand-in instead of the real service")
    args = parser.parse_args()

    if args.fake:
        from tests.fake_llm import FakeProvider
        fake = FakeProvider()
        client.provider = lambda: fake
        print("Using the stand-in AI: this only checks this script.")
    global MODEL
    MODEL = args.model or client.default_model()
    if not args.fake and not check_key():
        return 1
    if args.every_model and not args.fake:
        for model in client.available_models():
            check_small_call(model)

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
