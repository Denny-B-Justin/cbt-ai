# Deployment

## One process, several threads

```bash
gunicorn app:server --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:8050
```

**Use exactly one worker process.** Sessions, running jobs, uploads and the rate limiter are Python objects in one process.
With two workers, a visitor's polling request can land on a process that has never heard of their job and see an empty page.
Threads give concurrency (long analyses run in their own background threads, so web threads stay free). Scale up with a bigger
machine, not more workers. To run more than one process you would need a shared store and a job queue; that is out of scope
for the demo (see "If this becomes more than a demo").

`--timeout 300` only matters for the slowest web requests (a very large upload). Analyses are not bound by it because they run
outside the request.

## Settings

Provide environment variables (see README). Put the key in the platform's secret store, not in the image. `.env` is read
only if present and is in `.gitignore`.

## Reverse proxy

- Allow request bodies of at least `3 × MAX_UPLOAD_MB` plus ~35 % for base64 (Dash sends uploads as text). For the default
  of 50 MB that is about 200 MB. nginx: `client_max_body_size 200m;`.
- Pass `/_session/*` through unchanged; they are plain `POST` routes.
- Do not buffer-cache `/_dash-update-component`.
- Sub-path hosting: set `DASH_URL_BASE_PATHNAME=/tagging/` (Dash reads it). Routing is query-string based and the session
  routes and `session.js` use the configured prefix, so nothing else is needed.
- TLS and access control belong at the proxy. The app has no authentication.

## Sizing

- Memory (estimate, measure with your own documents): a 50 MB upload can briefly need around 200 MB (the base64 text in the
  request, the decoded bytes, the parsed pages). Compare keeps both uploads per visitor until the session ends. Size the
  machine for `MAX_RUNNING_ANALYSES` of those at once.
- CPU is small; time is dominated by model calls. A 100-page budget needs on the order of 10–40 calls (reading sections
  plus tagging batches). At `AI_REQUESTS_PER_MINUTE=8` that is a few minutes; the loading bar says so.
- The rate limiter is global. Ten visitors share the same requests-per-minute budget, so each waits longer. If your key has
  more headroom, raise `AI_REQUESTS_PER_MINUTE` and `AI_PARALLEL_CALLS` together.

## Health and logs

- `GET /` returns the app shell (use it for liveness).
- Logs go to stdout via `logging` (`LOG_LEVEL`). Unexpected errors in a background job are logged with a stack trace; the
  visitor sees a generic sentence. Provider error messages are logged at warning level only through the mapped exception text.
- No telemetry is sent anywhere by the app.

## Upgrading dependencies

`requirements.txt` pins ranges, not exact versions. Before upgrading `dash`, `plotly` or `google-genai`, run `pytest` (the
Gemini tests exercise the real SDK against a local server, so breaking SDK changes surface there) and
`python tests/live_check.py`.

## If this becomes more than a demo

Everything that would need to change is isolated: replace `utils/session.py` with a store keyed by session id (Redis for
state, object storage for uploads), run jobs on a queue (RQ/Celery) with the same `progress` / `cancelled` callbacks,
move the `RateLimiter` to a shared limiter, add authentication, and decide on retention rules. `tagging/` and `ai/` need no changes.
