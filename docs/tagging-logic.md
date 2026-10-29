# Tagging logic (`tagging/`, `utils/documents.py`)

## 1. From file to pages (`utils/documents.py`)

- **PDF** (PyMuPDF): text per page, with table rows rebuilt as `a | b | c` from word positions so columns survive.
  Repeated header/footer lines are removed. A page with at least 25 amount-like numbers is flagged *table-like*; a page
  with fewer than 120 characters is flagged *scanned*.
- **DOCX** (python-docx): paragraphs and tables in document order, cut into pseudo-pages of about 3 500 characters.
- Notes for the user: if every page is scanned, or at least `max(3, 5 %)` of pages are, `Document.notes` gets a sentence
  that ends up in the results as an info notice.
- Limits: `ALLOWED_SUFFIXES`, `MAX_PAGES` (600), `max_upload_bytes()`; errors are `DocumentError` with a user-safe message.

### Chunking

`make_chunks` groups consecutive pages up to `CHUNK_CHARS` (28 000). A scanned page weighs `SCAN_PAGE_WEIGHT` (2 600) so
image-heavy documents split into more calls. For PDF chunks containing table-like or scanned pages the original pages
are attached (`_pdf_slice`, at most 12 MB, split further when larger). `split_chunk` halves a chunk by pages, or by lines
if it is a single page, when an answer is cut off.

## 2. From records to budget lines (`tagging/lines.py::select_lines`)

The model returns *records* (it may list the same money several ways). `select_lines` turns them into the set of lines
that are summed, in this order:

1. **Clean**: collapse whitespace, parse amounts (`parse_amount` handles thousands separators, decimal commas,
   brackets/minus for negatives, nulls like `-` and `n/a`), cap text lengths, normalise `kind`.
2. **Drop** `total` and `category` records.
3. **Negative amounts** are set to "no amount" (they cannot be part of a share) and counted for the notice.
4. **Merge by code**: records with the same specific code (≥ 4 digits, trailing all-zero parts ignored) are one line:
   longest title, max-abs amount, descriptions joined.
5. **Choose one view**: `programme` > `function` > `ministry`, the first kind with at least 3 lines. If the document shows
   several views the user is told which one is used, so the same money is not counted twice.
6. **Hierarchy**: a coded parent whose coded children have amounts is a subtotal and is dropped; coded children without an
   amount are folded into the nearest coded parent's description ("Includes: …").
7. **De-duplicate**: same code, or (title, ministry, amount) when there is no code.

Everything dropped is counted in `Selection.stats` and shown in the Evaluate page's technical-free notices.

## 3. Distinct classifications

`pipeline._unique_items` keys lines on (ministry, title, description, function code), lower-cased. The model tags each
distinct key once; the verdict is copied to every line with the same key.

## 4. The two keyword taggers (second opinion)

`RioMarkerTagger` and `EUTaxonomyTagger` are ported from the previous version (`keywords.py`, `cofog.py`, `matcher.py`).
They return a result plus a method label (`KEYWORDS`, `EXCLUSION`, or `PREDETERMINED` when the line carries a COFOG function
code: division 05 "environmental protection" is rated principal, the other known divisions are rated neutral). `matcher.py` matches whole words and phrases with simple plural handling (`s`, `es`,
consonant-`y` → `ies`) and returns the surface form it matched, which is shown in rationales.
Their vocabularies differ (the Rio lists are stricter on adaptation than the EU lists); disagreement lowers confidence, it
does not change the model's tag, except in the cases below.

## 5. Reconciliation (`tagging/reconcile.py`)

The model's verdict is primary. The keyword result can confirm it, lower its confidence, or flag the line. **Keywords never
make a line greener.**

| Model verdict | Keyword check | Result | `decided_by` | Confidence |
|---|---|---|---|---|
| no verdict (model failed for this line) | anything | keyword result | Keyword check only | LOW |
| administrative | – | Rio 0/0, EU neutral | Routine administration | HIGH if keywords agree (no relevance), else MEDIUM |
| Rio 0 | marker > 0 | Rio 0 | Needs a second look | LOW |
| Rio 0 | none (exclusion term) | Rio 0 | Routine administration | model's |
| Rio 0 | none | Rio 0 | No climate relevance found | model's |
| Rio > 0 | marker > 0 | model's ratings | Confirmed by both checks | model's if same marker, else ≤ MEDIUM |
| Rio > 0 | none | model's ratings | AI judgement only | ≤ MEDIUM |
| brown | green | EU brown | Needs a second look | LOW |
| brown | brown | EU brown | Fossil or polluting activity | model's |
| brown | other | EU brown | Fossil or polluting activity | ≤ MEDIUM |
| objectives | green | EU green with the model's objectives | Confirmed by both checks | model's if same main objective, else ≤ MEDIUM |
| objectives | brown | EU green (model's objectives) | Needs a second look | LOW |
| objectives | neutral | EU green | AI judgement only | ≤ MEDIUM |
| no objectives | green or brown | EU neutral | Needs a second look | LOW |
| no objectives | neutral | EU neutral | No climate relevance found / Routine administration | model's |

Rio and EU are reconciled independently, so one line can be "Confirmed" in one taxonomy and "AI judgement only" in the other.
The Rio marker of a line is `max(mitigation, adaptation)`.

## 6. Numbers (`tagging/metrics.py::summarize`)

- **Basis**: amount if any line has an amount, otherwise number of lines (the user is told). Lines without an amount are
  ignored in amount-based shares. Amounts are used as given; currencies are never converted.
- **Rio**: `principal_share`, `significant_share`, `weighted_share = (principal + 0.4 · significant) / total`,
  `mitigation_share` / `adaptation_share` (the full share of lines whose mitigation / adaptation rating is above 0; not
  weighted, and a line rated for both counts in both), counts by deciding rule.
  The weights are `constants.RIO_WEIGHTS`.
- **EU**: `green_share`, `brown_share`, per-objective amounts and shares (`objective_shares`; a line serving several
  objectives counts fully towards each, so objective shares can add up to more than the green share), counts by rule.
- All charts and the Excel files read these dictionaries and the two frames; nothing is recomputed in the page code.
