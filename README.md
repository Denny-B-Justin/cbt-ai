# Climate Budget Tagging Tool (AI edition)

A Plotly Dash application that reads a government budget document (PDF, Word or Excel), has an LLM extract and tag every
budget line against three taxonomies (**Rio Markers**, **EU Taxonomy** and the **Georgian Taxonomy** of the
CBT Handbook for Georgia), computes all shares and charts deterministically
in code, and can score and compare two budgets.

It succeeds the rule-based `wb-climate-budget-tagging` app (Excel/CSV in, keyword matching, Databricks storage). What changed:

| | Previous version | This version |
|---|---|---|
| Input | Structured Excel/CSV | PDF, Word or Excel, any layout |
| Reading the budget | Column mapping | LLM extracts budget lines from text and table pages |
| Tagging | Keyword counts | LLM judgement per line, keyword taggers kept as a second opinion |
| Storage | Databricks | None. Memory only, per visitor, deleted when the page closes |
| Pages | Several | Home, **Evaluate Budget**, **Compare Budget**, Methodology |

The model is **only asked for judgements** (what the lines are, which tag fits, how a budget compares). Every sum, share,
chart value and table is computed in Python from those judgements.

> **Demo scope.** There is no database, no file storage and no accounts. State lives in the memory of one server process.
> See [docs/sessions-and-privacy.md](docs/sessions-and-privacy.md) for what that implies, including what leaves the server.

---

## Quick start

Python 3.12 (targets 3.12.12, the version pinned in `manifest.json`).

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                           # http://127.0.0.1:8050
```

> **The AI works only on Posit Connect.** Locally the app starts, but analyses report that the service is not set up.
> To try the whole interface on your own machine, use the scripted stand-in below.

Check the real model once the app is deployed (run on Posit Connect):

```bash
python tests/live_check.py            # settings, one small call, reading + tagging a sample budget
python tests/live_check.py --full     # also a complete analysis and a two-budget comparison
```

Try the whole interface locally without the AI (uses a scripted stand-in for the model):

```bash
python tests/serve_fake.py            # PORT=8051 python tests/serve_fake.py for another port
```

Production (see [docs/deployment.md](docs/deployment.md) for why exactly one worker):

```bash
gunicorn app:server --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:8050
```

## Configuration

### AI settings

Set these in Posit Connect under **Settings → Runtime → Environment Variables**. No keys or tokens are needed.

| Variable | Required | Meaning |
|---|---|---|
| `MAI_BASE_URL` | yes | Gateway URL for the environment (QA or Production), ending in `/`. |
| `MAI_ENDPOINT` | yes | mAI endpoint of the model provider (OpenAI, Claude or Gemini). |
| `MAI_MODEL` | no | Model to use, for example `gpt-6-luna`, `claude-haiku-5-5` or `gemini-3.8-flash`. It must belong to the same provider as `MAI_ENDPOINT`. If it is not set, the provider's default model is used. |

**Note:** this works only when the app runs on Posit Connect. It does not work on a local machine.

### Optional app settings

All have sensible defaults; a `.env` file is read if present (see `.env.sample`).

| Variable | Default | Meaning |
|---|---|---|
| `AI_REQUESTS_PER_MINUTE` | `3500` | Global pacing across all visitors: calls per minute. |
| `AI_TOKENS_PER_MINUTE` | `35000` | Global token budget per minute across all visitors (`0` switches it off). Usually the tighter of the two. |
| `AI_PARALLEL_CALLS` | `3` | Worker threads per analysis for the reading step. |
| `MAX_UPLOAD_MB` | `50` | Per-file limit. The browser refuses files above 3× this before sending. |
| `SESSION_IDLE_MINUTES` | `15` | A visitor with no heartbeat for this long is forgotten. |
| `MAX_RUNNING_ANALYSES` | `8` | Concurrent analyses; further starts get a "busy" message. |
| `PORT` | `8050` | Used by `python app.py`. |
| `LOG_LEVEL` | `INFO` | Python logging level. |

## How an analysis runs

```
browser ──upload (base64)──▶ dcc.Upload callback ──▶ session.start_job(sid, slot, work)   (background thread)
   ▲                                                         │
   │  dcc.Interval (1 s) ─▶ show_job ─▶ loader / results     ▼
   │                                              pipeline.analyse_document
   │                                                1. documents.read_document     PyMuPDF / python-docx → pages, table + scan flags
   │                                                2. tasks.describe_document     LLM: name, country, year, currency, unit
   │                                                3. tasks.extract_budget_lines  LLM, sections in parallel → raw records
   │                                                4. lines.select_lines          clean, de-duplicate, avoid double counting
   │                                                5. tasks.tag_budget_lines      LLM, batches of 60 → one verdict per distinct line
   │                                                5b. tasks.tag_budget_lines_georgia  own prompt, same batches → CM/CA/CB + level
   │                                                6. reconcile + metrics         verdict + keyword check → tags; shares in pandas
   └────────────── charts, tables, .xlsx ◀────────  Analysis(rio, eu, summaries, issues)
