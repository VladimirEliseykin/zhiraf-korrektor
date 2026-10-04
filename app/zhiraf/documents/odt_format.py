"""OpenDocument .odt: read into the document model and save corrected copies in place.

Text of an ODF paragraph lives in element .text and in the .tail of child elements; spaces may be
<text:s text:c="n"/>, tabs <text:tab/>, breaks <text:line-break/> - those are fixed slots.
"""
import os
import zipfile

from lxml import etree

from .docx_format import PARSER, _parse_xml_safe
from .model import Document, DocumentError, Paragraph, SaveReport, Span, group_by_paragraph
from .package import read_package, write_package
from .slots import FixedSlot, Slot, apply_to_slots

TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
CONTENT_XML = "content.xml"
STYLES_XML = "styles.xml"
MAX_SIZE = 100 * 1024 * 1024  # 100 MB


def t(tag):
    return "{%s}%s" % (TEXT, tag)


def tb(tag):
    return "{%s}%s" % (TABLE, tag)


class NodeSlot(Slot):
    """The .text or .tail of an element."""

    def __init__(self, owner, attr, fmt):
        Slot.__init__(self, getattr(owner, attr) or "")
        self.owner, self.attr, self.fmt = owner, attr, fmt

    def write(self, text):
        self.text = text
        setattr(self.owner, self.attr, text)


class OdtFixed(FixedSlot):
    def __init__(self, text, fmt):
        FixedSlot.__init__(self, text)
        self.fmt = fmt


def _text_styles(*roots):
    """style name -> (bold, italic, underline) with None for 'not set'."""
    styles = {}
    for root in roots:
        if root is None:
            continue
        for st in root.iter("{%s}style" % STYLE):
            props = st.find("{%s}text-properties" % STYLE)
            if props is None:
                continue
            weight = props.get("{%s}font-weight" % FO)
            italic = props.get("{%s}font-style" % FO)
            underline = props.get("{%s}text-underline-style" % STYLE)
            styles[st.get("{%s}name" % STYLE)] = (
                None if weight is None else (weight == "bold" or weight.isdigit() and int(weight) >= 600),
                None if italic is None else italic == "italic",
                None if underline is None else underline != "none")
    return styles


def _format(el, inherited, styles):
    own = styles.get(el.get(t("style-name")))
    if not own:
        return inherited
    return tuple(o if o is not None else i for o, i in zip(own, inherited))


def paragraph_slots(p, styles):
    slots, image = [], [False]

    def add(owner, attr, fmt):
        if getattr(owner, attr):
            slots.append(NodeSlot(owner, attr, fmt))

    def walk(el, fmt):
        add(el, "text", fmt)
        for child in el:
            if not isinstance(child.tag, str):
                add(child, "tail", fmt)
                continue
            if child.tag in (t("span"), t("a")):
                walk(child, _format(child, fmt, styles))
            elif child.tag == t("s"):
                try:
                    count = int(child.get(t("c"), "1"))
                except (ValueError, TypeError):
                    count = 1
                slots.append(OdtFixed(" " * count, fmt))
            elif child.tag == t("tab"):
                slots.append(OdtFixed("\t", fmt))
            elif child.tag == t("line-break"):
                slots.append(OdtFixed("\n", fmt))
            elif child.tag == "{%s}frame" % DRAW:
                image[0] = True
            add(child, "tail", fmt)  # notes, bookmarks, frames: their content is not paragraph text

    walk(p, _format(p, (False, False, False), styles))
    return slots, image[0]


def _nearest(el, tag):
    el = el.getparent()
    while el is not None and el.tag != tag:
        el = el.getparent()
    return el


def iter_paragraphs(office_text):
    """(text:p or text:h, table position or None, in a list) in document order."""
    tables = [0]

    def walk(container, position, in_list):
        for child in container:
            if child.tag in (t("p"), t("h")):
                yield child, position, in_list
            elif child.tag == t("list"):
                for item in child:
                    for found in walk(item, position, True):
                        yield found
            elif child.tag == tb("table"):
                number = tables[0]
                tables[0] += 1
                rows = [r for r in child.iter(tb("table-row")) if _nearest(r, tb("table")) is child]
                for r, row in enumerate(rows):
                    for c, cell in enumerate(row.findall(tb("table-cell"))):
                        for found in walk(cell, (number, r, c), False):
                            yield found
            elif child.tag == t("section"):
                for found in walk(child, position, in_list):
                    yield found

    return walk(office_text, None, False)


