from docfactory import BR, P, R, TAB, make_docx, table, zip_entries
from zhiraf.documents import opener
from zhiraf.documents.docx_format import read_docx, save_docx
from zhiraf.documents.model import Replacement


def saved(tmp_path, *paragraphs, reps):
    src = make_docx(tmp_path / "src.docx", *paragraphs)
    report = save_docx(read_docx(src), reps, str(tmp_path / "out.docx"))
    return src, report, read_docx(report.path)


def test_replacement_inside_one_run(tmp_path):
    _, report, out = saved(tmp_path, P(R("Работа с информации ведётся.")), reps=[Replacement(0, 9, 19, "информацией")])
    assert report.applied == 1 and report.skipped == []
    assert out.paragraphs[0].text == "Работа с информацией ведётся."


def test_replacement_across_runs_keeps_first_run_format(tmp_path):
    _, _, out = saved(tmp_path, P(R("Так ", bold=True), R("же был")), reps=[Replacement(0, 0, 6, "Также")])
    p = out.paragraphs[0]
    assert p.text == "Также был"
    assert (p.spans[0].text, p.spans[0].bold) == ("Также", True)


def test_comma_insertion_joins_previous_word_run(tmp_path):
    _, _, out = saved(tmp_path, P(R("Документ", bold=True), R(" определяющий порядок")),
                      reps=[Replacement(0, 8, 8, ",")])
    assert out.paragraphs[0].text == "Документ, определяющий порядок"
    assert out.paragraphs[0].spans[0].text == "Документ,"


def test_comma_deletion(tmp_path):
    _, _, out = saved(tmp_path, P(R("Однако, промокод")), reps=[Replacement(0, 6, 7, "")])
    assert out.paragraphs[0].text == "Однако промокод"


def test_several_fixes_in_one_paragraph(tmp_path):
    text = "Так же сотрудники с информации работают"
    _, report, out = saved(tmp_path, P(R(text)),
                           reps=[Replacement(0, 0, 6, "Также"), Replacement(0, 20, 30, "информацией"),
                                 Replacement(0, 17, 17, ",")])
    assert report.applied == 3
    assert out.paragraphs[0].text == "Также сотрудники, с информацией работают"


def test_fix_crossing_a_tab_or_break_is_refused(tmp_path):
    reps = [Replacement(0, 0, 3, "АБВ"), Replacement(1, 0, 3, "АБВ")]
    _, report, out = saved(tmp_path, P(R("А"), TAB, R("Б")), P(R("А"), BR, R("Б")), reps=reps)
    assert report.applied == 0 and report.skipped == reps
    assert [p.text for p in out.paragraphs] == ["А\tБ", "А\nБ"]


def test_table_cell_and_paragraph_numbering(tmp_path):
    _, _, out = saved(tmp_path, P(R("До")), table([[P(R("с информации"))]]), P(R("После")),
                      reps=[Replacement(1, 2, 12, "информацией")])
    assert [p.text for p in out.paragraphs] == ["До", "с информацией", "После"]


def test_deleted_text_is_never_edited(tmp_path):
    deleted = '<w:del w:id="1" w:author="x"><w:r><w:delText>старое</w:delText></w:r></w:del>'
    src, _, _ = saved(tmp_path, P(deleted, R("новое")), reps=[Replacement(0, 0, 5, "свежее")])
    xml = zip_entries(tmp_path / "out.docx")["word/document.xml"].decode("utf-8")
    assert "<w:delText>старое</w:delText>" in xml and "свежее" in xml


def test_other_parts_and_namespaces_are_kept(tmp_path):
    src, report, _ = saved(tmp_path, P(R("Так же")), P(R("Не трогать")), reps=[Replacement(0, 0, 6, "Также")])
    before, after = zip_entries(src), zip_entries(report.path)
    assert list(before) == list(after)
    for name in before:
        if name != "word/document.xml":
            assert before[name] == after[name]
    xml = after["word/document.xml"].decode("utf-8")
    assert 'mc:Ignorable="w14"' in xml and "xmlns:w14=" in xml
    assert '<w:t xml:space="preserve">Не трогать</w:t>' in xml


def test_leading_space_is_preserved(tmp_path):
    _, _, out = saved(tmp_path, P(R("А"), R("б в")), reps=[Replacement(0, 1, 2, " Б")])
    assert out.paragraphs[0].text == "А Б в"


def test_save_document_names_the_copy(tmp_path):
    src = make_docx(tmp_path / "Приказ.docx", P(R("Так же")))
    report = opener.save_document(opener.open_document(src), [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith("Приказ (исправлено).docx")


def test_document_changed_after_read_raises_error_and_creates_no_output(tmp_path):
    from zhiraf.documents.model import DocumentError
    src = make_docx(tmp_path / "src.docx", P(R("Исходный текст")))
    doc = read_docx(src)
    # Rewrite the source file with different content
    make_docx(tmp_path / "src.docx", P(R("Изменённый текст")))
    # Try to save with the old Document (which has stale paragraph text)
    dst = str(tmp_path / "out.docx")
    try:
        save_docx(doc, [Replacement(0, 0, 7, "Новый")], dst)
        assert False, "Should have raised DocumentError"
    except DocumentError as e:
        assert "изменился" in str(e).lower()
    # Verify no output file was created
    assert not (tmp_path / "out.docx").exists()


def test_replacement_out_of_bounds_paragraph_index_raises_error(tmp_path):
    from zhiraf.documents.model import DocumentError
    src = make_docx(tmp_path / "src.docx", P(R("Текст")))
    doc = read_docx(src)
    dst = str(tmp_path / "out.docx")
    try:
        save_docx(doc, [Replacement(99, 0, 2, "XX")], dst)
        assert False, "Should have raised DocumentError"
    except DocumentError as e:
        assert "изменился" in str(e).lower()
    # Verify no output file was created
    assert not (tmp_path / "out.docx").exists()


def test_write_package_cleanup_on_write_failure(tmp_path):
    """Test that write_package cleans up .part file if writing fails."""
    import zipfile
    from zhiraf.documents import package
    from zipfile import ZipInfo

    # Create minimal zip info with actual content so the loop executes
    info = ZipInfo("test.txt")
    infos = [info]
    blobs = {"test.txt": b"test content"}

    # Monkeypatch zipfile.ZipFile.writestr to simulate failure
    original_writestr = zipfile.ZipFile.writestr

    def failing_writestr(self, *args, **kwargs):
        raise IOError("Simulated write failure")

    dst = str(tmp_path / "test.docx")

    zipfile.ZipFile.writestr = failing_writestr
    try:
        try:
            package.write_package(dst, infos, blobs)
            assert False, "Should have raised IOError"
        except IOError as e:
            if "Simulated" not in str(e):
                raise
        # Verify no .part file was left behind
        assert not (tmp_path / "test.docx.part").exists()
    finally:
        zipfile.ZipFile.writestr = original_writestr
