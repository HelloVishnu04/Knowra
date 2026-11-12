"""Optional real conversion tests: RUN_DOCLING_TESTS=1 with full dependencies installed.

Model/tokenizer artifacts must be cached or downloadable for PDF conversion.
"""

import os

import pytest

from app.workers.ingest import chunk_document, parse_document

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCLING_TESTS") != "1", reason="requires Docling and model artifacts"
)


@pytest.mark.parametrize("extension", ["docx", "pptx", "xlsx", "pdf"])
def test_real_document_formats(tmp_path, extension):
    path = tmp_path / f"sample.{extension}"
    phrase = "The launch is scheduled for June."
    if extension == "docx":
        from docx import Document

        doc = Document()
        doc.add_heading("Launch schedule", 1)
        doc.add_paragraph(phrase)
        doc.save(path)
    elif extension == "pptx":
        from pptx import Presentation

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Launch schedule"
        slide.placeholders[1].text = phrase
        deck.save(path)
    elif extension == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        book.active.title = "Launch schedule"
        book.active.append(["Milestone", "Date"])
        book.active.append(["Launch", "June"])
        book.save(path)
    else:
        # Minimal valid PDF fixture, with exact byte offsets for the xref table.
        stream = b"BT /F1 12 Tf 72 720 Td (The launch is scheduled for June.) Tj ET"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        ]
        data = b"%PDF-1.4\n"
        offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(len(data))
            data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
        xref = len(data)
        data += b"xref\n0 6\n0000000000 65535 f \n"
        data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
        data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
        path.write_bytes(data)
    chunks = chunk_document(parse_document(path))
    assert any("June" in chunk["content"] for chunk in chunks)
    assert all(
        "pages" in chunk["metadata"] and "sections" in chunk["metadata"]
        for chunk in chunks
    )
    if extension == "pdf":
        assert any(1 in chunk["metadata"]["pages"] for chunk in chunks)