def _check_sizes(path):
    """Check file sizes BEFORE reading (only for parts we actually parse)."""
    try:
        with zipfile.ZipFile(path) as z:
            for name in (CONTENT_XML, STYLES_XML):
                try:
                    info = z.getinfo(name)
                    if info.file_size > MAX_SIZE:
                        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))
                except KeyError:
                    pass  # STYLES_XML is optional
    except DocumentError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError, EOFError, RecursionError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))


def _roots(blobs, path):
    """Parse content.xml and styles.xml with safe parsing."""
    if CONTENT_XML not in blobs:
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))

    content_blob = blobs[CONTENT_XML]
    content = _parse_xml_safe(content_blob, path)

    styles = None
    if STYLES_XML in blobs:
        styles_blob = blobs[STYLES_XML]
        styles = _parse_xml_safe(styles_blob, path)

    return content, _text_styles(content, styles)


def _body(content):
    return content.find("{%s}body/{%s}text" % (OFFICE, OFFICE))


def read_odt(path):
    _check_sizes(path)

    try:
        _, blobs = read_package(path)
    except DocumentError:
        raise
    except (KeyError, OSError, RuntimeError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))

    try:
        content, styles = _roots(blobs, path)
        body = _body(content)
        if body is None:
            raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))
    except DocumentError:
        raise

    paragraphs = []
    for p, position, in_list in iter_paragraphs(body):
        slots, image = paragraph_slots(p, styles)
        spans = []
        for slot in slots:
            fmt = tuple(bool(x) for x in slot.fmt)
            if spans and (spans[-1].bold, spans[-1].italic, spans[-1].underline) == fmt:
                spans[-1].text += slot.text
            else:
                spans.append(Span(slot.text, *fmt))
        if p.tag == t("h"):
            try:
                level = int(p.get(t("outline-level"), "1"))
            except (ValueError, TypeError):
                level = 1
            style = "h%d" % min(level, 3)
        else:
            style = "list" if in_list else "normal"
        paragraphs.append(Paragraph(spans, style, position, image))
    return Document(paragraphs, kind="odt", path=path, editable=False, saved_as="odt")


def save_odt(doc, replacements, dst):
    """Copy the original package; only characters of the fixes change in content.xml."""
    _check_sizes(doc.path)

    try:
        infos, blobs = read_package(doc.path)
    except DocumentError:
        raise
    except (KeyError, OSError, RuntimeError):
        raise DocumentError("Не удалось сохранить «%s»: файл повреждён или защищён паролем." % os.path.basename(doc.path))

    try:
        content, styles = _roots(blobs, doc.path)
        body = _body(content)
        if body is None:
            raise DocumentError("Не удалось сохранить «%s»: файл повреждён или защищён паролем." % os.path.basename(doc.path))
    except DocumentError:
        raise

    paragraphs = [p for p, _, _ in iter_paragraphs(body)]

    # Validate that document hasn't changed: check paragraph count and slot text
    if len(paragraphs) != len(doc.paragraphs):
        raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

    # Check for replacements to paragraphs that don't exist, and validate slot text matches
    for index, reps in group_by_paragraph(replacements).items():
        if index >= len(paragraphs):
            raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

        slots, _ = paragraph_slots(paragraphs[index], styles)
        slot_text = "".join(slot.text for slot in slots)
        if slot_text != doc.paragraphs[index].text:
            raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

    applied, skipped = 0, []
    for index, reps in group_by_paragraph(replacements).items():
        slots, _ = paragraph_slots(paragraphs[index], styles)
        for r in sorted(reps, key=lambda r: (r.start, r.end), reverse=True):
            if apply_to_slots(slots, r.start, r.end, r.text):
                applied += 1
            else:
                skipped.append(r)

    try:
        blobs[CONTENT_XML] = etree.tostring(content, xml_declaration=True, encoding="UTF-8")
        write_package(dst, infos, blobs)
    except DocumentError:
        raise
    except (OSError, RuntimeError):
        raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе." % os.path.basename(dst))

    return SaveReport(dst, applied, sorted(skipped, key=lambda r: (r.paragraph, r.start)))
