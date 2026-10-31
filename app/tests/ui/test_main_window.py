import os
import time

import pytest
from PySide2.QtCore import QMimeData, Qt
from PySide2.QtGui import QGuiApplication
from PySide2.QtTest import QTest
from PySide2.QtWidgets import QFileDialog, QMessageBox

from docfactory import P, R, make_docx
from zhiraf import storage
from zhiraf.documents.opener import open_document
from zhiraf.review import ACCEPTED, DICTIONARY, MANUAL, OPEN, SKIPPED
from zhiraf.ui import loader
from zhiraf.ui.main_window import MainWindow

FIRST = "Работа с информации ведётся."
SECOND = "Документ определяющий порядок утверждён."
FORM, COMMA = 0, 1   # the paragraphs where the fake models find a wrong ending / a missing comma


class Dialogs:
    """Every modal the window can open is replaced: an unpatched one would block the offscreen run."""

    def __init__(self):
        self.calls = {"information": [], "warning": [], "critical": [], "question": [], "save": [], "open": []}
        self.answer = QMessageBox.Yes
        self.save_path = ""
        self.open_path = ""


@pytest.fixture(autouse=True)
def dialogs(monkeypatch):
    d = Dialogs()
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, _n=name, **k: d.calls[_n].append(a[2:]) or 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: d.calls["question"].append(a[2:]) or d.answer))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: d.calls["save"].append(a) or (d.save_path, "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: d.calls["open"].append(a) or (d.open_path, "")))
    monkeypatch.setattr(MainWindow, "_ask_save_before_close", lambda self: "discard")
    return d


def window(qtbot, models, factories="fakes:make_factories"):
    w = MainWindow(models, factories=factories)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitActive(w)
    return w


def make_doc(tmp_path, name="a.docx"):
    return make_docx(tmp_path / name, P(R(FIRST)), P(R(SECOND)))


def wait_state(qtbot, w, *states):
    qtbot.waitUntil(lambda: w.controller is not None and w.controller.state in states, timeout=60000)


def opened(qtbot, models, tmp_path, name="a.docx", factories="fakes:make_factories", state="done"):
    w = window(qtbot, models, factories)
    w.open_path(make_doc(tmp_path, name))
    wait_state(qtbot, w, state)
    return w


def block_text(w, index):
    return w.editor.document().findBlockByNumber(index).text()


def set_clipboard(text=None, html=None):
    mime = QMimeData()
    if text is not None:
        mime.setText(text)
    if html is not None:
        mime.setHtml(html)
    QGuiApplication.clipboard().setMimeData(mime)


def mark_in(w, paragraph):
    return next(m for m in w.session.marks if m.paragraph == paragraph)


def inject_typos(w, word, paragraphs):
    """The fake models know no typos: add 'check' marks on a word, the way the rules would."""
    for p in paragraphs:
        text = w.session.originals[p]
        start = text.index(word)
        w.session.add_findings(p, 0, [{"start": start, "end": start + len(word), "level": "check",
                                       "rule": "RULE_TYPO", "fix": None, "message": "Возможно, опечатка"}])
    w._marks_changed(set(paragraphs))


def test_start_screen_is_shown_first(qtbot, full_models_dir):
    w = window(qtbot, full_models_dir)
    assert w.stack.currentWidget() is w.start_screen
    assert w.windowTitle() == "Жираф.Корректор"
    assert w.doc is None and w.controller is None
    assert set(w.actions) == {"open", "paste", "stop", "save_copy", "save_as", "copy_formatted", "undo",
                              "accept_all", "dictionary", "settings", "help"}
    for key in ("dictionary", "settings", "help"):
        w.actions[key].trigger()   # stubs until Task 13: nothing happens, nothing crashes


def test_open_path_runs_check_and_shows_marks(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    assert w.windowTitle() == "Жираф.Корректор — a.docx"
    assert w.stack.currentWidget() is w.review_page
    counts = w.session.counts()
    assert counts["errors"] == 2 and w.status.accept_all_button.isEnabled()
    assert w.status.labels["errors"].text() == "ошибок: 2"
    assert w.editor.checked_until is None            # ruling 6: done clears the unchecked part
    assert w.card.isVisible() and w.actions["stop"].isEnabled() is False
    assert w.progress.label.text() == "Проверка завершена"


def test_keys_review_flow(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    first = w.session.current
    QTest.keyClick(w.editor, Qt.Key_Right)
    assert w.session.current is not first
    QTest.keyClick(w.editor, Qt.Key_Left)
    assert w.session.current is first
    assert first.paragraph == COMMA
    QTest.keyClick(w.editor, Qt.Key_Return)
    assert first.status == ACCEPTED and "Документ," in block_text(w, COMMA)
    assert w.session.current is not first and w.session.current.status == OPEN
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)
    assert first.status == OPEN and block_text(w, COMMA) == SECOND and w.session.current is first


def test_arrows_move_the_cursor_in_edit_mode(qtbot, full_models_dir):
    w = window(qtbot, full_models_dir)
    set_clipboard(text="Простой текст.")
    w.paste_from_clipboard()
    wait_state(qtbot, w, "done")
    assert w.windowTitle() == "Жираф.Корректор — Вставленный текст"
    w.editor._enter_edit_mode()
    w.editor.moveCursor(w.editor.textCursor().Start)
    current = w.session.current
    QTest.keyClick(w.editor, Qt.Key_Right)
    assert w.editor.textCursor().position() == 1 and w.session.current is current


def test_typing_in_manual_edit_keeps_the_keys_to_itself(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    first = w.session.current
    other = next(m for m in w.session.marks if m is not first)
    QTest.mouseClick(w.card.manual_button, Qt.LeftButton)
    assert w.card.manual_edit.isVisible()
    QTest.keyClick(w.card.manual_edit, Qt.Key_Right)
    assert w.session.current is first
    QTest.keyClicks(w.card.manual_edit, ",")
    QTest.keyClick(w.card.manual_edit, Qt.Key_Return)
    assert first.status == MANUAL and first.applied == "," and other.status == OPEN   # no second, window-level Enter


def test_accept_all_one_undo(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    QTest.mouseClick(w.status.accept_all_button, Qt.LeftButton)
    assert w.session.counts()["errors"] == 0 and w.session.counts()["fixed"] == 2
    assert "информацией" in block_text(w, FORM) and "Документ," in block_text(w, COMMA)
    assert not w.card.isVisible()
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)
    assert w.session.counts()["errors"] == 2
    assert block_text(w, FORM) == FIRST and block_text(w, COMMA) == SECOND


def test_check_level_is_not_accepted_by_accept_all(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    inject_typos(w, "порядок", [COMMA])
    w._accept_all()
    counts = w.session.counts()
    assert counts["errors"] == 0 and counts["checks"] == 1 and counts["fixed"] == 2


def test_manual_fix_and_skip_and_dictionary(qtbot, full_models_dir, tmp_path):
    w = window(qtbot, full_models_dir)
    w.open_path(make_docx(tmp_path / "t.docx", P(R("Слово ИСПДн тут.")), P(R("И ещё ИСПДн здесь.")), P(R("Раз два."))))
    wait_state(qtbot, w, "done")
    inject_typos(w, "ИСПДн", [0, 1])
    # manual fix of the first, skip of the second through the card
    w.session.select(w.session.marks[0].id)
    w._refresh()
    QTest.mouseClick(w.card.manual_button, Qt.LeftButton)
    w.card.manual_edit.setText("ИСПДН")
    QTest.keyClick(w.card.manual_edit, Qt.Key_Return)
    assert w.session.marks[0].status == MANUAL and "ИСПДН" in block_text(w, 0)
    QTest.mouseClick(w.card.skip_button, Qt.LeftButton)
    assert w.session.marks[1].status == SKIPPED
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)   # un-skip
    assert w.session.marks[1].status == OPEN and w.session.current is w.session.marks[1]
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)   # un-manual
    assert w.session.marks[0].status == OPEN
    # the dictionary takes both
    w.session.select(w.session.marks[0].id)
    w._refresh()
    QTest.mouseClick(w.card.dictionary_button, Qt.LeftButton)
    assert "ИСПДн" in storage.Dictionary()
    assert [m.status for m in w.session.marks] == [DICTIONARY, DICTIONARY]
    assert w.session.counts()["dictionary"] == 2


def test_dictionary_write_failure_shows_notice_and_keeps_mark(qtbot, full_models_dir, tmp_path, monkeypatch):
    w = opened(qtbot, full_models_dir, tmp_path)
    inject_typos(w, "порядок", [COMMA])
    mark = next(m for m in w.session.marks if m.rule == "RULE_TYPO")
    w.session.select(mark.id)
    w._refresh()

    def broken(self, word):
        raise OSError("read only")
    monkeypatch.setattr(storage.Dictionary, "add", broken)
    QTest.mouseClick(w.card.dictionary_button, Qt.LeftButton)
    assert mark.status == OPEN and w.session.current is mark
    assert w.notice.isVisible() and "Не удалось записать словарь" in w.notice.text_label.text()
    assert "Слово не добавлено" in w.notice.text_label.text()


def test_undo_with_failing_dictionary_keeps_everything(qtbot, full_models_dir, tmp_path, monkeypatch):
    w = opened(qtbot, full_models_dir, tmp_path)
    inject_typos(w, "порядок", [COMMA])
    mark = next(m for m in w.session.marks if m.rule == "RULE_TYPO")
    w.session.select(mark.id)
    w._refresh()
    QTest.mouseClick(w.card.dictionary_button, Qt.LeftButton)
    assert mark.status == DICTIONARY

    def broken(self, word):
        raise OSError("read only")
    monkeypatch.setattr(storage.Dictionary, "remove", broken)
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)
    assert mark.status == DICTIONARY and "Слово осталось в словаре" in w.notice.text_label.text()
    monkeypatch.undo()
    QTest.keyClick(w.editor, Qt.Key_Z, Qt.ControlModifier)
    assert mark.status == OPEN


def test_empty_paste_shows_no_text_message_and_does_not_start(qtbot, full_models_dir, dialogs):
    w = window(qtbot, full_models_dir)
    set_clipboard(text="  \n ")
    w.paste_from_clipboard()
    assert len(dialogs.calls["information"]) == 1 and "нет текста" in dialogs.calls["information"][0][0]
    assert w.doc is None and w.controller is None and w.stack.currentWidget() is w.start_screen


def test_text_without_sentences_is_shown_but_not_checked(qtbot, full_models_dir, tmp_path):
    w = window(qtbot, full_models_dir)
    w.open_path(make_docx(tmp_path / "empty.docx", P(R("  ")), P(R(""))))
    qtbot.waitUntil(lambda: w.doc is not None, timeout=10000)
    assert w.controller.jobs_started == 0 and w.controller.state == "idle"
    assert "нет текста для проверки" in w.notice.text_label.text()


def test_missing_models_show_notice_and_do_not_check(qtbot, models_dir, tmp_path):
    w = window(qtbot, models_dir)    # only vocab.tsv
    w.open_path(make_doc(tmp_path))
    qtbot.waitUntil(lambda: w.doc is not None, timeout=10000)
    assert w.controller.jobs_started == 0 and w.stack.currentWidget() is w.review_page
    assert "не хватает" in w.notice.text_label.text() and block_text(w, 0) == FIRST


def test_paste_html_creates_editable_document_with_formatting(qtbot, full_models_dir):
    w = window(qtbot, full_models_dir)
    set_clipboard(text=FIRST, html="<p>Работа с <b>информации</b> ведётся.</p>")
    w.paste_from_clipboard()
    assert w.doc.kind == "paste" and w.doc.editable and w.doc.path is None
    wait_state(qtbot, w, "done")
    QTest.mouseClick(w.status.accept_all_button, Qt.LeftButton)
    w.copy_with_formatting()
    mime = QGuiApplication.clipboard().mimeData()
    assert "информацией" in mime.text() and "<b>" in mime.html() and "информацией" in mime.html()


def test_save_copy_next_to_original_and_original_untouched(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    original = (tmp_path / "a.docx").read_bytes()
    w._accept_all()
    w.save_copy()
    copy = tmp_path / "a (исправлено).docx"
    assert copy.exists() and (tmp_path / "a.docx").read_bytes() == original
    assert [p.text for p in open_document(str(copy)).paragraphs] == ["Работа с информацией ведётся.",
                                                                      "Документ, определяющий порядок утверждён."]
    assert "Сохранено: %s" % copy in w.notice.text_label.text()


def test_save_as_same_path_is_refused_and_existing_file_asks(qtbot, full_models_dir, tmp_path, dialogs):
    w = opened(qtbot, full_models_dir, tmp_path)
    source = tmp_path / "a.docx"
    before = source.read_bytes()
    w.save_as(str(source))
    assert len(dialogs.calls["warning"]) == 1 and not dialogs.calls["question"] and source.read_bytes() == before

    other = tmp_path / "other.docx"
    other.write_bytes(b"precious")
    dialogs.answer = QMessageBox.No
    w.save_as(str(other))
    assert len(dialogs.calls["question"]) == 1 and other.read_bytes() == b"precious"
    dialogs.answer = QMessageBox.Yes
    w.save_as(str(other))
    assert len(dialogs.calls["question"]) == 2 and other.read_bytes() != b"precious"
    assert source.read_bytes() == before


def test_save_as_asks_for_a_name_and_adds_the_extension(qtbot, full_models_dir, tmp_path, dialogs):
    w = opened(qtbot, full_models_dir, tmp_path)
    dialogs.save_path = str(tmp_path / "итог")
    w.save_as()
    assert dialogs.calls["save"] and (tmp_path / "итог.docx").exists()


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores folder permissions")
def test_save_failure_offers_save_as(qtbot, full_models_dir, tmp_path, dialogs):
    folder = tmp_path / "ro"
    folder.mkdir()
    w = opened(qtbot, full_models_dir, folder)
    folder.chmod(0o500)
    try:
        w.save_copy()
        assert len(dialogs.calls["question"]) == 1 and "другим именем" in dialogs.calls["question"][0][0]
        assert len(dialogs.calls["save"]) == 1       # the answer was Yes: «Сохранить как…» opened
    finally:
        folder.chmod(0o700)


def test_pasted_text_saves_through_save_as(qtbot, full_models_dir, tmp_path, dialogs):
    w = window(qtbot, full_models_dir)
    set_clipboard(text=FIRST)
    w.paste_from_clipboard()
    wait_state(qtbot, w, "done")
    dialogs.save_path = str(tmp_path / "p.txt")
    w.save_copy()
    assert len(dialogs.calls["save"]) == 1 and (tmp_path / "p.txt").exists()


def test_closing_during_check_kills_child_and_ignores_late_messages(qtbot, full_models_dir, tmp_path):
    w = window(qtbot, full_models_dir, "fakes:make_slow_factories")
    w.open_path(make_doc(tmp_path))
    wait_state(qtbot, w, "running")
    old, old_session = w.controller, w.session
    process = old.job._process
    start = time.time()
    assert w.close_document() is True
    assert time.time() - start < 2.5
    assert old.state != "done" and not process.is_alive() and w.controller is None
    w.open_path(make_doc(tmp_path, "b.docx"))
    wait_state(qtbot, w, "done")
    assert w.session is not old_session and w.session.counts()["total"] == 1 and old_session.marks == []


def test_crash_shows_notice_with_resume_button(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path, factories="fakes:make_crashing_factories",
               state="failed")
    assert w.controller.state == "failed"
    assert w.notice.isVisible() and w.notice.action_button.text() == "Продолжить с этого места"
    w.controller.factories = "fakes:make_factories"
    QTest.mouseClick(w.notice.action_button, Qt.LeftButton)
    wait_state(qtbot, w, "done")
    assert not w.notice.action_button.isVisible() or "Продолжить" not in w.notice.action_button.text()
    assert w.session.counts()["errors"] == 2


def test_stop_button_follows_the_state(qtbot, full_models_dir, tmp_path):
    w = window(qtbot, full_models_dir, "fakes:make_slow_factories")
    w.open_path(make_doc(tmp_path))
    wait_state(qtbot, w, "running")
    assert w.actions["stop"].isEnabled()
    w.actions["stop"].trigger()
    wait_state(qtbot, w, "stopped")
    assert not w.actions["stop"].isEnabled() and w.notice.action_button.text() == "Продолжить с этого места"


def test_unsaved_changes_ask_before_closing(qtbot, full_models_dir, tmp_path, monkeypatch):
    w = opened(qtbot, full_models_dir, tmp_path)
    w._accept_all()
    answers = iter(["cancel", "save", ])
    monkeypatch.setattr(w, "_ask_save_before_close", lambda: next(answers))
    assert w.close_document() is False and w.doc is not None
    assert w.close_document() is True
    assert (tmp_path / "a (исправлено).docx").exists() and w.doc is None
    # «Не сохранять»
    w.open_path(make_doc(tmp_path, "c.docx"))
    wait_state(qtbot, w, "done")
    w._accept_all()
    monkeypatch.setattr(w, "_ask_save_before_close", lambda: "discard")
    assert w.close_document() is True and not (tmp_path / "c (исправлено).docx").exists()


def test_saved_document_closes_without_asking(qtbot, full_models_dir, tmp_path, monkeypatch):
    w = opened(qtbot, full_models_dir, tmp_path)
    w._accept_all()
    w.save_copy()
    monkeypatch.setattr(w, "_ask_save_before_close", lambda: pytest.fail("asked after saving"))
    assert w.close_document() is True
    assert storage.Recent(storage.Settings()).items()[0]["stats"]["fixed"] == 2


def test_opening_unsupported_extension_shows_message_and_stays_on_start(qtbot, full_models_dir, tmp_path, dialogs):
    w = window(qtbot, full_models_dir)
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF")
    w.open_path(str(path))
    qtbot.waitUntil(lambda: bool(dialogs.calls["warning"]), timeout=10000)
    assert "Формат «.pdf» не поддерживается" in dialogs.calls["warning"][0][0]
    assert w.stack.currentWidget() is w.start_screen and w.task is None and w.actions["open"].isEnabled()


def test_open_runs_in_thread(qtbot, full_models_dir, tmp_path, monkeypatch):
    path = make_doc(tmp_path)

    def slow(p):
        time.sleep(0.3)
        return open_document(p)
    monkeypatch.setattr(loader, "open_document", slow)
    w = window(qtbot, full_models_dir)
    w.open_path(path)
    start = time.time()
    qtbot.wait(10)
    assert time.time() - start < 0.25
    assert w.stack.currentWidget() is w.opening_page and not w.actions["open"].isEnabled()
    qtbot.waitUntil(lambda: w.doc is not None, timeout=10000)
    assert w.stack.currentWidget() is w.review_page


def test_doc_notice_is_shown(qtbot, full_models_dir, tmp_path, monkeypatch):
    def with_notice(p):
        doc = open_document(p)
        doc.notice = ".doc сохранён только как .docx"
        return doc
    monkeypatch.setattr(loader, "open_document", with_notice)
    w = window(qtbot, full_models_dir)
    w.open_path(make_doc(tmp_path))
    qtbot.waitUntil(lambda: w.doc is not None, timeout=10000)
    assert ".docx" in w.notice.text_label.text()


def test_card_is_narrower_than_a_narrow_viewport_and_never_covers_the_mark(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    w.resize(560, 600)
    qtbot.wait(50)
    viewport = w.editor.viewport().rect()
    assert w.card.width() <= viewport.width() - 32
    w.resize(1100, 760)
    qtbot.wait(50)
    assert w.card.width() == 640
    assert w.card.geometry().intersected(w._anchor).isEmpty()


def test_closing_the_window_remembers_the_document(qtbot, full_models_dir, tmp_path):
    w = opened(qtbot, full_models_dir, tmp_path)
    w.close()
    items = storage.Recent(storage.Settings()).items()
    assert items and items[0]["path"].endswith("a.docx")


def test_recent_write_failure_is_silent(qtbot, full_models_dir, tmp_path, monkeypatch):
    def broken(self, path, stats=None):
        raise OSError("read only")
    monkeypatch.setattr(storage.Recent, "touch", broken)
    w = opened(qtbot, full_models_dir, tmp_path)
    assert w.close_document() is True
