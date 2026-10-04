"""Build small Word and ODF documents for tests, with the XML shapes Word itself writes."""
import zipfile
from xml.sax.saxutils import escape

from zhiraf.documents import docx_format

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
TAB = "<w:r><w:tab/></w:r>"
BR = "<w:r><w:br/></w:r>"


def R(text, bold=False, italic=False, underline=False):
    props = "".join(tag for tag, on in (("<w:b/>", bold), ("<w:i/>", italic), ('<w:u w:val="single"/>', underline)) if on)
    rpr = "<w:rPr>%s</w:rPr>" % props if props else ""
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(text))


def P(*runs, style=None, numbered=False):
    ppr = ""
    if style or numbered:
        ppr = "<w:pPr>%s%s</w:pPr>" % ('<w:pStyle w:val="%s"/>' % style if style else "",
                                        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else "")
    return "<w:p>%s%s</w:p>" % (ppr, "".join(runs))


def table(rows):
    cells = lambda row: "".join("<w:tc><w:tcPr/>%s</w:tc>" % cell for cell in row)
    return "<w:tbl><w:tblPr/>%s</w:tbl>" % "".join("<w:tr>%s</w:tr>" % cells(row) for row in rows)


def make_docx(path, *paragraphs, styles_xml=None):
    docx_format.write_docx_package(str(path), "".join(paragraphs), styles_xml=styles_xml,
                                   extra={"word/media/image1.png": PNG})
    return str(path)


def zip_entries(path):
    with zipfile.ZipFile(str(path)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


ODF = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
}
ODF_DECL = " ".join('xmlns:%s="%s"' % kv for kv in ODF.items())
BOLD_STYLE = ('<style:style style:name="T1" style:family="text">'
              '<style:text-properties fo:font-weight="bold"/></style:style>')


def OP(*parts, style=None):
    attr = ' text:style-name="%s"' % style if style else ""
    return "<text:p%s>%s</text:p>" % (attr, "".join(parts))


def OH(text, level):
    return '<text:h text:outline-level="%d">%s</text:h>' % (level, escape(text))


def OSPAN(text, style):
    return '<text:span text:style-name="%s">%s</text:span>' % (style, escape(text))


def make_odt(path, body_xml, auto_styles=BOLD_STYLE):
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s office:version="1.2">'
               '<office:automatic-styles>%s</office:automatic-styles><office:body><office:text>%s'
               '</office:text></office:body></office:document-content>' % (ODF_DECL, auto_styles, body_xml))
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        z.writestr("META-INF/manifest.xml", manifest, zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", content, zipfile.ZIP_DEFLATED)
        z.writestr("Pictures/image1.png", PNG, zipfile.ZIP_DEFLATED)
    return str(path)
