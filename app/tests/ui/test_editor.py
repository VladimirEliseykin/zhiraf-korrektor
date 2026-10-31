import time

import pytest
from PySide2.QtCore import QEvent, QPoint, Qt
from PySide2.QtGui import QTextCursor
from PySide2.QtTest import QTest

from zhiraf.documents.model import Document, Paragraph, Span
from zhiraf.review import ReviewSession
from zhiraf.ui.blockfmt import BASE_UNDERLINE_PROP, MARK_PROP, spans_from_block
from zhiraf.ui.editor import ReviewEditor
from zhiraf.ui.runs import to_utf16


def finding(start, end, fix, level="error", rule="MODEL_FORM"):
    return {"start": start, "end": end, "fix": fix, "level": level, "rule": rule, "message": "m"}


def make(texts, styles=None, editable=False, tables=None):
    doc = Document([Paragraph([Span(t)], style=(styles or {}).get(i, "normal"), table=(tables or {}).get(i))
                    for i, t in enumerate(texts)], kind="paste" if editable else "docx", editable=editable)
    return doc, ReviewSession(texts)


def blocks(editor):
    block = editor.document().firstBlock()
    while block.isValid():
        yield block
        block = block.next()


def char_format_at(editor, pos):
    cursor = QTextCursor(editor.document())
    cursor.setPosition(pos + 1)
    return cursor.charFormat()


def marked_text(block):
    """Text of the characters of the block that carry a mark."""
    result, it = [], block.begin()
    while not it.atEnd():
        if it.fragment().charFormat().hasProperty(MARK_PROP):
            result.append(it.fragment().text())
        it += 1
    return "".join(result)


def shown(qtbot, doc, session, size=(640, 420)):
    editor = ReviewEditor()
    qtbot.addWidget(editor)
    editor.resize(*size)
    editor.load(doc, session)
    editor.show()
    return editor


def test_block_per_paragraph_and_text_equal_after_unsafe_characters(qtbot):
    doc, session = make(["Яблоко🍎 сорт", "a\nb\tc", "x y\rz"])
    editor = shown(qtbot, doc, session)
    assert editor.document().blockCount() == 3
    for i, block in enumerate(blocks(editor)):
        assert len(block.text()) == len(session.text(i))


@pytest.mark.parametrize("text, start, end, expected", [
    ("Яблоко🍎 сорт", 8, 12, "сорт"),
    ("Яблоко🍎 сорт", 0, 6, "Яблоко"),
    ("a\nb\tc d", 2, 4, "b\t"),
    ("a\nb\tc d", 6, 7, "d"),
    ("x yz w", 2, 4, "yz"),
    ("p\rq r", 2, 3, "q"),
    ("🍎🍎 ab", 3, 5, "ab"),
])
def test_mark_lands_on_the_right_characters(qtbot, text, start, end, expected):
    doc, session = make([text])
    session.add_findings(0, 0, [finding(start, end, "Z")])
    editor = shown(qtbot, doc, session)
    block = editor.document().firstBlock()
    assert marked_text(block) == expected.replace("\n", " ").replace("\r", " ")
    pos = block.position() + len(text[:start].encode("utf-16-le")) // 2
    assert char_format_at(editor, pos).property(MARK_PROP) == "open"
    assert editor.mark_at(pos) == session.marks[0].id
    assert editor.mark_at(pos - 1) is None if start else True
    assert editor.mark_at(block.position() + to_utf16(text, end)) is None


def test_error_mark_has_fill_and_solid_underline(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    fmt = char_format_at(editor, 10)
    assert fmt.property(MARK_PROP) == "open"
    assert fmt.underlineStyle() == fmt.SingleUnderline
    assert fmt.background().color().alpha() > 0
    assert fmt.background().color().red() == 0xb9
    assert fmt.property(BASE_UNDERLINE_PROP) is False


def test_check_mark_is_dotted_yellow(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, None, level="check")])
    editor = shown(qtbot, doc, session)
    fmt = char_format_at(editor, 10)
    assert fmt.underlineStyle() == fmt.DotLine
    assert fmt.background().color().name() == "#d9a521"
    assert fmt.background().color().alpha() > 0


