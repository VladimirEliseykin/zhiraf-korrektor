"""Word .docx: read into the document model (saving: task 6).

lxml, not xml.etree: etree renames namespace prefixes on output, and Word rejects a file whose
mc:Ignorable prefixes no longer match their declarations.
"""
import os
import re
import zipfile
from xml.sax.saxutils import escape

from lxml import etree

from .model import Document, DocumentError, Paragraph, SaveReport, Span, group_by_paragraph
from .package import read_package, write_package
from .slots import FixedSlot, Slot, apply_to_slots

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_XML = "word/document.xml"
STYLES_XML = "word/styles.xml"
HEADING_NAME = re.compile(r"^(heading|заголовок)\s*(\d)$", re.I)
# documents come from outside: no entity expansion, no external DTDs
PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


def q(tag):
    return "{%s}%s" % (W, tag)


IMAGE_TAGS = {q("drawing"), q("pict"), q("object")}
DELETED = {q("del"), q("moveFrom")}


class TextSlot(Slot):
    """The text of one w:t element."""

    def __init__(self, element, run):
        Slot.__init__(self, element.text or "")
        self.element = element
        self.run = run

    def write(self, text):
        self.text = text
        self.element.text = text
        if text != text.strip():
            self.element.set(XML_SPACE, "preserve")


class DocxFixed(FixedSlot):
    def __init__(self, text, run):
        FixedSlot.__init__(self, text)
        self.run = run


def _owner_paragraph(el):
    while el is not None and el.tag != q("p"):
        el = el.getparent()
    return el


def _deleted(el, p):
    """Inside tracked deleted or moved-away text of this paragraph."""
    el = el.getparent()
    while el is not None and el is not p:
        if el.tag in DELETED:
            return True
        el = el.getparent()
    return False


def paragraph_slots(p):
    """Text slots of a w:p in reading order and whether it holds a picture; text boxes are left out."""
    slots, image = [], False
    for el in p.iter():
        tag = el.tag
        if el is p or not isinstance(tag, str):
            continue
        if tag in IMAGE_TAGS:
            if _owner_paragraph(el.getparent()) is p:
                image = True
            continue
        run = el.getparent()
        if run is None or run.tag != q("r") or _owner_paragraph(run) is not p or _deleted(el, p):
            continue
        if tag == q("t"):
            slots.append(TextSlot(el, run))
        elif tag == q("tab"):
            slots.append(DocxFixed("\t", run))
        elif tag in (q("br"), q("cr")):
            slots.append(DocxFixed("\n", run))
        elif tag == q("noBreakHyphen"):
            slots.append(DocxFixed("-", run))
    return slots, image


def iter_paragraphs(body):
    """(w:p, table position or None) in document order; cells of tables (also nested) included."""
    tables = [0]

    def walk(container, position):
        for child in container:
            if child.tag == q("p"):
                yield child, position
            elif child.tag == q("tbl"):
                number = tables[0]
                tables[0] += 1
                for r, tr in enumerate(child.findall(q("tr"))):
                    for c, tc in enumerate(tr.findall(q("tc"))):
                        for item in walk(tc, (number, r, c)):
                            yield item
            elif child.tag == q("sdt"):
                content = child.find(q("sdtContent"))
                if content is not None:
                    for item in walk(content, position):
                        yield item
            elif child.tag in (q("customXml"), q("ins")):
                for item in walk(child, position):
                    yield item

    return walk(body, None)


def _flag(rpr, tag):
    el = rpr.find(q(tag)) if rpr is not None else None
    if el is None:
        return False
    return el.get(q("val"), "true").lower() not in ("0", "false", "off", "none")


def _run_format(run):
    rpr = run.find(q("rPr"))
    return _flag(rpr, "b"), _flag(rpr, "i"), _flag(rpr, "u")


def _paragraph_style(p, names):
    ppr = p.find(q("pPr"))
    if ppr is None:
        return "normal"
    style = ppr.find(q("pStyle"))
    style_id = style.get(q("val"), "") if style is not None else ""
    name = names.get(style_id, style_id).strip()
    m = HEADING_NAME.match(name) or HEADING_NAME.match(style_id)
    if m:
        return "h%d" % max(1, min(int(m.group(2)), 3))
    if name.lower() in ("title", "название"):
        return "title"
    if ppr.find(q("numPr")) is not None or name.lower().startswith(("list", "список")):
        return "list"
    return "normal"


def load_package(path):
    """(document root element, styles xml bytes or None); DocumentError with a user message."""
    try:
        with zipfile.ZipFile(path) as z:
            # Check file sizes before reading (only for parts we actually parse)
            for name in (DOCUMENT_XML, STYLES_XML):
                try:
                    info = z.getinfo(name)
                    if info.file_size > 100 * 1024 * 1024:
                        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))
                except KeyError:
                    pass  # STYLES_XML is optional

            document = z.read(DOCUMENT_XML)
            styles = z.read(STYLES_XML) if STYLES_XML in z.namelist() else None

        # Parse document with safety checks
        root = _parse_xml_safe(document, path)

        # Check that w:body exists
        body = root.find(q("body"))
        if body is None:
            raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))

        # Extract style names from styles.xml using the same safety checks
        names = _extract_style_names(styles, path)

        return root, names
    except DocumentError:
        raise
    except (zipfile.BadZipFile, KeyError, OSError, ValueError,
            RuntimeError, NotImplementedError, EOFError, RecursionError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))


