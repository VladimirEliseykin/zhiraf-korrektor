import os
import subprocess

import pytest
from conftest import SOFFICE, needs_soffice
from docfactory import P, R, make_docx, table
from zhiraf.documents.doc_format import extract_doc_text
from zhiraf.documents.model import DocumentError


def to_doc(docx, outdir):
    profile = "file://" + str(outdir / "lo-profile")
    subprocess.run([SOFFICE, "--headless", "--norestore", "-env:UserInstallation=" + profile,
                    "--convert-to", "doc:MS Word 97", "--outdir", str(outdir), docx], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.splitext(docx)[0] + ".doc"


@needs_soffice
def test_paragraphs_and_table_cells(tmp_path):
    docx = make_docx(tmp_path / "a.docx", P(R("Первый абзац с информацией.")), P(R("Второй абзац.")),
                     table([[P(R("Ячейка А")), P(R("Ячейка Б"))]]))
    texts = [t for t in extract_doc_text(to_doc(docx, tmp_path)) if t.strip()]
    assert texts[:2] == ["Первый абзац с информацией.", "Второй абзац."]
    assert "Ячейка А" in texts and "Ячейка Б" in texts


@needs_soffice
def test_hyperlink_field_keeps_only_visible_text(tmp_path):
    link = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> HYPERLINK '
            '"http://example.org" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + R("ссылка") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    docx = make_docx(tmp_path / "a.docx", P(R("Это "), link, R(" здесь.")))
    texts = extract_doc_text(to_doc(docx, tmp_path))
    assert "Это ссылка здесь." in texts
    assert not any("HYPERLINK" in t for t in texts)


def test_not_a_word_file(tmp_path):
    bad = tmp_path / "не_ворд.doc"
    bad.write_bytes(b"plain text, not OLE")
    with pytest.raises(DocumentError) as e:
        extract_doc_text(str(bad))
    assert "не_ворд.doc" in str(e.value)


def test_truncated_doc_file(tmp_path):
    """Truncated .doc file should raise DocumentError, not a raw exception."""
    # First, create a real .doc file using LibreOffice
    if SOFFICE is None:
        pytest.skip("LibreOffice is not installed")

    docx = make_docx(tmp_path / "a.docx", P(R("Test content.")))
    doc_path = to_doc(docx, tmp_path)

    # Read the real .doc and truncate it
    with open(doc_path, "rb") as f:
        original = f.read()

    truncated_path = tmp_path / "truncated.doc"
    truncated_path.write_bytes(original[:len(original) // 2])

    with pytest.raises(DocumentError) as e:
        extract_doc_text(str(truncated_path))
    assert "truncated.doc" in str(e.value)