```

Compare Budget runs steps 1–6 for budget A, then B, then `pipeline.compare_budgets` (step 7: one LLM call that scores both).
The two tabs share no state; each owns a "slot" (`evaluate`, `compare`) in the visitor's session.

## Repository layout

```
app.py                 Dash app, layout, routing, session beacon routes
assets/                CSS, session.js (heartbeat + pagehide beacon), logo, favicon, fonts, hero art
ai/                    everything that talks to a model
  client.py            provider lookup, pacing, retries (provider-neutral)
  ratelimit.py         RateLimiter (requests and tokens per minute, adaptive) + call_with_retries
  types.py             Attachment, DocInfo, error taxonomy, Cancelled
  mai_llm.py           the model provider: GPT, Claude or Gemini through mAI, picked by MAI_MODEL
  schemas.py           JSON schemas for the four tasks + tolerant JSON loading
  prompt.py            all prompts
  tasks.py             describe / extract / tag / score: the four jobs, with splitting and second passes
tagging/               everything that decides or computes
  lines.py             record cleaning, merging, hierarchy and double-counting rules
  rio_tagger.py        keyword tagger (Rio Markers)         ┐ ported from the previous version,
  eu_tagger.py         keyword tagger (EU Taxonomy)         │ used as a second opinion only
  keywords.py, cofog.py, matcher.py                         ┘
  reconcile.py         verdict + second opinion → final tag, confidence, "decided by"
  georgia.py           Georgian Taxonomy: line rows (level × amount, CB split 50/50) and every number its charts use
  metrics.py           shares, summaries, fallback scoring rubric
  pipeline.py          analyse_document, compare_budgets, Analysis dataclass
utils/                 one module per page plus shared helpers
  home.py, evaluate.py, compare.py, methodology.py   pages and their callbacks
  components.py, charts.py, export.py, formatting.py presentation helpers
  documents.py         PDF/DOCX reading and chunking
  session.py           in-memory sessions, uploads and background jobs
  constants.py         names, labels, colours, limits, env var names
docs/                  developer documentation + samples/ (fictional test documents)
tests/                 pytest suite, stand-in model, fake mAI gateway, live smoke test
```

## What the model does, and what it does not

| Step | Model decides | Code decides |
|---|---|---|
| Describe | name, country, year, currency, unit | fallbacks when absent or odd |
| Extract | which text rows are budget lines; amount, kind (programme / function / ministry / category / total), page | amount parsing, dropping totals, merging, hierarchy, duplicates, negative amounts |
| Tag | Rio mitigation 0–2, adaptation 0–2, EU objectives, brown, administrative, confidence, one-line reason | normalisation to a consistent verdict; final tag via `reconcile` |
| Tag (Georgian) | the four guiding questions, level class, sector, function, service cost, liveable wording | level snapped to 20/40/70/100 for tagged lines (0 otherwise); CB split; climate amounts |
| Score | 0–100 and a sentence per budget, a two-sentence comparison | clamping to ±15 of the fixed rubric (`SCORE_GUARD`) |
| Everything else | – | all sums, shares, charts, tables, Excel files |

Details: [docs/ai-layer.md](docs/ai-layer.md), [docs/tagging-logic.md](docs/tagging-logic.md), [docs/scoring.md](docs/scoring.md).

## Testing

```bash
pip install -r requirements-dev.txt && playwright install chromium
pytest                       # everything (about 90 seconds; the browser tests are most of it)
pytest -m "not ui"           # skip the headless-browser tests (about 10 seconds)
```

No test calls the network. The model is replaced by `tests/fake_llm.py` (in-process) or `tests/fake_mai_server.py`
(a local stand-in for the mAI gateway that exercises `ai/mai_llm.py` for all three model families, including error mapping).
What the tests cannot tell you is how the *real* model behaves on your documents. `tests/live_check.py` is for that.
See [docs/testing.md](docs/testing.md).

## Known limits

- **Model quality is the ceiling.** Prompts are tuned on the sample documents and structure, not on a labelled benchmark.
  Run `tests/live_check.py` on a few of your own budgets and read the reasons column before relying on numbers.
- **Scanned PDFs**: table and scanned pages are also attached to the model call as PDF pages, so the model can read them visually; accuracy is lower and the user is told.
- **One process.** Sessions, jobs and the rate limiter are in process memory. Do not run multiple workers (docs/deployment.md).
- **No currency conversion**; amounts keep the document's currency and unit.
- **Large documents** are read in sections. A section or batch that is too large for the model is split automatically,
  and page images too large to attach are left out (the text is still read).
- **Limits**: 600 pages, 2,500 distinct budget lines per document (largest by amount kept), 50 MB by default.

## Further reading

- [docs/architecture.md](docs/architecture.md) – modules, data flow, threading, routing
- [docs/ai-layer.md](docs/ai-layer.md) – provider interface, pacing and retries, prompts
- [docs/tagging-logic.md](docs/tagging-logic.md) – line cleaning, taggers, reconciliation table, metrics
- [docs/scoring.md](docs/scoring.md) – the 0–100 score
- [docs/sessions-and-privacy.md](docs/sessions-and-privacy.md) – session lifecycle, what is kept and what leaves the server
- [docs/testing.md](docs/testing.md) – test layout, stand-ins, what is and is not covered
- [docs/deployment.md](docs/deployment.md) – gunicorn, reverse proxy, sub-path, sizing
