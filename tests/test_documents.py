import io

import pymupdf
import pytest

from utils import constants as C
from utils.documents import DocumentError, make_chunks, read_document, split_chunk


def pdf_with(pages, blank=()):
    doc = pymupdf.open()
    for i, lines in enumerate(pages):
        page = doc.new_page()
        if i not in blank:
            for k, text in enumerate(lines):
                page.insert_text((50, 60 + 14 * k), text, fontsize=9)
    return doc.tobytes()


def unique_pages(n, rows=8):
    return [["Programme %d-%d budget line item %d" % (i, k, i * 100 + k) for k in range(rows)] for i in range(n)]


def test_reads_a_pdf_and_rebuilds_table_rows(green_pdf):
    doc = read_document(green_pdf, "green.pdf")
    assert doc.kind == "pdf" and doc.n_pages == 1 and doc.notes == []
    text = doc.pages[0].text
    assert "Solar power programme" in text and "120.0" in text
    assert "0201 |" in text, "table cells of one row stay on one line"


def test_reads_a_word_file(project_docx):
    doc = read_document(project_docx, "project.docx")
    assert doc.kind == "docx" and doc.n_pages == 1
    assert "Sea walls and drainage | " in doc.pages[0].text and doc.pages[0].text.count("|") >= 15
    assert doc.pdf_bytes is None and make_chunks(doc)[0].pdf_slice is None


@pytest.mark.parametrize("name,data,message", [
    ("notes.txt", b"hello", "PDF or Word"),
    ("empty.pdf", b"", "empty"),
    ("broken.pdf", b"%PDF-1.4 this is not a pdf", "could not open"),
    ("broken.docx", b"not a zip", "could not open"),
])
def test_rejects_unusable_files(name, data, message):
    with pytest.raises(DocumentError, match=message):
        read_document(data, name)


def test_rejects_large_files(monkeypatch):
    monkeypatch.setenv(C.ENV_MAX_UPLOAD_MB, "1")
    with pytest.raises(DocumentError, match="larger than 1 MB"):
        read_document(b"0" * (1024 * 1024 + 1), "big.pdf")


def test_rejects_password_protected_pdf():
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 60), "secret text for the page")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    with pytest.raises(DocumentError, match="password"):
        read_document(data, "locked.pdf")


def test_rejects_too_many_pages(monkeypatch):
    monkeypatch.setattr(C, "MAX_PAGES", 5)
    with pytest.raises(DocumentError, match="limit"):
        read_document(pdf_with(unique_pages(6)), "long.pdf")


def test_repeated_headers_and_footers_are_removed():
    pages = [["REPUBLIC OF EXAMPLIA BUDGET 2025"] + ["Programme %d-%d budget line item %d" % (i, k, i * 50 + k) for k in range(8)]
             + ["Page footer text"] for i in range(10)]
    doc = read_document(pdf_with(pages), "headers.pdf")
    assert all("REPUBLIC OF EXAMPLIA" not in p.text and "Page footer" not in p.text for p in doc.pages)
    assert "Programme 3-2" in doc.pages[3].text


def test_a_single_blank_page_is_not_worth_a_warning():
    doc = read_document(pdf_with(unique_pages(10), blank={3}), "one_blank.pdf")
    assert doc.notes == [] and sum(p.scanned for p in doc.pages) == 1


def test_scanned_pages_are_reported_and_shown_to_the_ai_as_pictures():
    doc = read_document(pdf_with(unique_pages(40), blank=set(range(40))), "scan.pdf")
    assert any("no selectable text" in n for n in doc.notes)
    chunks = make_chunks(doc)
    assert len(chunks) >= 4 and all(c.pdf_slice for c in chunks), "scanned pages are sent as PDF pages"
    assert [(c.first_page, c.last_page) for c in chunks][0][0] == 1 and chunks[-1].last_page == 40


def test_some_scanned_pages_get_a_count():
    doc = read_document(pdf_with(unique_pages(20), blank={2, 5, 9}), "partly.pdf")
    assert doc.notes and "3 page(s)" in doc.notes[0]


def test_chunks_cover_every_page_once_and_in_order():
    doc = read_document(pdf_with(unique_pages(60, rows=40)), "long.pdf")
    chunks = make_chunks(doc, max_chars=3000)
    assert len(chunks) > 3
    pages = []
    for c in chunks:
        pages += list(range(c.first_page, c.last_page + 1))
        assert "[Page %d]" % c.first_page in c.text
    assert pages == list(range(1, 61))
    assert [c.index for c in chunks] == list(range(1, len(chunks) + 1))


def test_table_pages_are_attached_as_pdf_pages(green_pdf):
    doc = read_document(green_pdf, "green.pdf")
    doc.pages[0].table_like = True
    chunk = make_chunks(doc)[0]
    assert chunk.pdf_slice and chunk.pdf_slice[:4] == b"%PDF"
    assert pymupdf.open(stream=chunk.pdf_slice, filetype="pdf").page_count == 1


def test_split_chunk_halves_a_section():
    doc = read_document(pdf_with(unique_pages(8, rows=30)), "s.pdf")
    chunk = make_chunks(doc, max_chars=10 ** 6)[0]
    assert (chunk.first_page, chunk.last_page) == (1, 8)
    parts = split_chunk(chunk, doc)
    assert [(p.first_page, p.last_page) for p in parts] == [(1, 4), (5, 8)]


def test_split_chunk_cuts_a_single_long_page_by_lines():
    doc = read_document(pdf_with([["Programme 1-%d budget line item %d" % (k, k) for k in range(60)]]), "one.pdf")
    chunk = make_chunks(doc)[0]
    parts = split_chunk(chunk, doc)
    assert len(parts) == 2 and parts[0].text != parts[1].text


def test_a_short_single_page_cannot_be_split():
    doc = read_document(pdf_with([["Programme 1-%d budget line item %d" % (k, k) for k in range(5)]]), "short.pdf")
    assert split_chunk(make_chunks(doc)[0], doc) == []


def test_word_files_are_cut_into_pseudo_pages(tmp_path):
    import docx
    d = docx.Document()
    for i in range(200):
        d.add_paragraph("Paragraph %d about the programme budget with enough words to fill the line %d" % (i, i))
    buf = io.BytesIO()
    d.save(buf)
    doc = read_document(buf.getvalue(), "long.docx")
    assert doc.n_pages > 3 and all(p.number == i + 1 for i, p in enumerate(doc.pages))
