# Tagging logic (`tagging/`, `utils/documents.py`)

## 1. From file to pages (`utils/documents.py`)

- **PDF** (PyMuPDF): text per page, with table rows rebuilt as `a | b | c` from word positions so columns survive.
  Repeated header/footer lines are removed. A page with at least 25 amount-like numbers is flagged *table-like*; a page
  with fewer than 120 characters is flagged *scanned*.
- **DOCX** (python-docx): paragraphs and tables in document order, cut into pseudo-pages of about 3 500 characters.
- **XLSX / XLSM** (openpyxl, computed values): every non-empty row of every sheet, written as
  `R12: A: code | B: name | D: 1,250` (column letters, so any column names work), cut into pseudo-pages of about
  3 500 characters. Each pseudo-page starts with `Sheet: <name>`. Merged headings show the columns they cover
  (`E-L: 2027 Forecast`; workbooks above 15 MB are streamed without this). No schema is imposed: the first 10 filled
  rows of each sheet are kept in `Document.headings`, and any section that starts mid-sheet opens with them in a
  `<sheet_headings>` block, so every AI call can rebuild the column names itself. For Excel the extraction system
  prompt adds `SPREADSHEET_SYSTEM` (multi-row headings, year and funding-source columns, code hierarchy, skipping
  non-money rows such as staff counts, go through every row of every sheet).
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

## 4. The tag of a line (`ai/tasks.py::verdict_from_row`, `tagging/tags.py`)

The method is *Climate Budget Tagging in Georgia: Handbook* (Ministry of Environmental Protection and Agriculture of
Georgia and the World Bank, June 2025), Steps 1–3. The model receives `ai/prompt.py::TAG_SYSTEM`: the handbook's
definitions, GHG sources by sector, the four guiding questions, the four levels, the salary and service-cost rules and
its labelled examples. For each line it answers Q1–Q4, picks a level, a sector and a government function (COFOG
division), flags service costs and liveable / habitable wording, and gives a confidence and a one-line reason.

`verdict_from_row` makes the answer consistent (it is the only place these rules live):

- **Mitigation** = Q1 and Q2; **adaptation** = Q3 and Q4. A measure without its link (Q2 without Q1) does not count.
- **Service-oriented** lines are not tagged (no code, no level), whatever the questions say.
- **Liveable or habitable wording** alone (a rule of this tool, not of the handbook) makes the line adaptation at level
  `FLOOR_LEVEL` (20); with a real measure it only raises the level to at least 20.
- **Levels are classes.** A climate-tagged line always has one of **100, 70, 40, 20**: the model's number snaps to the
  nearest class (`snap_level`; ties go lower, 37 → 40), and a tagged line with 0 or no level gets 20. A line that is not
  climate-tagged has level 0 ("Not climate").
- Unknown sectors become `None`, unknown functions `Not known`, unknown confidence `MEDIUM`.

`tags.tag_row` turns a verdict into the line's columns:

| Column | Value |
|---|---|
| `cbt_code` | `CB` (both), `CM` (mitigation), `CA` (adaptation) or `""` |
| `climate_level` | 100, 70, 40, 20, or 0 when not tagged |
| `mitigation_share`, `adaptation_share` | `level / 100` to the line's aim; a CB line gets `level / 200` in each, so a line is never counted twice |
| `tag_method` → `decided_by` | the first that applies: liveable wording only, both measures, mitigation measure, adaptation measure, service cost, GHG or hazard link without a measure, no relevance |

A line the model skipped even after the second pass has no verdict: it is **Not assessed**, not tagged, `LOW`
confidence, and the user is told how many there are. If the model returns no verdict at all, the analysis stops with an
error.

`tags.tagged_frame` adds `mitigation_amount`, `adaptation_amount` and `climate_amount` (= amount × share) per line.

## 5. Numbers (`tagging/metrics.py::summarize`)

- **Basis**: amount if any line has an amount, otherwise number of lines (the user is told). Lines without an amount are
  ignored in amount-based shares. Amounts are used as given; currencies are never converted.
- **Shares of the budget**: `climate_share`, `mitigation_share`, `adaptation_share` (sum of the counted parts ÷ total).
  Mitigation and adaptation add up to the climate share.
- **Composition of the climate spend**: `mitigation_of_climate`, `adaptation_of_climate`, `level_of_climate` (share of
  the climate spend at each level), `high_level_share` (levels 100 and 70).
- **Counts**: `tagged_lines`, `code_lines` (CM, CA, CB).
- **Grouped tables** for the charts, all from the same counted parts so they add up: `by_level`, `level_code`
  (level × CBT code), `by_sector`, `by_ministry`, `by_function`, `sector_levels`, `ministry_levels`, `by_method`
  (lines and amount per "decided by"), `floor_lines` (lines counted only for liveable wording), and
  `climate_sectors` (sectors with at least 1 % of the climate spend).
- The Evaluate page, the Excel file and the comparison read these; nothing is recomputed in page code. There is no
  per-year chart: an analysis covers one budget year, so it would repeat the headline share.
