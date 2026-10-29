# Sessions and privacy

The demo stores nothing on disk and has no database. Everything a visitor does lives in `utils/session.py`, in the memory
of the server process, under a random 128-bit id.

## Lifecycle

| Event | What happens |
|---|---|
| Page load | `serve_layout()` makes a new id, puts it in a `dcc.Store` and in a hidden `#session-root[data-sid]`. The server creates the session lazily on first use. |
| While the page is open | `assets/session.js` POSTs the id to `/_session/ping` every 20 s; running jobs also touch the session every poll. |
| Tab closed, navigated away, browser closed | `pagehide` → `navigator.sendBeacon('/_session/end', sid)`. The session, its uploads, its jobs and its results are deleted and running jobs are told to stop. |
| Refresh | The old page fires `pagehide` (old session ended); the new page gets a new id. Results are gone by design. |
| Back/forward cache restore | `pageshow` with `persisted` reloads the page so a dead session is never shown. |
| Beacon lost (crash, network, mobile) | A daemon thread runs `session.sweep()` every 30 s and ends sessions silent for `SESSION_IDLE_MINUTES` (15). |
| Process restart | Everything is gone. |

Navigating between the app's own pages does **not** end the session (it is the same browser page; only the content is
swapped), so a running analysis continues and its result is there when the visitor returns to that tab.

## What is held, and where

| Data | Where | Released |
|---|---|---|
| Evaluate upload bytes | closure of the running job | when the job ends |
| Compare uploads (A, B) | `Session.uploads` | when replaced, or session end (kept so the comparison can be repeated after a failure) |
| `Analysis` results (data frames, summaries) | `Job.result` | session end, or Stop |
| Rendered figures and tables | browser only | page close |
| Excel downloads | built on demand from `Job.result`, streamed to the browser | never stored |

Not stored: uploaded files on disk, results on disk, user identifiers, IP addresses (beyond normal web-server access logs,
which contain no document content). The application log contains stack traces for unexpected errors; document text is not logged by design (an exception message could in rare cases quote a short fragment).

## What leaves the server

Document text and, for table or scanned pages, the original PDF pages are sent to the model provider so it can read them.
Budget briefs (numbers and line names) are sent for scoring. This is inherent to the design and is disclosed on the
site in plain words ("read by an online AI service … please do not upload confidential documents").

**Free vs. paid keys.** Under Google's current Gemini API terms, content submitted through unpaid (free-tier) services may be
used to improve Google's products and may be read by human reviewers, and the terms ask users not to submit confidential or
personal data to unpaid services. Paid services are excluded from product improvement (Google keeps logs for a limited
period for abuse detection). Read the current terms at <https://ai.google.dev/gemini-api/terms> before deciding which kind
of key a deployment uses. A demo with public or already-published budgets is fine on a free key; anything sensitive needs a
paid key and a decision by the data owner.

## Concurrency and abuse limits

- `MAX_RUNNING_ANALYSES` (default 8) – further starts get a friendly "busy" message instead of queuing without bound.
- One running job per slot per visitor; starting again stops the previous one.
- Upload limits: `MAX_UPLOAD_MB` (server check, friendly message), 3× that in the browser (protects tab memory),
  600 pages, 2 500 distinct lines.
- Uploaded documents are treated as untrusted text: wrapped in `<document>` tags and prefixed by a system instruction not to
  follow instructions found inside. Excel output neutralises text that begins with `=` so a budget line cannot become a
  formula.
- The session endpoints accept any body and ignore unknown ids (they leak nothing and change nothing for other visitors).
  There is no authentication: **anyone who can reach the URL can use your API quota.** Put it behind your own access
  control (VPN, SSO proxy, basic auth) and keep `AI_REQUESTS_PER_MINUTE` realistic.
