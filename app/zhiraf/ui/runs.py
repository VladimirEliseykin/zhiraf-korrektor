"""What the editor shows for a paragraph: text pieces with character format and mark.

Pure Python, no Qt. All offsets are Python code-point offsets (as in ReviewSession); the editor
converts them to UTF-16 units at the QTextCursor boundary with to_utf16.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..documents.model import Paragraph, Span
from ..review import ACCEPTED, MANUAL, OPEN, SKIPPED, APPLIED

SHOWN = (OPEN, ACCEPTED, MANUAL, SKIPPED)
PLAIN = (False, False, False)


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    mark: Optional[Tuple[int, str, str]] = None  # (mark.id, mark.status, mark.level)


def utf16_len(text):
    return len(text.encode("utf-16-le")) // 2


def to_utf16(text, offset):
    """Offset in UTF-16 units of the code-point offset `offset` in `text`."""
    return utf16_len(text[:offset])


def display_range(session, mark):
    """Range of the mark in the CURRENT text; an empty one grows by one character (left, else right)."""
    start, end = session.span(mark)
    if start == end:
        return (start - 1, start) if start > 0 else (0, 1)
    return start, end


def _formats(paragraph):
    result = []
    for span in paragraph.spans:
        result.extend([(span.bold, span.italic, span.underline)] * len(span.text))
    return result


def _char_formats(paragraph, session, index):
    """(text, formats): the current text and the format of each of its characters."""
    formats = _formats(paragraph)
    original = session.originals[index]
    formats += [formats[-1] if formats else PLAIN] * max(0, len(original) - len(formats))
    applied = sorted((m for m in session.marks if m.paragraph == index and m.status in APPLIED),
                     key=lambda m: (m.start, m.end))
    text, out, pos = [], [], 0
    for m in applied:
        text.append(original[pos:m.start])
        out.extend(formats[pos:m.start])
        if m.applied:
            if m.start < len(original) and m.end > m.start:
                source = formats[m.start]
            elif m.start > 0:
                source = formats[m.start - 1]   # an insertion takes the format of the previous character
            else:
                source = formats[0] if formats else PLAIN
            text.append(m.applied)
            out.extend([source] * len(m.applied))
        pos = max(pos, m.end)
    text.append(original[pos:])
    out.extend(formats[pos:len(original)])
    return "".join(text), out


def _merge(text, keys):
    runs = []
    for ch, key in zip(text, keys):
        if runs and runs[-1][1] == key:
            runs[-1][0].append(ch)
        else:
            runs.append(([ch], key))
    return [("".join(chars), key) for chars, key in runs]


def paragraph_runs(paragraph, session, index, show_checks=True):
    text, formats = _char_formats(paragraph, session, index)
    marks = [None] * len(text)
    for m in session.marks:
        if m.paragraph != index or m.status not in SHOWN or (m.level == "check" and not show_checks):
            continue
        start, end = display_range(session, m)
        for i in range(max(start, 0), min(end, len(text))):
            if marks[i] is None:
                marks[i] = (m.id, m.status, m.level)
    keys = [(f, mk) for f, mk in zip(formats, marks)]
    return [Run(t, f[0], f[1], f[2], mk) for t, (f, mk) in _merge(text, keys)]


def final_spans(paragraph, session, index):
    text, formats = _char_formats(paragraph, session, index)
    return [Span(t, *f) for t, f in _merge(text, formats)]


def final_paragraphs(doc, session):
    return [Paragraph(final_spans(p, session, i), p.style, p.table, p.has_image)
            for i, p in enumerate(doc.paragraphs)]
