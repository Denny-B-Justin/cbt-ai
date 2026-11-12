# Climate Budget Tagging Tool: Georgian method

A Plotly Dash application that tags government budgets with the method of **Climate Budget Tagging in Georgia: Handbook**
(Ministry of Environmental Protection and Agriculture of Georgia and the World Bank, June 2025). It reads a budget document
(PDF, Word or Excel), has an LLM extract every budget line and answer the handbook's four guiding questions for it, gives
each climate-tagged line its CBT code (**CM** mitigation, **CA** adaptation, **CB** both) and its level (**100, 70, 40 or
20**), computes all shares and charts deterministically in code, and can score and compare two budgets.

It succeeds the rule-based `wb-climate-budget-tagging` app (Excel/CSV in, keyword matching, Databricks storage). What changed:

| | Previous version | This version |
|---|---|---|
| Input | Structured Excel/CSV | PDF, Word or Excel, any layout |
| Reading the budget | Column mapping | LLM extracts budget lines from text and table pages |
| Tagging | Keyword counts | LLM judgement per line with the handbook's guiding questions and four levels |
| Storage | Databricks | None. Memory only, per visitor, deleted when the page closes |
| Pages | Several | Home, **Evaluate Budget**, **Compare Budget**, Methodology |

The model is **only asked for judgements** (what the lines are, which tag fits, how a budget compares). Every sum, share,
chart value and table is computed in Python from those judgements.

> **Demo scope.** There is no database, no file storage and no accounts. State lives in the memory of one server process.
> See [docs/sessions-and-privacy.md](docs/sessions-and-privacy.md) for what that implies, including what leaves the server.

---

## Quick start

Python 3.10 or later (3.12 recommended). You need an API key from at least one of OpenAI, Anthropic, Google Gemini or
Mistral AI.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env                                     # then put your key(s) in .env
python app.py                                           # http://127.0.0.1:8050
```

Check your key and the model with one small real call before analysing whole budgets (this uses a little API credit):

```bash
python tests/live_check.py                    # settings, one small call, reading + tagging a sample budget
python tests/live_check.py --every-model      # one small call to every model your keys unlock
python tests/live_check.py --full             # also a complete analysis and a two-budget comparison
```

Try the whole interface without any key (uses a scripted stand-in for the model):

```bash
python tests/serve_fake.py            # PORT=8051 python tests/serve_fake.py for another port
```

Production (see [docs/deployment.md](docs/deployment.md) for why exactly one worker):

```bash
gunicorn app:server --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:8050
```

## Configuration

### AI provider keys

Put them in `.env` (copied from `.env.sample`, git-ignored) or in your host's environment settings. Set at least one;
leave the others empty.

| Variable | Unlocks these models in the picker |
|---|---|
| `OPENAI_API_KEY` | GPT-6 Astra, GPT-6.1 Sol, GPT-6 Luna, and the older GPT-5.6 Luna |
| `ANTHROPIC_API_KEY` | Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku 5.5, and the older Claude Haiku 4.5 |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Gemini 4 Argon, Gemini 3.8 Flash, Gemini 3.5 Flash-Lite, and the older Gemini 3.1 Flash-Lite |
| `MISTRAL_API_KEY` | Mistral Large, Medium and Small (latest), and the older Mistral Large 3 |

People choose the model on the Evaluate and Compare pages; only the models of providers with a key are listed. The
model pre-selected is the first of GPT-6.1 Sol, Claude Sonnet 5.5, Gemini 3.8 Flash and Mistral Medium whose provider has
a key. The lists are `MODELS` and `DEFAULT_MODELS` in `constants.py`: edit them when a provider releases or retires a model.

Optional `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `GEMINI_BASE_URL` and `MISTRAL_BASE_URL` send a provider's calls to
another address, for example a company proxy.

### Optional app settings

All have sensible defaults; a `.env` file is read if present (see `.env.sample`).

| Variable | Default | Meaning |
|---|---|---|
| `AI_REQUESTS_PER_MINUTE` | `50` | Calls per minute for each model, shared by all visitors using it. Set it to your account tier's limit. |
| `AI_TOKENS_PER_MINUTE` | `0` | Token budget per minute for each model (`0` switches it off). Set it when your tier's token limit is the tighter one. Refused calls (429) are waited out and retried either way. |
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
   │                                                5. tasks.tag_budget_lines      LLM, batches of 60 → Q1–Q4, level, sector per distinct line
   │                                                6. tags + metrics              CM/CA/CB, level × amount, CB split 50/50; shares in pandas
   └────────────── charts, tables, .xlsx ◀────────  Analysis(lines, summary, stats, issues)
