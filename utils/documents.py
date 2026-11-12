"""Read an uploaded PDF, Word or Excel file into clean text pages and split it into sections for the AI."""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import date, datetime
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

import constants as C


AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{1,2}\b")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024    # stays under the smallest per-document limit of the mAI models (Claude: 4.5 MB)
DOCX_PAGE_CHARS = 3500
SHEET_HEADING_ROWS = 10                    # top rows of a sheet repeated with every later section of it
SHEET_HEADING_CHARS = 3000
MERGED_CELLS_MAX_BYTES = 15 * 1024 * 1024  # larger workbooks are read row by row, without merged-cell spans
SCAN_PAGE_WEIGHT = 2600


class DocumentError(Exception):
    """A problem with the uploaded file; the message is safe to show to the user."""


@dataclass
class Page:
    number: int
    text: str
    table_like: bool = False
    scanned: bool = False
    sheet: str = ""                            # Excel only: the sheet this pseudo-page comes from
    continued: bool = False                    # Excel only: not the first pseudo-page of its sheet


@dataclass
class Chunk:
    index: int
    first_page: int
    last_page: int
    text: str
    pdf_slice: bytes | None = None

    @property
    def label(self) -> str:
        return "page %d" % self.first_page if self.first_page == self.last_page else "pages %d-%d" % (self.first_page, self.last_page)


@dataclass
class Document:
    filename: str
    kind: str                                  # "pdf" | "docx" | "xlsx"
    pages: list[Page]
    pdf_bytes: bytes | None = None
    notes: list[str] = field(default_factory=list)
    headings: dict[str, str] = field(default_factory=dict)   # Excel only: sheet name -> its top rows

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    @property
    def n_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)

    def sample_text(self, limit: int = 6000) -> str:
        out, used = [], 0
        for p in self.pages:
            if used >= limit:
                break
            out.append(p.text[: limit - used])
            used += len(out[-1])
        return "\n".join(out)