def read_docx(path):
    root, names = load_package(path)
    paragraphs = []
    for p, position in iter_paragraphs(root.find(q("body"))):
        slots, image = paragraph_slots(p)
        spans = []
        for slot in slots:
            fmt = _run_format(slot.run)
            if spans and (spans[-1].bold, spans[-1].italic, spans[-1].underline) == fmt:
                spans[-1].text += slot.text
            else:
                spans.append(Span(slot.text, *fmt))
        paragraphs.append(Paragraph(spans, _paragraph_style(p, names), position, image))
    return Document(paragraphs, kind="docx", path=path, editable=False, saved_as="docx")


CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Default Extension="png" ContentType="image/png"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument'
                 '.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument'
                 '.wordprocessingml.styles+xml"/></Types>')
PACKAGE_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'officeDocument" Target="word/document.xml"/></Relationships>')
DOCUMENT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                 'styles" Target="styles.xml"/></Relationships>')
DEFAULT_STYLES = ('<w:styles xmlns:w="%s"><w:style w:type="paragraph" w:styleId="Heading1">'
                  '<w:name w:val="heading 1"/></w:style></w:styles>' % W)
DOCUMENT_TEMPLATE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<w:document xmlns:w="%s" '
                     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                     'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                     'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14">'
                     '<w:body>%%s<w:sectPr/></w:body></w:document>' % W)


def write_docx_package(path, body_xml, styles_xml=None, extra=None):
    """A minimal valid .docx with the given w:body content."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", PACKAGE_RELS)
        z.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        z.writestr(DOCUMENT_XML, DOCUMENT_TEMPLATE % body_xml)
        z.writestr(STYLES_XML, styles_xml or DEFAULT_STYLES)
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def plain_paragraphs_xml(texts):
    """w:p elements for plain paragraphs (used when a .doc can only be saved as a new .docx)."""
    def flat(text):  # a tab or line break inside a w:t is not valid there: a space keeps the words apart
        return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(flat(t)) for t in texts)


def _parse_xml_safe(xml_bytes, filename):
    """Parse XML bytes with DOCTYPE refusal and error wrapping (used by load_package and save_docx)."""
    try:
        # Check for DOCTYPE which enables entity attacks (byte check first, fast path)
        if b"<!DOCTYPE" in xml_bytes:
            raise DocumentError("Не удалось открыть «%s»: документ содержит неподдерживаемые конструкции XML." % os.path.basename(filename))

        # Parse document
        root = etree.fromstring(xml_bytes, PARSER)

        # Check for DOCTYPE in parsed tree (catches UTF-16 and other encodings)
        # docinfo.doctype is empty string for normal docs, non-empty for docs with DOCTYPE
        if root.getroottree().docinfo.doctype:
            raise DocumentError("Не удалось открыть «%s»: документ содержит неподдерживаемые конструкции XML." % os.path.basename(filename))

        return root
    except DocumentError:
        raise
    except (etree.XMLSyntaxError, ValueError, RuntimeError, NotImplementedError, EOFError, RecursionError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(filename))


def _extract_style_names(styles_xml, filename):
    """Parse styles.xml and extract style names; uses _parse_xml_safe."""
    if not styles_xml:
        return {}
    styles_root = _parse_xml_safe(styles_xml, filename)
    names = {}
    for style in styles_root.iter(q("style")):
        name = style.find(q("name"))
        if style.get(q("styleId")) and name is not None:
            names[style.get(q("styleId"))] = name.get(q("val"), "")
    return names


def save_docx(doc, replacements, dst):
    """Copy the original package; only characters of the fixes change in word/document.xml."""
    try:
        infos, blobs = read_package(doc.path)
    except DocumentError:
        raise
    except KeyError:
        raise DocumentError("Не удалось сохранить «%s»: файл повреждён или защищён паролем." % os.path.basename(doc.path))

    try:
        root = _parse_xml_safe(blobs[DOCUMENT_XML], doc.path)
    except KeyError:
        raise DocumentError("Не удалось сохранить «%s»: файл повреждён или защищён паролем." % os.path.basename(doc.path))

    body = root.find(q("body"))
    if body is None:
        raise DocumentError("Не удалось сохранить «%s»: файл повреждён или защищён паролем." % os.path.basename(doc.path))

    paragraphs = [p for p, _ in iter_paragraphs(body)]

    # Validate that document hasn't changed: check paragraph count and slot text
    if len(paragraphs) != len(doc.paragraphs):
        raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

    # Check for replacements to paragraphs that don't exist, and validate slot text matches
    for index, reps in group_by_paragraph(replacements).items():
        if index >= len(paragraphs):
            raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

        slots, _ = paragraph_slots(paragraphs[index])
        slot_text = "".join(slot.text for slot in slots)
        if slot_text != doc.paragraphs[index].text:
            raise DocumentError("Документ «%s» изменился после открытия. Откройте его заново и проверьте ещё раз." % os.path.basename(doc.path))

    applied, skipped = 0, []
    for index, reps in group_by_paragraph(replacements).items():
        slots, _ = paragraph_slots(paragraphs[index])
        for r in sorted(reps, key=lambda r: (r.start, r.end), reverse=True):
            if apply_to_slots(slots, r.start, r.end, r.text):
                applied += 1
            else:
                skipped.append(r)
    blobs[DOCUMENT_XML] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    write_package(dst, infos, blobs)
    return SaveReport(dst, applied, sorted(skipped, key=lambda r: (r.paragraph, r.start)))
