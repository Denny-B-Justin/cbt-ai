"""Read an uploaded PDF or Word file into clean text pages and split it into sections for the AI."""

from __future__ import annotations

import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import constants as C

AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{1,2}\b")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
DOCX_PAGE_CHARS = 3500
SCAN_PAGE_WEIGHT = 2600


class DocumentError(Exception):
    """A problem with the uploaded file; the message is safe to show to the user."""


@dataclass
class Page:
    number: int
    text: str
    table_like: bool = False
    scanned: bool = False


@dataclass
class Chunk:
    index: int
    first_page: int
    last_page: int
    text: str
    pdf_slice: Optional[bytes] = None

    @property
    def label(self) -> str:
        return "page %d" % self.first_page if self.first_page == self.last_page else "pages %d-%d" % (self.first_page, self.last_page)


@dataclass
class Document:
    filename: str
    kind: str                                  # "pdf" | "docx"
    pages: List[Page]
    pdf_bytes: Optional[bytes] = None
    notes: List[str] = field(default_factory=list)

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


def _drop_repeated_lines(pages: List[Page]) -> None:
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
        raise DocumentError("Please upload a PDF or Word (.docx) file.")
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > C.max_upload_bytes():
        raise DocumentError("This file is larger than %d MB. Please upload a smaller file or an extract." %
                            (C.max_upload_bytes() // (1024 * 1024)))
    doc = _read_pdf(data, filename) if suffix == ".pdf" else _read_docx(data, filename)
    if doc.n_pages > C.MAX_PAGES:
        raise DocumentError("This document has %d pages; the limit is %d. Please upload an extract." % (doc.n_pages, C.MAX_PAGES))
    if doc.n_chars < 80 and doc.kind == "docx":
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


def _docx_blocks(doc) -> List[str]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    blocks: List[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = Paragraph(child, doc).text.strip()
            if text:
                blocks.append(text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                cells: List[str] = []
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
    pages: List[Page] = []
    buf: List[str] = []
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


def _pdf_slice(pdf_bytes: bytes, first: int, last: int) -> Optional[bytes]:
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


def _with_slices(doc: Document, group: List[Page]) -> List[tuple]:
    """Pair a group of pages with the PDF pages to attach (table and scanned pages are also shown to the AI as pages).
    A group of scanned pages whose picture is too large to attach is cut in two."""
    if not (doc.kind == "pdf" and doc.pdf_bytes and any(p.table_like or p.scanned for p in group)):
        return [(group, None)]
    piece = _pdf_slice(doc.pdf_bytes, group[0].number, group[-1].number)
    if piece is not None or len(group) == 1 or not any(p.scanned for p in group):
        return [(group, piece)]
    mid = len(group) // 2
    return _with_slices(doc, group[:mid]) + _with_slices(doc, group[mid:])


def make_chunks(doc: Document, max_chars: int = C.CHUNK_CHARS) -> List[Chunk]:
    """Group consecutive pages into sections. Table pages weigh double: they produce many rows."""
    groups: List[List[Page]] = []
    cur: List[Page] = []
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

    chunks: List[Chunk] = []
    for g, piece in (pair for group in groups for pair in _with_slices(doc, group)):
        text = "\n".join("[Page %d]\n%s" % (p.number, p.text) for p in g)
        chunks.append(Chunk(len(chunks) + 1, g[0].number, g[-1].number, text, piece))
    return chunks


def split_chunk(chunk: Chunk, doc: Document) -> List[Chunk]:
    """Cut a section in two (used when the AI answer was too long). Returns [] if it cannot be split."""
    pages = [p for p in doc.pages if chunk.first_page <= p.number <= chunk.last_page]
    if len(pages) >= 2:
        mid = len(pages) // 2
        parts = [pages[:mid], pages[mid:]]
    else:
        lines = chunk.text.splitlines()
        if len(lines) < 20:
            return []
        mid = len(lines) // 2
        halves = ["\n".join(lines[:mid]), "\n".join(lines[mid:])]
        return [Chunk(chunk.index, chunk.first_page, chunk.last_page, h, chunk.pdf_slice) for h in halves]
    out = []
    for g in parts:
        text = "\n".join("[Page %d]\n%s" % (p.number, p.text) for p in g)
        piece = None
        if doc.kind == "pdf" and doc.pdf_bytes and any(p.table_like or p.scanned for p in g):
            piece = _pdf_slice(doc.pdf_bytes, g[0].number, g[-1].number)
        out.append(Chunk(chunk.index, g[0].number, g[-1].number, text, piece))
    return out
