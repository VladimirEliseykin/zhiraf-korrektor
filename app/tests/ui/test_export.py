import os

import pytest
from PySide2.QtGui import QGuiApplication

from docfactory import P, R, make_docx
from zhiraf.documents.model import Document, DocumentError, Paragraph, Span
from zhiraf.documents.opener import open_document
from zhiraf.review import ReviewSession
from zhiraf.ui import export
from zhiraf.ui.runs import final_paragraphs


def opened(tmp_path):
    path = make_docx(tmp_path / "a.docx", P(R("Это "), R("жирноее", bold=True), R(" слово.")), P(R("Второй.")))
    doc = open_document(path)
    session = ReviewSession([p.text for p in doc.paragraphs])
    start = doc.paragraphs[0].text.index("жирноее")
    session.add_findings(0, 0, [{"start": start, "end": start + 7, "level": "error", "rule": "R",
                                 "fix": "жирное", "message": "m"}])
    session.accept()
    return doc, session


def texts(doc, session):
    return [p.text for p in final_paragraphs(doc, session)]


def test_save_corrected_copy_keeps_formatting(tmp_path):
    doc, session = opened(tmp_path)
    report = export.save_corrected_copy(doc, session)
    saved = open_document(report.path)
    assert saved.paragraphs[0].text == "Это жирное слово."
    assert any(s.bold and "жирное" in s.text for s in saved.paragraphs[0].spans)


def test_save_as_odt(tmp_path, qapp):
    doc, session = opened(tmp_path)
    dst = str(tmp_path / "x.odt")
    export.save_as(doc, session, dst)
    assert [p.text for p in open_document(dst).paragraphs] == texts(doc, session)
    assert not os.path.exists(dst + ".part")


def test_save_as_txt(tmp_path):
    doc, session = opened(tmp_path)
    dst = str(tmp_path / "x.txt")
    export.save_as(doc, session, dst)
    raw = open(dst, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    assert raw.decode("utf-8-sig").split("\r\n") == texts(doc, session)


def test_save_as_pdf(tmp_path, qapp):
    doc, session = opened(tmp_path)
    dst = str(tmp_path / "x.pdf")
    export.save_as(doc, session, dst)
    data = open(dst, "rb").read()
    assert data.startswith(b"%PDF") and len(data) > 0


def test_paste_to_docx(tmp_path):
    doc = Document([Paragraph([Span("Привет "), Span("мир", bold=True)]), Paragraph([Span("пункт")], style="list")],
                   kind="paste", saved_as="docx")
    session = ReviewSession([p.text for p in doc.paragraphs])
    dst = str(tmp_path / "p.docx")
    export.save_as(doc, session, dst)
    back = open_document(dst)
    assert back.paragraphs[0].text == "Привет мир"
    assert any(s.bold and s.text == "мир" for s in back.paragraphs[0].spans)
    assert back.paragraphs[1].text == "• пункт"


def test_paste_without_destination():
    doc = Document([Paragraph([Span("а")])], kind="paste", saved_as="docx")
    with pytest.raises(DocumentError, match="куда сохранить"):
        export.save_corrected_copy(doc, ReviewSession(["а"]))


def test_refuses_source(tmp_path):
    doc, session = opened(tmp_path)
    for dst in (doc.path, os.path.join(str(tmp_path), ".", "a.docx")):
        with pytest.raises(DocumentError, match="не перезаписывается"):
            export.save_as(doc, session, dst)
    with pytest.raises(DocumentError, match="не перезаписывается"):
        export.save_as(doc, session, str(tmp_path / "A.txt").replace("A.txt", "a.docx"))


def test_unknown_extension(tmp_path):
    doc, session = opened(tmp_path)
    with pytest.raises(DocumentError):
        export.save_as(doc, session, str(tmp_path / "x.rtf"))


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_no_access(tmp_path):
    doc, session = opened(tmp_path)
    folder = tmp_path / "ro"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        with pytest.raises(DocumentError, match="Не удалось сохранить «x.txt»"):
            export.save_as(doc, session, str(folder / "x.txt"))
    finally:
        folder.chmod(0o700)
    assert not list(folder.glob("*.part"))


def test_part_removed_on_other_error(tmp_path, monkeypatch):
    doc, session = opened(tmp_path)
    dst = str(tmp_path / "x.txt")

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(export.os, "replace", boom)
    with pytest.raises(DocumentError):
        export.save_as(doc, session, dst)
    assert not os.path.exists(dst + ".part")


def test_needs_overwrite(tmp_path):
    doc, session = opened(tmp_path)
    other = tmp_path / "o.txt"
    other.write_text("x")
    assert export.needs_overwrite_confirmation(str(other), doc)
    assert not export.needs_overwrite_confirmation(str(tmp_path / "new.txt"), doc)
    assert not export.needs_overwrite_confirmation(doc.path, doc)


def test_copy_corrected(tmp_path, qapp):
    doc, session = opened(tmp_path)
    clipboard = QGuiApplication.clipboard()
    export.copy_corrected(doc, session, clipboard)
    mime = clipboard.mimeData()
    assert mime.text() == "\n".join(texts(doc, session))
    assert "<b>" in mime.html()
