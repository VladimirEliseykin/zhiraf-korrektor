import os
import random
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


@needs_soffice
def test_hostile_input_variants(tmp_path):
    """Fuzz-test with truncations and random byte flips.

    Every malformed input must raise DocumentError, not a raw exception.
    """
    docx = make_docx(tmp_path / "a.docx", P(R("Test content.")))
    doc_path = to_doc(docx, tmp_path)

    with open(doc_path, "rb") as f:
        original = f.read()

    rng = random.Random(1234)
    tested = 0

    # Truncations at various sizes
    truncation_sizes = [
        1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048,
        len(original) // 4, len(original) // 3, len(original) // 2,
        len(original) * 2 // 3, len(original) - 1
    ]
    for size in truncation_sizes:
        if size > 0 and size < len(original):
            tested += 1
            truncated_path = tmp_path / ("trunc_%d.doc" % size)
            truncated_path.write_bytes(original[:size])
            try:
                result = extract_doc_text(str(truncated_path))
                assert isinstance(result, list), "extract_doc_text must return list[str]"
                for item in result:
                    assert isinstance(item, str), "list elements must be str"
            except DocumentError:
                pass  # Expected

    # Random byte flips in first 64 KB
    flip_region = min(65536, len(original))
    for _ in range(max(0, 200 - len(truncation_sizes))):
        tested += 1
        data = bytearray(original)
        pos = rng.randint(0, flip_region - 1)
        data[pos] ^= rng.randint(1, 255)
        flip_path = tmp_path / ("flip_%d.doc" % tested)
        flip_path.write_bytes(bytes(data))
        try:
            result = extract_doc_text(str(flip_path))
            assert isinstance(result, list), "extract_doc_text must return list[str]"
            for item in result:
                assert isinstance(item, str), "list elements must be str"
        except DocumentError:
            pass  # Expected

    assert tested >= 30, "Not enough variants tested"
