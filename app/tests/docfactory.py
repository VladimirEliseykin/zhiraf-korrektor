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
