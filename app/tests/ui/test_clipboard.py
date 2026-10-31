from PySide2.QtCore import QMimeData
from PySide2.QtGui import QImage, QTextCursor, QTextDocument

from zhiraf.documents.model import Paragraph, Span
from zhiraf.ui.clipboard import copy_to_clipboard, document_from_mime, document_from_qtext, paragraphs_to_html
from zhiraf.ui.blockfmt import spans_from_block


def html_mime(html):
    mime = QMimeData()
    mime.setHtml(html)
    return mime


def text_mime(text):
    mime = QMimeData()
    mime.setText(text)
    return mime


HTML = ("<h1>Приказ</h1><p>Текст <b>жирный</b> и <i>курсив</i></p><ul><li>пункт</li></ul>"
        "<table><tr><td>ячейка</td></tr></table>")


def test_html_paragraphs_and_styles():
    doc = document_from_mime(html_mime(HTML))
    assert doc.kind == "paste" and doc.editable and doc.path is None and doc.saved_as == "docx"
    assert [p.style for p in doc.paragraphs[:3]] == ["h1", "normal", "list"]
    assert doc.paragraphs[0].text == "Приказ"
    assert Span("жирный", bold=True) in doc.paragraphs[1].spans
    assert Span("курсив", italic=True) in doc.paragraphs[1].spans
    assert doc.paragraphs[3].table == (0, 0, 0) and doc.paragraphs[3].text == "ячейка"


def test_tables_numbered_in_document_order():
    html = ("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table><p>x</p>"
            "<table><tr><td>e</td></tr></table>")
    doc = document_from_mime(html_mime(html))
    tables = {p.text: p.table for p in doc.paragraphs if p.table}
    assert tables == {"a": (0, 0, 0), "b": (0, 0, 1), "c": (0, 1, 0), "d": (0, 1, 1), "e": (1, 0, 0)}


def test_image_is_dropped():
    doc = document_from_mime(html_mime('<p>до</p><p><img src="file:///etc/passwd"></p>'
                                       '<script>\nalert(1)\n</SCRIPT>'))
    assert not any(p.has_image for p in doc.paragraphs)
    assert all("passwd" not in p.text and "alert" not in p.text for p in doc.paragraphs)
    assert doc.paragraphs[0].text == "до"
    assert doc.paragraphs[1].text == "" and not doc.paragraphs[1].has_image


def test_empty_buffer_is_none():
    assert document_from_mime(QMimeData()) is None
    assert document_from_mime(text_mime("  \r\n \t ")) is None
    assert document_from_mime(html_mime("<p>  </p>")) is None


def test_plain_text_split_by_lines():
    doc = document_from_mime(text_mime("первый\r\nвторой\nтретий"))
    assert [p.text for p in doc.paragraphs] == ["первый", "второй", "третий"]
    assert doc.kind == "paste"


def test_html_is_escaped():
    html = paragraphs_to_html([Paragraph([Span("a < b & c")])])
    assert "a &lt; b &amp; c" in html and "a < b" not in html


def test_html_structure():
    html = paragraphs_to_html([
        Paragraph([Span("Заг")], style="h2"),
        Paragraph([Span("а", bold=True), Span("б", italic=True), Span("в", underline=True)]),
        Paragraph([Span("один")], style="list"), Paragraph([Span("два")], style="list"),
        Paragraph([Span("конец")])])
    assert "<h2>Заг</h2>" in html
    assert "<b>а</b>" in html and "<i>б</i>" in html and "<u>в</u>" in html
    assert html.count("<ul>") == 1 and "<li>один</li><li>два</li>" in html
    assert "<p>конец</p>" in html


def test_copy_puts_html_and_plain(qapp):
    paragraphs = [Paragraph([Span("один", bold=True)]), Paragraph([Span("два")])]
    copy_to_clipboard(paragraphs, qapp.clipboard())
    mime = qapp.clipboard().mimeData()
    assert mime.hasHtml() and "<b>один</b>" in mime.html()
    assert mime.text() == "один\nдва"
    assert "text/html" in mime.formats() and "text/plain" in mime.formats()


def test_line_separator_becomes_newline():
    qdoc = QTextDocument()
    cursor = QTextCursor(qdoc)
    cursor.insertText("раз два")
    assert spans_from_block(qdoc.firstBlock()) == [Span("раз\nдва")]
    assert document_from_qtext(qdoc).paragraphs[0].text == "раз\nдва"


def test_empty_paragraphs_stay():
    qdoc = QTextDocument()
    qdoc.setPlainText("a\n\nb")
    assert [p.text for p in document_from_qtext(qdoc).paragraphs] == ["a", "", "b"]


def test_no_resource_is_ever_loaded(monkeypatch, tmp_path):
    from zhiraf.ui import clipboard
    calls = []
    orig = clipboard._NoResourceDocument.loadResource

    def spy(self, type, url):
        result = orig(self, type, url)
        calls.append((url.toString(), result))
        return result
    monkeypatch.setattr(clipboard._NoResourceDocument, "loadResource", spy)
    real = tmp_path / "t.png"  # a file that exists: the base class WOULD load it
    QImage(2, 2, QImage.Format_RGB32).save(str(real))
    html = ('<p background="file:///x">a</p><p><span style="background-image:url(file:///y)">b</span></p>'
            '<link rel=stylesheet href="file:///z"><table background="%s">'
            '<tr><td>c</td></tr></table>' % real.as_uri() +
            '<table background="\\\\host\\share\\a.png"><tr><td>d</td></tr></table>')
    doc = document_from_mime(html_mime(html))
    assert doc is not None
    assert calls, "Qt never asked the document for a resource: the test proves nothing"
    assert all(result is None for _, result in calls)


def test_loader_override_returns_nothing():
    from PySide2.QtCore import QUrl
    from zhiraf.ui.clipboard import _NoResourceDocument
    assert not _NoResourceDocument().loadResource(2, QUrl("file:///etc/passwd"))


def test_unclosed_script_body_dropped():
    doc = document_from_mime(html_mime("<p>до</p><script>alert(1) SECRET"))
    assert "SECRET" not in "".join(p.text for p in doc.paragraphs)


def test_img_with_gt_in_attribute():
    doc = document_from_mime(html_mime('<p>до</p><img alt=">" src=x>'))
    assert [p.text for p in doc.paragraphs] == ["до"] or "".join(p.text for p in doc.paragraphs) == "до"
