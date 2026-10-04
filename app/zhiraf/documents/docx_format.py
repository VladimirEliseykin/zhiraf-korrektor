"""Word .docx: read into the document model (saving: task 6).

lxml, not xml.etree: etree renames namespace prefixes on output, and Word rejects a file whose
mc:Ignorable prefixes no longer match their declarations.
"""
import os
import re
import zipfile
from xml.sax.saxutils import escape

from lxml import etree

from .model import Document, DocumentError, Paragraph, Span
from .slots import FixedSlot, Slot

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_XML = "word/document.xml"
STYLES_XML = "word/styles.xml"
HEADING_NAME = re.compile(r"^(heading|заголовок)\s*(\d)$", re.I)
# documents come from outside: no entity expansion, no external DTDs
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


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
    return el.get(q("val"), "true").lower() not in ("0", "false", "none")


def _run_format(run):
    rpr = run.find(q("rPr"))
    return _flag(rpr, "b"), _flag(rpr, "i"), _flag(rpr, "u")


def _style_names(styles_xml):
    names = {}
    if styles_xml:
        root = etree.fromstring(styles_xml, PARSER)
        for style in root.iter(q("style")):
            name = style.find(q("name"))
            if style.get(q("styleId")) and name is not None:
                names[style.get(q("styleId"))] = name.get(q("val"), "")
    return names


def _paragraph_style(p, names):
    ppr = p.find(q("pPr"))
    if ppr is None:
        return "normal"
    style = ppr.find(q("pStyle"))
    style_id = style.get(q("val"), "") if style is not None else ""
    name = names.get(style_id, style_id).strip()
    m = HEADING_NAME.match(name) or HEADING_NAME.match(style_id)
    if m:
        return "h%d" % min(int(m.group(2)), 3)
    if name.lower() in ("title", "название"):
        return "title"
    if ppr.find(q("numPr")) is not None or name.lower().startswith(("list", "список")):
        return "list"
    return "normal"


def load_package(path):
    """(document root element, styles xml bytes or None); DocumentError with a user message."""
    try:
        with zipfile.ZipFile(path) as z:
            document = z.read(DOCUMENT_XML)
            styles = z.read(STYLES_XML) if STYLES_XML in z.namelist() else None
        return etree.fromstring(document, PARSER), styles
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))


def read_docx(path):
    root, styles = load_package(path)
    names = _style_names(styles)
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
    return "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(t) for t in texts)
