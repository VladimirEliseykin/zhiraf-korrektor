"""One model for every document format: paragraphs made of formatted spans."""
import collections
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


class DocumentError(Exception):
    """A file that cannot be opened or saved; the message is shown to the user as is."""


class UnsupportedFormat(DocumentError):
    pass


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class Paragraph:
    spans: List[Span]
    style: str = "normal"                       # normal | title | h1 | h2 | h3 | list
    table: Optional[Tuple[int, int, int]] = None  # (table number, row, column) for text in a table cell
    has_image: bool = False

    @property
    def text(self):
        return "".join(s.text for s in self.spans)


@dataclass
class Document:
    paragraphs: List[Paragraph]
    kind: str                       # docx | odt | doc | txt | paste
    path: Optional[str] = None
    editable: bool = True           # False: an opened file changes only through marks
    saved_as: Optional[str] = None  # extension of the corrected copy
    notice: Optional[str] = None    # what the user must know (e.g. .doc saved as .docx)
    source: Any = None              # format-specific data for saving in place


@dataclass
class Replacement:
    """Characters [start, end) of a paragraph's ORIGINAL text become text ("" deletes, start == end inserts)."""
    paragraph: int
    start: int
    end: int
    text: str


@dataclass
class SaveReport:
    path: str
    applied: int
    skipped: List[Replacement] = field(default_factory=list)  # fixes that could not be placed safely


def apply_replacements(text, replacements):
    for r in sorted(replacements, key=lambda r: (r.start, r.end), reverse=True):
        text = text[:r.start] + r.text + text[r.end:]
    return text


def group_by_paragraph(replacements):
    groups = collections.OrderedDict()
    for r in replacements:
        groups.setdefault(r.paragraph, []).append(r)
    return groups


def corrected_path(path, ext=None):
    folder, name = os.path.split(path)
    stem, old_ext = os.path.splitext(name)
    ext = "." + (ext or old_ext.lstrip("."))
    candidate = os.path.join(folder, "%s (исправлено)%s" % (stem, ext))
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, "%s (исправлено %d)%s" % (stem, n, ext))
        n += 1
    return candidate