def clean_text(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").replace("Ɵ", "ti")
    text = _CTRL_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s{3,}", " | ", line.strip())
        line = re.sub(r"[ \t]{2,}", " ", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def _drop_repeated_lines(pages: list[Page]) -> None:
    """Remove running headers and footers that repeat on most pages."""
    if len(pages) < 5:
        return
    counts: Counter = Counter()
    for p in pages:
        counts.update({ln for ln in p.text.splitlines() if len(ln) < 80})
    repeated = {ln for ln, n in counts.items() if n >= 0.4 * len(pages)}
    if repeated:
        for p in pages:
            p.text = "\n".join(ln for ln in p.text.splitlines() if ln not in repeated)


def _mark_page(page: Page) -> Page:
    page.table_like = len(AMOUNT_RE.findall(page.text)) >= C.TABLE_PAGE_NUMBERS
    page.scanned = len(page.text) < C.SCAN_PAGE_CHARS
    return page


def read_document(data: bytes, filename: str) -> Document:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in C.ALLOWED_SUFFIXES:
        raise DocumentError("Please upload a PDF, Word (.docx) or Excel (.xlsx) file.")
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > C.max_upload_bytes():
        raise DocumentError("This file is larger than %d MB. Please upload a smaller file or an extract." %
                            (C.max_upload_bytes() // (1024 * 1024)))
    if suffix == ".pdf":
        doc = _read_pdf(data, filename)
    elif suffix in C.EXCEL_SUFFIXES:
        doc = _read_xlsx(data, filename)
    else:
        doc = _read_docx(data, filename)
    if doc.n_pages > C.MAX_PAGES:
        raise DocumentError("This document has %d pages; the limit is %d. Please upload an extract." % (doc.n_pages, C.MAX_PAGES))
    if doc.n_chars < 80 and doc.kind in ("docx", "xlsx"):
        raise DocumentError("We could not find any readable text in this file.")
    if doc.kind == "pdf":
        n = sum(1 for p in doc.pages if p.scanned)
        if n and n == doc.n_pages:
            doc.notes.append("This PDF has no selectable text, so its pages were read as pictures. Results may be less exact.")
        elif n >= max(3, 0.05 * doc.n_pages):
            doc.notes.append("%d page(s) have no selectable text and were read as pictures." % n)
    return doc


def _read_pdf(data: bytes, filename: str) -> Document:
    import pymupdf

    try:
        src = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentError("We could not open this PDF. It may be damaged.") from exc
    try:
        if src.needs_pass:
            raise DocumentError("This PDF is password-protected. Please remove the password and upload it again.")
        if src.page_count == 0:
            raise DocumentError("This PDF has no pages.")
        pages = [Page(i + 1, clean_text(pg.get_text("text", sort=True))) for i, pg in enumerate(src)]
    finally:
        src.close()
    _drop_repeated_lines(pages)
    for p in pages:
        _mark_page(p)
    return Document(filename=filename, kind="pdf", pages=pages, pdf_bytes=data)


def _docx_blocks(doc) -> list[str]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                blocks.append(text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells: list[str] = []
                for cell in row.cells:
                    t = " ".join(cell.text.split())
                    if not cells or cells[-1] != t:       # merged cells repeat; keep one copy
                        cells.append(t)
                if any(cells):
                    blocks.append(" | ".join(cells))
    return blocks


def _read_docx(data: bytes, filename: str) -> Document:
    import docx

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentError("We could not open this Word file. Please save it as .docx or upload a PDF.") from exc
    pages: list[Page] = []
    buf: list[str] = []
    size = 0
    for block in (clean_text(b) for b in _docx_blocks(doc)):
        if size + len(block) > DOCX_PAGE_CHARS and buf:
            pages.append(Page(len(pages) + 1, "\n".join(buf)))
            buf, size = [], 0
        buf.append(block)
        size += len(block)
    if buf:
        pages.append(Page(len(pages) + 1, "\n".join(buf)))
    for p in pages:
        _mark_page(p)
        p.scanned = False
    if not pages:
        raise DocumentError("We could not find any readable text in this file.")
    return Document(filename=filename, kind="docx", pages=pages)


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return "{:,}".format(value)
    if isinstance(value, float):
        if value.is_integer():
            return "{:,}".format(int(value))
        return "{:,.2f}".format(value).rstrip("0").rstrip(".") if abs(value) >= 1 else "{:.6g}".format(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == datetime.min.time() else value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(_CTRL_RE.sub(" ", unicodedata.normalize("NFKC", str(value))).split())


def _merged_spans(ws) -> dict[tuple[int, int], int]:
    """(row, column) of the top-left cell of each merged block that spans columns -> its last column."""
    ranges = getattr(getattr(ws, "merged_cells", None), "ranges", ())
    return {(r.min_row, r.min_col): r.max_col for r in ranges if r.max_col > r.min_col}


def _sheet_row(number: int, values: tuple, spans: dict[tuple[int, int], int] | None = None) -> str:
    """One spreadsheet row as 'R12: A: code | B: name | D: 1,250'. Column letters keep cells aligned with the headings
    whatever the headings are called; a merged heading is written over the columns it covers ('E-L: 2027 Forecast').
    Empty cells are left out."""
    from openpyxl.utils import get_column_letter

    cells = []
    for i, value in enumerate(values):
        text = _cell_text(value)
        if not text:
            continue
        col = get_column_letter(i + 1)
        last = (spans or {}).get((number, i + 1))
        cells.append("%s-%s: %s" % (col, get_column_letter(last), text) if last else "%s: %s" % (col, text))
    return "R%d: %s" % (number, " | ".join(cells)) if cells else ""


def _read_xlsx(data: bytes, filename: str) -> Document:
    """Every row of every sheet, in order, cut into pseudo-pages that start with the sheet name. The top rows of each
    sheet are kept in Document.headings so that every later section of the sheet can show its column headings again."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=len(data) > MERGED_CELLS_MAX_BYTES, data_only=True)
    except Exception as exc:
        raise DocumentError("We could not open this Excel file. Please save it as .xlsx and upload it again.") from exc
    pages: list[Page] = []
    headings: dict[str, str] = {}
    try:
        for ws in wb.worksheets:
            if not hasattr(ws, "iter_rows"):
                continue
            spans = _merged_spans(ws)
            top: list[str] = []
            buf: list[str] = []
            size = 0
            for number, values in enumerate(ws.iter_rows(values_only=True), start=1):
                line = _sheet_row(number, values, spans)
                if not line:
                    continue
                if len(top) < SHEET_HEADING_ROWS:
                    top.append(line)
                if size + len(line) > DOCX_PAGE_CHARS and buf:
                    pages.append(Page(len(pages) + 1, "\n".join(buf), sheet=ws.title, continued=len(pages) > first))
                    buf, size = ["Sheet: %s (continued)" % ws.title], 0
                elif not buf:
                    buf, first = ["Sheet: %s" % ws.title], len(pages)
                buf.append(line)
                size += len(line)
            if buf:
                pages.append(Page(len(pages) + 1, "\n".join(buf), sheet=ws.title, continued=len(pages) > first))
                headings[ws.title] = "\n".join(top)[:SHEET_HEADING_CHARS]
    finally:
        wb.close()
    if not pages:
        raise DocumentError("We could not find any filled cells in this Excel file.")
    for p in pages:
        _mark_page(p)
        p.scanned = False
    return Document(filename=filename, kind="xlsx", pages=pages, headings=headings)


def _pages_text(doc: Document, pages: list[Page]) -> str:
    """The text of consecutive pages with their [Page N] markers. A section that starts in the middle of an Excel sheet
    first repeats that sheet's top rows, so the AI can always tell what each column means."""
    text = "\n".join("[Page %d]\n%s" % (p.number, p.text) for p in pages)
    first = pages[0]
    if first.continued and doc.headings.get(first.sheet):
        text = _headings_block(doc, first) + "\n" + text
    return text


def _headings_block(doc: Document, page: Page) -> str:
    return '<sheet_headings sheet="%s">\n%s\n</sheet_headings>' % (page.sheet, doc.headings.get(page.sheet, ""))


def _pdf_slice(pdf_bytes: bytes, first: int, last: int) -> bytes | None:
    import pymupdf

    src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        out = pymupdf.open()
        out.insert_pdf(src, from_page=first - 1, to_page=last - 1)
        data = out.tobytes(garbage=3, deflate=True)
        out.close()
    finally:
        src.close()
    return data if len(data) <= MAX_ATTACHMENT_BYTES else None


def _page_weight(p: Page) -> int:
    if p.scanned:
        return SCAN_PAGE_WEIGHT                          # a picture page is read visually and yields many rows
    return len(p.text) * (2 if p.table_like else 1) + 200


def _with_slices(doc: Document, group: list[Page]) -> list[tuple]:
    """Pair a group of pages with the PDF pages to attach (table and scanned pages are also shown to the AI as pages).
    A group of scanned pages whose picture is too large to attach is cut in two."""
    if not (doc.kind == "pdf" and doc.pdf_bytes and any(p.table_like or p.scanned for p in group)):
        return [(group, None)]
    piece = _pdf_slice(doc.pdf_bytes, group[0].number, group[-1].number)
    if piece is not None or len(group) == 1 or not any(p.scanned for p in group):
        return [(group, piece)]
    mid = len(group) // 2
    return _with_slices(doc, group[:mid]) + _with_slices(doc, group[mid:])


def make_chunks(doc: Document, max_chars: int = C.CHUNK_CHARS) -> list[Chunk]:
    """Group consecutive pages into sections. Table pages weigh double: they produce many rows."""
    groups: list[list[Page]] = []
    cur: list[Page] = []
    weight = 0
    for p in doc.pages:
        w = _page_weight(p)
        if cur and weight + w > max_chars:
            groups.append(cur)
            cur, weight = [], 0
        cur.append(p)
        weight += w
    if cur:
        groups.append(cur)

    chunks: list[Chunk] = []
    for g, piece in (pair for group in groups for pair in _with_slices(doc, group)):
        text = _pages_text(doc, g)
        chunks.append(Chunk(len(chunks) + 1, g[0].number, g[-1].number, text, piece))
    return chunks


def split_chunk(chunk: Chunk, doc: Document) -> list[Chunk]:
    """Cut a section in two (used when the AI answer was too long). Returns [] if it cannot be split."""
    pages = [p for p in doc.pages if chunk.first_page <= p.number <= chunk.last_page]
    if len(pages) >= 2:
        mid = len(pages) // 2
        parts = [pages[:mid], pages[mid:]]
    elif doc.kind == "xlsx":
        # cut the rows of the one pseudo-page; each half keeps the sheet name and its headings
        first, *rows = pages[0].text.splitlines()
        if len(rows) < 20:
            return []
        mid = len(rows) // 2
        halves = [replace(pages[0], text="\n".join([first] + rows[:mid])),
                  replace(pages[0], text="\n".join([first] + rows[mid:]), continued=True)]
        return [Chunk(chunk.index, chunk.first_page, chunk.last_page, _pages_text(doc, [h])) for h in halves]
    else:
        lines = chunk.text.splitlines()
        if len(lines) < 20:
            return []
        mid = len(lines) // 2
        halves = ["\n".join(lines[:mid]), "\n".join(lines[mid:])]
        return [Chunk(chunk.index, chunk.first_page, chunk.last_page, h, chunk.pdf_slice) for h in halves]
    out = []
    for g in parts:
        text = _pages_text(doc, g)
        piece = None
        if doc.kind == "pdf" and doc.pdf_bytes and any(p.table_like or p.scanned for p in g):
            piece = _pdf_slice(doc.pdf_bytes, g[0].number, g[-1].number)
        out.append(Chunk(chunk.index, g[0].number, g[-1].number, text, piece))
    return out
