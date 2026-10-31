"""Character-format properties the editor puts on marked text, and the way back from a block to spans.

Shared by the editor and the clipboard code, so neither imports the other.
"""
from PySide2.QtGui import QFont, QTextFormat

from ..documents.model import Span

MARK_PROP = QTextFormat.UserProperty + 1            # value: mark status (open, accepted, ...)
BASE_UNDERLINE_PROP = QTextFormat.UserProperty + 2  # value: bool, the underline the TEXT has without the mark
MARK_ID_PROP = QTextFormat.UserProperty + 3         # value: mark id

LINE_SEPARATOR = " "


def spans_from_block(block):
    """Formatted spans of a block; U+2028 (a line break inside a paragraph) becomes \\n."""
    heading = block.blockFormat().headingLevel() > 0   # headings are bold by style, not by the author
    spans = []
    it = block.begin()
    while not it.atEnd():
        fragment = it.fragment()
        fmt = fragment.charFormat()
        underline = bool(fmt.property(BASE_UNDERLINE_PROP)) if fmt.hasProperty(BASE_UNDERLINE_PROP) \
            else fmt.fontUnderline()
        bold = fmt.fontWeight() >= QFont.Bold and not heading
        text = fragment.text().replace(LINE_SEPARATOR, "\n")
        if spans and (spans[-1].bold, spans[-1].italic, spans[-1].underline) == (bold, fmt.fontItalic(), underline):
            spans[-1].text += text
        elif text:
            spans.append(Span(text, bold, fmt.fontItalic(), underline))
        it += 1
    return spans