```

Compare Budget runs steps 1–6 for budget A, then B, then `pipeline.compare_budgets` (step 7: one LLM call that scores both).
The two tabs share no state; each owns a "slot" (`evaluate`, `compare`) in the visitor's session.

## Repository layout

```
app.py                 Dash app, layout, routing, session beacon routes
constants.py           what the system needs: AI models (MODELS, DEFAULT_MODEL), env var names, limits, stages, method vocabulary
page_constants.py      what only the pages need: routing, page text, loading-bar labels, colours
assets/                CSS, session.js (heartbeat + pagehide beacon), logo, favicon, fonts, hero art
ai/                    everything that talks to a model
  client.py            provider lookup, pacing, retries (provider-neutral)
  ratelimit.py         RateLimiter (requests and tokens per minute, adaptive) + call_with_retries
  types.py             Attachment, DocInfo, error types, Cancelled
  llm.py               the provider entry: API keys, models on offer, one attempt with the chosen model
  provider_openai.py, provider_anthropic.py, provider_gemini.py, provider_mistral.py   one module per provider API
  provider_common.py   what they share: JSON-schema helper, token usage, SDK errors → app errors
  schemas.py           JSON schemas for the four tasks + tolerant JSON loading
  prompt.py            all prompts
  tasks.py             describe / extract / tag / score: the four jobs, with splitting and second passes
tagging/               everything that decides or computes
  lines.py             record cleaning, merging, hierarchy and double-counting rules
  models.py            Verdict: the AI's answer for one line, made consistent
  tags.py              line rows: CBT code, level, "decided by", climate / mitigation / adaptation amounts
  metrics.py           shares, the grouped tables behind every chart, fallback scoring rubric
  pipeline.py          analyse_document, compare_budgets, Analysis dataclass
utils/                 one module per page plus shared helpers
  home.py, evaluate.py, compare.py, methodology.py   pages and their callbacks
  components.py, charts.py, export.py, formatting.py presentation helpers
  documents.py         PDF/DOCX reading and chunking
  session.py           in-memory sessions, uploads and background jobs
  (constants.py and page_constants.py are at the top level, above)
docs/                  developer documentation + samples/ (fictional test documents)
tests/                 pytest suite, stand-in model, fake provider APIs, live smoke test
```

## What the model does, and what it does not

| Step | Model decides | Code decides |
|---|---|---|
| Describe | name, country, year, currency, unit | fallbacks when absent or odd |
| Extract | which text rows are budget lines; amount, kind (programme / function / ministry / category / total), page | amount parsing, dropping totals, merging, hierarchy, duplicates, negative amounts |
| Tag | the four guiding questions (Q1–Q4), level class, sector, function, service cost, liveable wording, confidence, one-line reason | CM/CA/CB from Q1–Q4; level snapped to 100/70/40/20 for tagged lines (0 otherwise); service costs untagged; CB split; climate amounts |
| Score | 0–100 and a sentence per budget, a two-sentence comparison | clamping to ±15 of the fixed rubric (`SCORE_GUARD`) |
| Everything else | – | all sums, shares, charts, tables, Excel files |

Details: [docs/ai-layer.md](docs/ai-layer.md), [docs/tagging-logic.md](docs/tagging-logic.md), [docs/scoring.md](docs/scoring.md).

## Testing

```bash
pip install -r requirements-dev.txt && playwright install chromium
pytest                       # everything (about 90 seconds; the browser tests are most of it)
pytest -m "not ui"           # skip the headless-browser tests (about 10 seconds)
```

No test calls the network. The model is replaced by `tests/fake_llm.py` (in-process) or `tests/fake_llm_server.py`
(a local stand-in for the OpenAI, Anthropic, Gemini and Mistral APIs that exercises `ai/llm.py` and the four provider
modules with the real SDKs, including error mapping).
What the tests cannot tell you is how the *real* model behaves on your documents. `tests/live_check.py` is for that.
See [docs/testing.md](docs/testing.md).

## Known limits

- **Model quality is the ceiling.** Prompts are tuned on the sample documents and structure, not on a labelled benchmark.
  Run `tests/live_check.py` on a few of your own budgets and read the reasons column before relying on numbers.
- **Scanned PDFs**: table and scanned pages are also attached to the model call as PDF pages, so the model can read them visually; accuracy is lower and the user is told. Mistral's chat models take documents only as public links, so with Mistral only the extracted text is sent.
- **One process.** Sessions, jobs and the rate limiter are in process memory. Do not run multiple workers (docs/deployment.md).
- **Your keys, your costs.** Every analysis is paid from the API key of the provider chosen. A large national budget can
  take hundreds of thousands of tokens; try a small document first.
- **No currency conversion**; amounts keep the document's currency and unit.
- **Large documents** are read in sections. A section or batch that is too large for the model is split automatically,
  and page images too large to attach are left out (the text is still read).
- **Limits**: 600 pages, 2,500 distinct budget lines per document (largest by amount kept), 50 MB by default.

## Further reading

- [docs/architecture.md](docs/architecture.md) – modules, data flow, threading, routing
- [docs/ai-layer.md](docs/ai-layer.md) – provider interface, pacing and retries, prompts
- [docs/tagging-logic.md](docs/tagging-logic.md) – line cleaning, the guiding questions and four levels, CBT codes, metrics
- [docs/scoring.md](docs/scoring.md) – the 0–100 score
- [docs/sessions-and-privacy.md](docs/sessions-and-privacy.md) – session lifecycle, what is kept and what leaves the server
- [docs/testing.md](docs/testing.md) – test layout, stand-ins, what is and is not covered
- [docs/deployment.md](docs/deployment.md) – gunicorn, reverse proxy, sub-path, sizing