def test_accept_repaints_text_and_green(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    session.accept()
    editor.repaint_paragraphs([0])
    assert editor.document().firstBlock().text() == "Работа с информацией"
    fmt = char_format_at(editor, 10)
    assert fmt.property(MARK_PROP) == "accepted"
    assert fmt.background().color().name() == "#3f9a4e"
    assert marked_text(editor.document().firstBlock()) == "информацией"


def test_tooltip_of_fixed_mark_says_what_was_before(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    session.accept()
    editor.repaint_paragraphs([0])
    assert editor.tooltip_text_at(12) == "было: информации"
    assert editor.tooltip_text_at(2) is None


def test_tooltip_shows_document_markup_literally(qtbot, monkeypatch):
    from PySide2.QtCore import QEvent, QPoint
    from PySide2.QtGui import QHelpEvent
    from zhiraf.ui import editor as editor_module
    doc, session = make(["Работа <img src=x> конец"])
    session.add_findings(0, 0, [finding(6, 18, "текст")])
    editor = shown(qtbot, doc, session)
    session.accept()
    editor.repaint_paragraphs([0])
    shown_texts = []
    monkeypatch.setattr(editor_module.QToolTip, "showText", lambda pos, text, *a: shown_texts.append(text))
    monkeypatch.setattr(editor, "_position_at", lambda point: 8)
    editor.event(QHelpEvent(QEvent.ToolTip, QPoint(1, 1), editor.viewport().mapToGlobal(QPoint(1, 1))))
    assert shown_texts and "&lt;img src=x&gt;" in shown_texts[0] and "<img" not in shown_texts[0]


def test_skipped_has_grey_fill(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    session.skip()
    editor.repaint_paragraphs([0])
    fmt = char_format_at(editor, 10)
    assert fmt.property(MARK_PROP) == "skipped"
    assert fmt.background().color().name() == "#8792a2"
    editor.grab()


def test_read_only_for_opened_document(qtbot):
    doc, session = make(["a"])
    assert shown(qtbot, doc, session).isReadOnly()


def test_repaint_keeps_one_block_per_paragraph_and_no_text_duplication(qtbot):
    doc, session = make(["Работа с информации", "второй"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    editor.repaint_paragraphs([0, 1, 0])
    assert [b.text() for b in blocks(editor)] == ["Работа с информации", "второй"]


def test_repaint_is_one_undoable_edit_block_and_leaves_history_empty(qtbot):
    doc, session = make(["Работа с информации"])
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    session.accept()
    editor.repaint_paragraphs([0])
    assert not editor.document().isUndoAvailable()


def test_headings_list_table_and_image(qtbot):
    doc, session = make(["Заголовок", "обычный", "пункт один", "пункт два", "ячейка"],
                        styles={0: "h1", 2: "list", 3: "list"}, tables={4: (1, 0, 0)})
    doc.paragraphs[1].has_image = True
    editor = shown(qtbot, doc, session)
    bl = list(blocks(editor))
    head, plain = char_format_at(editor, 1), char_format_at(editor, bl[1].position() + 1)
    assert head.fontWeight() >= 75 and head.fontPointSize() > plain.fontPointSize()
    assert bl[2].textList() is not None and bl[2].textList() is bl[3].textList()
    assert bl[0].textList() is None
    assert bl[2].text() == "пункт один"                 # no bullet characters in the text
    assert bl[4].blockFormat().leftMargin() > bl[1].blockFormat().leftMargin()
    assert bl[4].blockFormat().background().color().alpha() > 0
    assert editor.document().toPlainText() == "\n".join(b.text() for b in bl)
    assert "рисун" in editor.tooltip_text_at(bl[1].position() + 1)
    assert editor.tooltip_text_at(1) is None


def test_click_on_plain_text_of_paste_enters_edit_mode_and_esc_leaves(qtbot):
    doc, session = make(["Работа с информации и текст"], editable=True)
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    cursor = QTextCursor(editor.document())
    cursor.setPosition(23)
    point = editor.cursorRect(cursor).center()
    with qtbot.waitSignal(editor.edit_mode_changed) as sig:
        QTest.mouseClick(editor.viewport(), Qt.LeftButton, Qt.NoModifier, point)
    assert sig.args == [True] and not editor.isReadOnly()
    with qtbot.waitSignal(editor.edit_mode_changed) as sig:
        QTest.keyClick(editor, Qt.Key_Escape)
    assert sig.args == [False] and editor.isReadOnly()


def test_click_on_opened_document_never_enters_edit_mode(qtbot):
    doc, session = make(["Работа с информации и текст"])
    editor = shown(qtbot, doc, session)
    cursor = QTextCursor(editor.document())
    cursor.setPosition(23)
    QTest.mouseClick(editor.viewport(), Qt.LeftButton, Qt.NoModifier, editor.cursorRect(cursor).center())
    assert editor.isReadOnly()


def test_click_on_mark_emits_mark_clicked_and_stays_in_view_mode(qtbot):
    doc, session = make(["Работа с информации и текст"], editable=True)
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    cursor = QTextCursor(editor.document())
    cursor.setPosition(14)
    with qtbot.waitSignal(editor.mark_clicked) as sig:
        QTest.mouseClick(editor.viewport(), Qt.LeftButton, Qt.NoModifier, editor.cursorRect(cursor).center())
    assert sig.args == [session.marks[0].id]
    assert editor.isReadOnly()


def test_typing_in_pasted_paragraph_drops_marks_and_bumps_version(qtbot):
    doc, session = make(["Работа с информации", "вторая"], editable=True)
    doc.paragraphs[0].spans = [Span("Работа "), Span("с информации", bold=True)]
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    with qtbot.waitSignal(editor.paragraph_edited, timeout=3000) as sig:
        editor.insertPlainText("Да. ")
    assert sig.args == [0]
    assert session.version(0) == 1 and session.version(1) == 0
    assert session.marks == []
    assert session.originals[0] == "Да. Работа с информации"
    assert doc.paragraphs[0].text == "Да. Работа с информации"
    assert doc.paragraphs[0].spans[-1].bold is True
    assert marked_text(editor.document().firstBlock()) == ""


def test_flush_edits_syncs_immediately_and_keeps_line_breaks_in_session_text(qtbot):
    doc, session = make(["ab"], editable=True)
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(1)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key_Return)            # Enter is a line break inside the paragraph
    assert editor.document().blockCount() == 1
    got = []
    editor.paragraph_edited.connect(got.append)
    editor.flush_edits()
    assert got == [0]
    assert doc.paragraphs[0].text == "a\nb"
    assert session.originals[0] == "a\nb"
    editor.flush_edits()
    assert got == [0]


def test_underline_of_text_survives_mark_and_edit(qtbot):
    doc, session = make(["ab cd"], editable=True)
    doc.paragraphs[0].spans = [Span("ab", underline=True), Span(" cd")]
    session.add_findings(0, 0, [finding(0, 2, "xx")])
    editor = shown(qtbot, doc, session)
    editor.flush_edits()
    assert spans_from_block(editor.document().firstBlock()) == [Span("ab", underline=True), Span(" cd")]


def test_set_checked_until_marks_unchecked_state(qtbot):
    doc, session = make(["один", "два", "три"])
    editor = shown(qtbot, doc, session)
    before = editor.grab().toImage()
    editor.set_checked_until(0)
    assert editor.checked_until == 0
    after = editor.grab().toImage()
    assert before != after                               # the unchecked part is painted over
    editor.set_checked_until(None)
    assert editor.checked_until is None
    assert editor.grab().toImage() == before


def test_current_rect_is_inside_viewport_and_scrolls_to_mark(qtbot):
    texts = ["строка %d" % i for i in range(200)]
    doc, session = make(texts)
    session.add_findings(150, 0, [finding(0, 6, "слово")])
    editor = shown(qtbot, doc, session)
    assert editor.verticalScrollBar().value() == 0
    with qtbot.waitSignal(editor.current_rect_changed) as sig:
        editor.show_current()
    rect = sig.args[0]
    assert editor.viewport().rect().contains(rect)
    assert editor.verticalScrollBar().value() > 0
    assert len(editor.extraSelections()) == 1


def test_show_current_without_mark_clears_frame(qtbot):
    doc, session = make(["abc"])
    editor = shown(qtbot, doc, session)
    editor.show_current()
    assert editor.extraSelections() == []


def test_deleting_across_paragraphs_in_edit_mode_keeps_block_per_paragraph(qtbot):
    doc, session = make(["abc", "def"], editable=True)
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(1)
    cursor.setPosition(5, QTextCursor.KeepAnchor)
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key_Delete)
    qtbot.waitUntil(lambda: editor.document().blockCount() == 2, timeout=2000)
    assert editor.document().blockCount() == len(doc.paragraphs)


def test_accept_all_two_thousand_marks_repaint_is_fast(qtbot):
    texts = ["Документ номер %d определяющий" % i for i in range(3000)]
    doc, session = make(texts)
    for i in range(0, 3000, 3)[:1000]:
        session.add_findings(i, 0, [finding(0, 8, "Бумага"), finding(9, 14, "число")])
    editor = shown(qtbot, doc, session)
    assert len(session.marks) == 2000
    edits = session.accept_all_errors()
    changed = {e.paragraph for e in edits}
    started = time.perf_counter()
    editor.repaint_paragraphs(changed)
    elapsed = time.perf_counter() - started
    print("repaint of %d paragraphs / %d marks: %.2f s" % (len(changed), len(edits), elapsed))
    assert elapsed < 5
    assert editor.document().findBlockByNumber(0).text().startswith("Бумага число")


def marked_chars(editor):
    return sum(len(marked_text(b)) for b in blocks(editor))


def test_undo_after_flush_is_one_step_without_stale_marks(qtbot):
    doc, session = make(["Работа с информации", "вторая"], editable=True)
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    editor.insertPlainText("Да. ")
    editor.flush_edits()
    assert marked_chars(editor) == 0
    editor.document().undo()
    qtbot.wait(20)
    assert editor.document().firstBlock().text() == "Работа с информации"
    assert marked_chars(editor) == 0


def test_repaint_in_edit_mode_adds_no_undo_step(qtbot):
    doc, session = make(["Работа с информации", "вторая"], editable=True)
    session.add_findings(1, 0, [finding(0, 6, "второй")])
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)
    session.accept()
    editor.repaint_paragraphs([1])
    assert not editor.document().isUndoAvailable()
    QTest.keyClick(editor, Qt.Key_Escape)
    assert editor.document().findBlockByNumber(1).text() == "второй"


def test_skipped_label_is_drawn_once_per_mark_even_if_split_by_bold(qtbot):
    doc, session = make(["Работа с информации"])
    doc.paragraphs[0].spans = [Span("Работа с инф"), Span("орма", bold=True), Span("ции")]
    session.add_findings(0, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    session.skip()
    editor.repaint_paragraphs([0])
    labels = editor.skipped_labels()
    assert [mark_id for mark_id, _ in labels] == [session.marks[0].id]


def test_repaint_during_edit_mode_keeps_undo_history(qtbot):
    doc, session = make(["первый абзац", "Работа с информации"], editable=True)
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    cursor = editor.textCursor()
    cursor.setPosition(0)
    editor.setTextCursor(cursor)
    editor.insertPlainText("Да. ")
    session.add_findings(1, 0, [finding(9, 19, "информацией")])
    editor.repaint_paragraphs([1])
    assert editor.document().findBlockByNumber(0).text() == "Да. первый абзац"
    editor.document().undo()
    assert editor.document().findBlockByNumber(0).text() == "первый абзац"


def test_deferred_repaint_is_applied_on_escape(qtbot):
    doc, session = make(["первый абзац", "Работа с информации"], editable=True)
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    session.add_findings(1, 0, [finding(9, 19, "информацией")])
    editor.repaint_paragraphs([1])
    assert marked_text(editor.document().findBlockByNumber(1)) == ""
    QTest.keyClick(editor, Qt.Key_Escape)
    assert marked_text(editor.document().findBlockByNumber(1)) == "информации"


def test_two_typings_both_undone_and_marks_hidden_only_in_edit_mode(qtbot):
    doc, session = make(["первый абзац", "Работа с информации"], editable=True)
    session.add_findings(1, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    assert marked_chars(editor) > 0
    editor._enter_edit_mode()
    assert marked_chars(editor) == 0
    for number, word in ((0, "Да. "), (1, "Ещё ")):
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(number).position())
        editor.setTextCursor(cursor)
        editor.insertPlainText(word)
    editor.document().undo()
    editor.document().undo()
    assert [b.text() for b in blocks(editor)] == ["первый абзац", "Работа с информации"]
    editor.document().redo()
    editor.document().redo()
    QTest.keyClick(editor, Qt.Key_Escape)
    assert [b.text() for b in blocks(editor)] == ["Да. первый абзац", "Ещё Работа с информации"]
    assert marked_chars(editor) == 0                      # the edited paragraphs lost their marks for good


def test_marks_come_back_after_escape_in_untouched_paragraphs(qtbot):
    doc, session = make(["первый абзац", "Работа с информации"], editable=True)
    session.add_findings(1, 0, [finding(9, 19, "информацией")])
    editor = shown(qtbot, doc, session)
    editor._enter_edit_mode()
    QTest.keyClick(editor, Qt.Key_Escape)
    assert marked_text(editor.document().findBlockByNumber(1)) == "информации"
