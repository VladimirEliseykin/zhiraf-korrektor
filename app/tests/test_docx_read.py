from docfactory import BR, P, R, TAB, make_docx, table
from zhiraf.documents import opener
from zhiraf.documents.docx_format import read_docx
from zhiraf.documents.model import DocumentError

import pytest


def test_paragraph_text_and_formatting(tmp_path):
    path = make_docx(tmp_path / "a.docx", P(R("Важный ", bold=True), R("текст", italic=True), R(" и всё")))
    doc = read_docx(path)
    assert doc.kind == "docx" and doc.editable is False and doc.saved_as == "docx"
    p = doc.paragraphs[0]
    assert p.text == "Важный текст и всё"
    assert [(s.text, s.bold, s.italic) for s in p.spans] == [("Важный ", True, False), ("текст", False, True),
                                                             (" и всё", False, False)]


def test_runs_with_same_format_merge_into_one_span(tmp_path):
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Раз"), R("два"))))
    assert len(doc.paragraphs[0].spans) == 1


def test_headings_lists_and_tables(tmp_path):
    path = make_docx(tmp_path / "a.docx",
                     P(R("Введение"), style="Heading1"),
                     P(R("Пункт"), numbered=True),
                     table([[P(R("Ячейка А")), P(R("Ячейка Б"))]]),
                     P(R("После таблицы")))
    doc = read_docx(path)
    assert [(p.text, p.style, p.table) for p in doc.paragraphs] == [
        ("Введение", "h1", None), ("Пункт", "list", None),
        ("Ячейка А", "normal", (0, 0, 0)), ("Ячейка Б", "normal", (0, 0, 1)), ("После таблицы", "normal", None)]


def test_heading_found_by_style_name_for_russian_word(tmp_path):
    styles = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="Заголовок 2"/></w:style></w:styles>')
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Раздел"), style="2"), styles_xml=styles))
    assert doc.paragraphs[0].style == "h2"


def test_tabs_and_breaks_are_part_of_the_text(tmp_path):
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("А"), TAB, R("Б"), BR, R("В"))))
    assert doc.paragraphs[0].text == "А\tБ\nВ"


def test_deleted_and_moved_text_is_not_read(tmp_path):
    deleted = '<w:del w:id="1" w:author="x"><w:r><w:delText>удалено </w:delText></w:r></w:del>'
    moved = '<w:moveFrom w:id="2" w:author="x"><w:r><w:t>перенесено </w:t></w:r></w:moveFrom>'
    inserted = '<w:ins w:id="3" w:author="x">%s</w:ins>' % R("вставлено ")
    doc = read_docx(make_docx(tmp_path / "a.docx", P(deleted, moved, inserted, R("текст"))))
    assert doc.paragraphs[0].text == "вставлено текст"


def test_text_box_text_does_not_join_the_paragraph(tmp_path):
    box = ('<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox><w:txbxContent>'
           + P(R("в надписи")) + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Основной "), box, R("текст"))))
    assert doc.paragraphs[0].text == "Основной текст"
    assert doc.paragraphs[0].has_image is True


def test_hyperlink_text_is_read(tmp_path):
    link = '<w:hyperlink w:anchor="x">%s</w:hyperlink>' % R("ссылка")
    assert read_docx(make_docx(tmp_path / "a.docx", P(R("Это "), link))).paragraphs[0].text == "Это ссылка"


def test_broken_file_gives_user_message(tmp_path):
    bad = tmp_path / "плохой.docx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(DocumentError) as e:
        read_docx(str(bad))
    assert "плохой.docx" in str(e.value)


def test_opener_knows_docx(tmp_path):
    assert opener.open_document(make_docx(tmp_path / "a.docx", P(R("Текст")))).paragraphs[0].text == "Текст"


def test_missing_body_gives_error(tmp_path):
    """Missing w:body should raise DocumentError."""
    import zipfile
    path = str(tmp_path / "bad.docx")
    make_docx(tmp_path / "bad.docx", P(R("text")))

    # Corrupt by removing w:body
    with zipfile.ZipFile(path, 'r') as z:
        entries = {i.filename: z.read(i.filename) for i in z.infolist()}
    doc_xml = entries['word/document.xml']
    corrupted = doc_xml.replace(b'<w:body>', b'<w:notbody>')
    corrupted = corrupted.replace(b'</w:body>', b'</w:notbody>')
    entries['word/document.xml'] = corrupted
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)

    with pytest.raises(DocumentError) as e:
        read_docx(path)
    assert "bad.docx" in str(e.value)


def test_corrupt_styles_gives_error(tmp_path):
    """Corrupt styles.xml should raise DocumentError."""
    import zipfile
    path = str(tmp_path / "bad.docx")
    make_docx(tmp_path / "bad.docx", P(R("Текст")))

    # Corrupt styles.xml
    with zipfile.ZipFile(path, 'r') as z:
        entries = {i.filename: z.read(i.filename) for i in z.infolist()}
    entries['word/styles.xml'] = b"not valid xml"
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)

    with pytest.raises(DocumentError) as e:
        read_docx(path)
    assert "bad.docx" in str(e.value)


def test_doctype_in_document_gives_error(tmp_path):
    """Document with DOCTYPE should raise DocumentError."""
    import zipfile
    path = str(tmp_path / "bad.docx")
    make_docx(tmp_path / "bad.docx", P(R("Текст")))

    # Add DOCTYPE to document.xml
    with zipfile.ZipFile(path, 'r') as z:
        entries = {i.filename: z.read(i.filename) for i in z.infolist()}
    doc_xml = entries['word/document.xml']
    corrupted = doc_xml.replace(b"?>", b"""?><!DOCTYPE w:document [
    <!ENTITY e "entity">
]>""")
    entries['word/document.xml'] = corrupted
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries.items():
            z.writestr(name, data)

    with pytest.raises(DocumentError) as e:
        read_docx(path)
    assert "неподдерживаемые конструкции" in str(e.value)


def test_bold_off_attribute(tmp_path):
    """<w:b w:val="off"/> should read as not bold."""
    bold_off = '<w:r><w:rPr><w:b w:val="off"/></w:rPr><w:t>текст</w:t></w:r>'
    doc = read_docx(make_docx(tmp_path / "a.docx", P(bold_off)))
    assert doc.paragraphs[0].spans[0].bold is False


def test_slot_text_equals_paragraph_text_invariant(tmp_path):
    """For any paragraph, concatenated slot texts should equal Paragraph.text."""
    from zhiraf.documents.docx_format import iter_paragraphs, paragraph_slots, q, PARSER
    from docfactory import zip_entries
    from lxml import etree

    path = make_docx(tmp_path / "a.docx",
                     P(R("Основной "), TAB, R("текст"), BR, R("и ещё")),
                     table([[P(R("Ячейка1")), P(R("Ячейка2"))]]),
                     P(R("После")))
    doc = read_docx(path)

    # Parse and iterate through the same document to get paragraphs and slots
    z = zip_entries(path)
    doc_xml = z['word/document.xml']
    root = etree.fromstring(doc_xml, PARSER)

    # Build mapping of slot_text -> expected doc paragraph
    para_idx = 0
    for w_p, position in iter_paragraphs(root.find(q("body"))):
        slots, _ = paragraph_slots(w_p)
        slot_text = "".join(slot.text for slot in slots)
        if para_idx < len(doc.paragraphs):
            dp = doc.paragraphs[para_idx]
            assert dp.text == slot_text, f"Paragraph {para_idx}: '{slot_text}' != '{dp.text}'"
            para_idx += 1
