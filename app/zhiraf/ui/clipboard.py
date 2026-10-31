"""Paste into the editor with formatting, and copy the corrected text out with formatting."""
import re
from html import escape
from typing import List, Optional

from PySide2.QtCore import QMimeData
from PySide2.QtGui import QTextCursor, QTextDocument

from ..documents.model import Document, Paragraph, Span
from .blockfmt import spans_from_block

__all__ = ["spans_from_block", "document_from_mime", "document_from_qtext", "paragraphs_to_html",
           "copy_to_clipboard"]

_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
_UNSAFE = re.compile(r"<script\b.*?</script\s*>|<script\b.*\Z|<img\b%s>?" % _ATTRS, re.IGNORECASE | re.DOTALL)


class _NoResourceDocument(QTextDocument):
    """Pasted HTML may point at files or network shares (a leak on Windows): load nothing, ever."""

    def loadResource(self, type, url):
        return None


def _strip_unsafe(html):
    # cosmetic only: the real protection is _NoResourceDocument
    while True:
        cleaned = _UNSAFE.sub("", html)
        if cleaned == html:
            return html
        html = cleaned
_HEADINGS = {1: "h1", 2: "h2", 3: "h3"}


def _paste_document(paragraphs):
    return Document(paragraphs, kind="paste", editable=True, path=None, saved_as="docx")


def document_from_mime(mime):
    # type: (QMimeData) -> Optional[Document]
    if mime.hasHtml():
        qdoc = _NoResourceDocument()
        qdoc.setHtml(_strip_unsafe(mime.html()))
        if qdoc.toPlainText().strip():
            return _paste_document(document_from_qtext(qdoc).paragraphs)
    if mime.hasText() and mime.text().strip():
        lines = mime.text().splitlines()
        return _paste_document([Paragraph([Span(line)] if line else []) for line in lines])
    return None


def document_from_qtext(qdoc):
    # type: (QTextDocument) -> Document
    paragraphs = []
    table_numbers = {}
    block = qdoc.begin()
    while block.isValid():
        style = _HEADINGS.get(block.blockFormat().headingLevel(), "normal")
        if style == "normal" and block.textList() is not None:
            style = "list"
        cell = None
        cursor = QTextCursor(block)
        table = cursor.currentTable()
        if table is not None:
            number = table_numbers.setdefault(table.firstPosition(), len(table_numbers))
            c = table.cellAt(cursor)
            cell = (number, c.row(), c.column())
        paragraphs.append(Paragraph(spans_from_block(block), style=style, table=cell))
        block = block.next()
    return Document(paragraphs, kind="paste", editable=True, saved_as="docx")


def _span_html(span):
    html = escape(span.text, quote=False).replace("\n", "<br>")
    for on, tag in ((span.underline, "u"), (span.italic, "i"), (span.bold, "b")):
        if on:
            html = "<%s>%s</%s>" % (tag, html, tag)
    return html


def paragraphs_to_html(paragraphs):
    # type: (List[Paragraph]) -> str
    out = []
    in_list = False
    for p in paragraphs:
        if p.style == "list" and not in_list:
            out.append("<ul>")
        elif p.style != "list" and in_list:
            out.append("</ul>")
        in_list = p.style == "list"
        body = "".join(_span_html(s) for s in p.spans)
        if p.style == "list":
            out.append("<li>%s</li>" % body)
        elif p.style in _HEADINGS.values():
            out.append("<%s>%s</%s>" % (p.style, body, p.style))
        else:
            out.append("<p>%s</p>" % body)
    if in_list:
        out.append("</ul>")
    return "".join(out)


def copy_to_clipboard(paragraphs, clipboard):
    mime = QMimeData()
    mime.setHtml(paragraphs_to_html(paragraphs))
    mime.setText("\n".join(p.text for p in paragraphs))
    clipboard.setMimeData(mime)
