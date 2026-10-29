# Architecture

## Layers

```
app.py ─────────────── Dash app, layout function, routing, session routes
  │
  ├─ utils/<page>.py ─ layout + callbacks for one page (home, evaluate, compare, methodology)
  │     └─ utils/components.py, charts.py, export.py, formatting.py   presentation helpers (no business rules)
  │
  ├─ utils/session.py ─ visitors, uploads, background jobs (memory only)
  │
  └─ tagging/pipeline.py ── analyse_document / compare_budgets      the only entry points the pages call
        ├─ utils/documents.py     bytes → pages → chunks
        ├─ ai/tasks.py            the four model jobs (describe, extract, tag, score)
        │     └─ ai/client.py → ai/<provider>.py                      the only code that touches a model
        └─ tagging/{lines,rio_tagger,eu_tagger,reconcile,metrics}.py  deterministic logic
```

Rules the code follows, which keep the layers replaceable:

- Pages never import `ai/` except `ai.client.is_configured()` for the "not set up" message. They call `tagging.pipeline`.
- `tagging/` does not know which model is used. It receives `AIVerdict` objects from `ai/tasks.py`.
- `ai/tasks.py` does not know which provider is used. It calls `ai.client.ask_json`.
- `utils/constants.py` holds names, labels, colours, limits and env var names. Labels shown to users live there so the
  site, the Excel files and the methodology page cannot drift apart.

## Routing

One Dash page, query-string routing (`?page=home|evaluate|compare|methodology`). A `dcc.Location` feeds the `route`
callback in `app.py`, which returns `page_shell(page, body)`. Query-string routing keeps the app working under any URL
prefix without extra configuration. The Methodology link is a plain `<a target="_blank">`, so it opens in a new browser
tab; a clientside callback sets `document.title` per page.

`app.layout` is a **function** (`serve_layout`). Every page load therefore creates a fresh session id, which is how a
refresh starts clean.

## Page callbacks

Each tool page follows the same pattern (see `utils/evaluate.py`):

1. `start_or_stop` (Upload contents / Stop clicks) validates the file, calls `session.start_job`, returns immediately.
2. `show_job` runs on the job store update and on a 1 s `dcc.Interval`. It renders the loader (running), the results
   (done) or a notice (failed / cancelled), and disables the interval once the job is finished.
3. Result tables, downloads and the table switch read the finished `Analysis` from the job in the session. Nothing is
   put in `dcc.Store`; results never travel to the browser except as rendered figures and table rows.

`compare.py` registers one upload callback per slot (A and B) so only the dropzone that was used shows the "uploading"
bar. Both files are held in `session.Session.uploads` until Compare is pressed.

## Loading indicators

- Upload: each dropzone's message area is wrapped in `dcc.Loading` with `custom_spinner=components.loader("uploading")`.
- Processing: `Job.stage` / `Job.detail` are set by `progress(stage, detail)` calls inside the pipeline
  (`reading`, `finding` "Section 3 of 12", `tagging` "120 of 480 lines", `calculating`, `scoring`). `show_job` turns them
  into `components.loader(...)`: a text label and a bar that sweeps indefinitely (pure CSS, no percentage).
  `prefers-reduced-motion` switches the sweep to a gentle pulse.

## Data model

`pipeline.Analysis` is the single result object:

| Field | Content |
|---|---|
| `info` | `DocInfo`: name, country, year, currency, unit (+ `unit_text`) |
| `rio`, `eu` | one row per budget line: base columns (`line`, `page`, `code`, `ministry`, `programme`, `description`, `function_code`, `amount`) + tag columns + `decided_by` |
| `rio_summary`, `eu_summary` | headline numbers from `metrics.summarize` (shares, per-objective shares, counts by deciding rule) |
| `stats` | counts and timings (lines, sections, pages, selection statistics) |
| `issues` | list of `{level, message}` shown above the results (scan pages, skipped sections, basis of the shares …) |

`Comparison` holds `scores`, `reasons`, `summary` and the `rubric` parts for A and B.

## Threads

- Web: Flask threads (gunicorn `--threads`).
- One background thread per running analysis (`session.start_job`).
- Inside an analysis the reading and tagging steps each use a `ThreadPoolExecutor` (`AI_PARALLEL_CALLS`); all model calls share one
  process-wide `RateLimiter`.
- One daemon thread sweeps idle sessions every 30 s.

Cancellation is cooperative: `Job.stop` is a `threading.Event` passed to the pipeline as `cancelled()`. It is checked
before every model call and inside every wait, so Stop takes effect within a fraction of a second even during back-off.
