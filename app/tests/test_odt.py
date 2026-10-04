import os
import zipfile

from docfactory import OH, OP, OSPAN, make_odt, zip_entries
from zhiraf.documents import opener
from zhiraf.documents.model import DocumentError, Replacement
from zhiraf.documents.odt_format import read_odt, save_odt


def test_read_text_headings_lists_tables_and_bold(tmp_path):
    body = (OH("Введение", 1) + OP("Текст ", OSPAN("важный", "T1"), " конец")
            + '<text:list><text:list-item>' + OP("Пункт") + "</text:list-item></text:list>"
            + '<table:table><table:table-row><table:table-cell>' + OP("Ячейка")
            + "</table:table-cell></table:table-row></table:table>")
    doc = read_odt(make_odt(tmp_path / "a.odt", body))
    assert [(p.text, p.style, p.table) for p in doc.paragraphs] == [
        ("Введение", "h1", None), ("Текст важный конец", "normal", None), ("Пункт", "list", None),
        ("Ячейка", "normal", (0, 0, 0))]
    assert [(s.text, s.bold) for s in doc.paragraphs[1].spans] == [("Текст ", False), ("важный", True),
                                                                   (" конец", False)]


def test_spaces_tabs_and_breaks(tmp_path):
    doc = read_odt(make_odt(tmp_path / "a.odt", OP('А<text:s text:c="2"/>Б<text:tab/>В<text:line-break/>Г')))
    assert doc.paragraphs[0].text == "А  Б\tВ\nГ"


def test_footnote_text_is_not_part_of_the_paragraph(tmp_path):
    note = '<text:note text:note-class="footnote"><text:note-body>' + OP("сноска") + "</text:note-body></text:note>"
    assert read_odt(make_odt(tmp_path / "a.odt", OP("Текст", note, " дальше"))).paragraphs[0].text == "Текст дальше"


def test_save_in_place_across_span_and_tail(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP(OSPAN("Так ", "T1"), "же был"))
    report = save_odt(read_odt(src), [Replacement(0, 0, 6, "Также")], str(tmp_path / "out.odt"))
    out = read_odt(report.path)
    assert report.applied == 1 and out.paragraphs[0].text == "Также был"
    assert (out.paragraphs[0].spans[0].text, out.paragraphs[0].spans[0].bold) == ("Также", True)


def test_fix_across_a_tab_is_refused(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("А<text:tab/>Б"))
    report = save_odt(read_odt(src), [Replacement(0, 0, 3, "АБВ")], str(tmp_path / "out.odt"))
    assert report.applied == 0 and len(report.skipped) == 1


def test_package_order_and_mimetype_kept(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("Так же"))
    report = opener.save_document(opener.open_document(src), [Replacement(0, 0, 6, "Также")])
    with zipfile.ZipFile(report.path) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    before, after = zip_entries(src), zip_entries(report.path)
    assert list(before) == list(after) and before["Pictures/image1.png"] == after["Pictures/image1.png"]


def test_corrupt_content_xml_raises_error(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("Текст"))
    # Corrupt content.xml by replacing valid XML with invalid XML
    with zipfile.ZipFile(src, "a") as z:
        z.writestr("content.xml", b"<invalid>unclosed tag")
    try:
        read_odt(src)
        assert False, "Should have raised DocumentError"
    except DocumentError as e:
        assert "повреждён" in str(e)


def test_document_changed_after_read_raises_error_and_creates_no_output(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("Текст"))
    doc = read_odt(src)
    # Rewrite source with different text
    make_odt(src, OP("Другой текст"))
    dst = str(tmp_path / "out.odt")
    try:
        save_odt(doc, [Replacement(0, 0, 4, "Новый")], dst)
        assert False, "Should have raised DocumentError"
    except DocumentError as e:
        assert "изменился" in str(e)
    # Verify output file was not created
    assert not os.path.exists(dst)
