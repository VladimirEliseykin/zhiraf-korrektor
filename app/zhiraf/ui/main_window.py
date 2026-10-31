"""The main window: start screen, the review screen and the flow between them.

The window only assembles the parts and wires their signals; what a mark means lives in ReviewSession,
how a check runs in CheckController, how a file is read or written in loader / export.
"""
import os
import time

from PySide2.QtCore import QEvent, Qt, QTimer
from PySide2.QtGui import QGuiApplication, QIcon, QKeySequence
from PySide2.QtWidgets import (QAction, QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QShortcut, QSizePolicy, QStackedWidget, QTextEdit, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from .. import missing_models, storage
from ..documents.model import DocumentError
from ..documents.opener import close_document as release_document
from ..review import OPEN, ReviewSession
from . import export, theme
from .card import MarkCard, card_position
from .clipboard import document_from_mime
from .controller import CheckController
from .dialogs import DictionaryDialog, HotkeysDialog, SettingsDialog
from .editor import ReviewEditor
from .loader import OpenTask
from .start_screen import StartScreen
from .status import NoticeBar, ProgressPanel, StatusPanel

TITLE = "Жираф.Корректор"
RETIRE_POLL_MS = 50
CLOSE_WAIT_S = 3.0
CARD_WIDTH = 640
CARD_SIDE_GAP = 32
CONTEXT_CHARS = 20
OPEN_FILTER = "Документы (*.docx *.doc *.odt *.txt);;Все файлы (*)"
DICTIONARY_FAILED = "Не удалось записать словарь: нет доступа к папке профиля. Слово не добавлено."
DICTIONARY_FAILED_ON_UNDO = "Не удалось записать словарь: нет доступа к папке профиля. Слово осталось в словаре."
SETTINGS_FAILED = "Не удалось записать настройки: нет доступа к папке профиля."
NO_TEXT = "В документе нет текста для проверки"
ALL_DONE = "Все пометки разобраны"
NOTHING_FOUND = "Ошибок не найдено"
RESUME = "Продолжить с этого места"


class MainWindow(QMainWindow):
    def __init__(self, models_dir, factories=None, parent=None, log_detail=None):
        super().__init__(parent)
        self.models_dir = models_dir
        self.factories = factories
        self.log_detail = log_detail
        self.settings = storage.Settings()
        self.dictionary = storage.Dictionary()
        self.recent = storage.Recent(self.settings)
        self.doc = None
        self.session = None
        self.controller = None
        self.task = None
        self.hard_exit = False        # a thread outlived the bounded wait: main() must leave with os._exit
        self._retiring = []           # cancelled opens whose thread still runs: kept alive, never waited for
        self._typed = False           # the reader typed into a pasted text since the last save
        self._title = None
        self._modified = False        # accepted fixes changed since the last save
        self._notice_kind = None
        self._anchor = None
        self.setWindowIcon(QIcon(theme.art_path("logo.png")))
        self.resize(1100, 760)
        self.setMinimumSize(800, 560)
        self._build()
        self._build_actions()
        self._build_shortcuts()
        self.show_start_page()

    # --- assembling the parts ---

    def _build(self):
        self.stack = QStackedWidget(self)
        self.setCentralWidget(self.stack)
        self.start_screen = StartScreen()
        self.opening_page = QLabel("Открываю…")
        self.opening_page.setAlignment(Qt.AlignCenter)
        self.opening_page.setStyleSheet("font-size: 22px; color: %s;" % theme.COLORS["skipped"])
        self.review_page = QWidget()
        self.stack.addWidget(self.start_screen)
        self.stack.addWidget(self.opening_page)
        self.stack.addWidget(self.review_page)

        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.toolbar_more = QToolBar()   # the second row: the whole set does not fit one row at the minimum width
        self.toolbar_more.setMovable(False)
        self.progress = ProgressPanel()
        self.progress.setFixedWidth(280)
        self.notice = NoticeBar()
        self.editor = ReviewEditor()
        self.card = MarkCard(self.editor.viewport())
        self.card.hide()
        self.status = StatusPanel()

        layout = QVBoxLayout(self.review_page)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.toolbar_more)
        layout.addWidget(self.progress, 0, Qt.AlignRight)   # its own row: beside the toolbar it pushed actions out
        layout.addWidget(self.notice)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.status)

        screen = self.start_screen
        screen.open_requested.connect(self._choose_and_open)
        screen.paste_requested.connect(self.paste_from_clipboard)
        screen.file_dropped.connect(self.open_path)
        screen.recent_chosen.connect(self.open_path)
        screen.clear_recent_requested.connect(self._clear_recent)

        self.card.accept_clicked.connect(self._accept)
        self.card.skip_clicked.connect(self._skip)
        self.card.dictionary_clicked.connect(self._to_dictionary)
        self.card.manual_submitted.connect(self._manual)
        self.card.manual_button.clicked.connect(self._sync_shortcuts)
        self.card.manual_edit.installEventFilter(self)
        self.editor.viewport().installEventFilter(self)
        self.editor.mark_clicked.connect(self._mark_clicked)
        self.editor.paragraph_edited.connect(self._paragraph_edited)
        self.editor.edit_mode_changed.connect(self._edit_mode_changed)
        self.editor.current_rect_changed.connect(self._set_anchor)
        self.status.accept_all_clicked.connect(self._accept_all)
        self.notice.action_clicked.connect(self._notice_action)
        QApplication.instance().focusChanged.connect(self._sync_shortcuts)

    def _build_actions(self):
        table = (("open", "Открыть", self._choose_and_open), ("paste", "Вставить текст", self.paste_from_clipboard),
                 ("stop", "Остановить", self._stop), ("save_copy", "Сохранить исправленную копию", self.save_copy),
                 ("save_as", "Сохранить как…", self.save_as), ("copy_formatted", "Скопировать с оформлением",
                                                               self.copy_with_formatting),
                 ("undo", "Отменить", self._undo), ("accept_all", "Принять все ошибки", self._accept_all),
                 ("dictionary", "Словарь", self._show_dictionary), ("settings", "Настройки", self._show_settings),
                 ("help", "Справка", self._show_help))
        self.actions = {}
        for key, text, handler in table:
            action = QAction(text, self)
            action.triggered.connect(lambda checked=False, h=handler: h())
            self.actions[key] = action
        self.actions["open"].setShortcut(QKeySequence("Ctrl+O"))
        self.actions["save_copy"].setShortcut(QKeySequence("Ctrl+S"))
        self.actions["help"].setShortcut(QKeySequence("F1"))
        for action in self.actions.values():
            action.setShortcutContext(Qt.WindowShortcut)
            self.addAction(action)

        bar, a = self.toolbar, self.actions
        for key in ("open", "paste", "stop"):
            bar.addAction(a[key])
        save = QToolButton()
        menu = QMenu(save)
        menu.addAction(a["save_copy"])
        menu.addAction(a["save_as"])
        save.setText("Сохранить")
        save.setMenu(menu)
        save.setPopupMode(QToolButton.InstantPopup)
        self.save_button = save
        bar.addWidget(save)
        bar.addAction(a["undo"])
        more = self.toolbar_more
        more.addAction(a["copy_formatted"])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        more.addWidget(spacer)
        for key in ("dictionary", "settings", "help"):
            more.addAction(a[key])
        self._enable_document_actions(False)

    def _build_shortcuts(self):
        table = (("Left", self._go_prev), ("Right", self._go_next), ("Return", self._accept), ("Enter", self._accept),
                 ("Ctrl+Z", self._undo), ("Ctrl+V", self._paste_key))
        self._shortcuts = []
        for keys, handler in table:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda h=handler: self._on_key(h))
            self._shortcuts.append(shortcut)

    # --- keys: only in the review mode, never while the reader types somewhere ---

    def _keys_active(self):
        if self.stack.currentWidget() is not self.review_page or not self.editor.isReadOnly():
            return False
        if self.card.manual_edit.isVisible():
            return False
        focus = QApplication.focusWidget()
        return not (isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)) and focus is not self.editor)

    def _sync_shortcuts(self, *_):
        # a disabled shortcut does not swallow the key, so a text field keeps Enter and the arrows
        active = self._keys_active()
        start = self.stack.currentWidget() is self.start_screen
        for shortcut in self._shortcuts:
            shortcut.setEnabled(active or (start and shortcut.key().toString() == "Ctrl+V"))

    def _on_key(self, handler):
        if self._keys_active() or (handler == self._paste_key and self.stack.currentWidget() is self.start_screen):
            handler()

    def _paste_key(self):
        self.paste_from_clipboard()

    def eventFilter(self, watched, event):
        if watched is self.card.manual_edit and event.type() in (QEvent.Show, QEvent.Hide):
            self._sync_shortcuts()
        elif watched is self.editor.viewport() and event.type() == QEvent.Resize:
            self._place_card()
        return False

    # --- pages and title ---

    def show_start_page(self):
        self.start_screen.set_recent(self.recent.items())
        self._set_title(None)
        self.stack.setCurrentWidget(self.start_screen)
        self._enable_document_actions(False)
        self._sync_shortcuts()

    def _set_title(self, name):
        self.setWindowTitle(TITLE if not name else "%s — %s" % (TITLE, name))

    def _enable_document_actions(self, on):
        for key in ("save_copy", "save_as", "copy_formatted", "undo", "accept_all"):
            self.actions[key].setEnabled(on)
        self.save_button.setEnabled(on)
        self.actions["stop"].setEnabled(False)

    def show_start(self):
        self.close_document()

    # --- opening ---

    def _choose_and_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть документ", "", OPEN_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        if not self.close_document():
            return
        self.opening_page.setText("Открываю…")
        self.stack.setCurrentWidget(self.opening_page)
        for key in ("open", "paste"):
            self.actions[key].setEnabled(False)
        self._sync_shortcuts()
        self.task = OpenTask(path, self)
        self.task.opened.connect(self._on_opened)
        self.task.failed.connect(self._on_open_failed)
        self.task.start()

    def _finish_task(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            task.close()
            task.deleteLater()
        for key in ("open", "paste"):
            self.actions[key].setEnabled(True)

    def _retire_task(self):
        """Drop an open in progress without waiting: its late result is ignored, its thread ends on its own."""
        task, self.task = self.task, None
        if task is None:
            return
        task.cancel()
        self._retiring.append(task)
        for key in ("open", "paste"):
            self.actions[key].setEnabled(True)
        QTimer.singleShot(RETIRE_POLL_MS, self._reap)

    def _reap(self):
        for task in [t for t in self._retiring if not t.is_running()]:
            self._retiring.remove(task)
            task.close()
            task.deleteLater()
        if self._retiring:
            QTimer.singleShot(RETIRE_POLL_MS, self._reap)

    def _on_opened(self, doc):
        self._finish_task()
        self._start_document(doc, os.path.basename(doc.path) if doc.path else "Вставленный текст")

    def _say(self, kind, text, buttons=None):
        """A message box whose text is always plain: it may carry a document's words or paths."""
        icon = {"information": QMessageBox.Information, "warning": QMessageBox.Warning,
                "question": QMessageBox.Question}[kind]
        box = QMessageBox(icon, TITLE, text, buttons if buttons is not None else QMessageBox.Ok, self)
        box.setTextFormat(Qt.PlainText)
        return box.exec_()

    def _on_open_failed(self, message):
        self._finish_task()
        self.show_start_page()
        self._say("warning", message)

    def paste_from_clipboard(self):
        doc = document_from_mime(QGuiApplication.clipboard().mimeData())
        if doc is None:
            self._say("information", "В буфере обмена нет текста для проверки.")
            return
        if self.close_document():
            self._start_document(doc, "Вставленный текст")

    def _start_document(self, doc, title):
        self.doc = doc
        self._modified = self._typed = False
        self.session = ReviewSession([p.text for p in doc.paragraphs], self.dictionary)
        self.session.set_show_checks(self.settings["show_checks"])
        self.editor.set_show_checks(self.settings["show_checks"])
        self.editor.load(doc, self.session)
        self.notice.clear()
        self._notice_kind = None
        self._set_title(title)
        self.stack.setCurrentWidget(self.review_page)
        self._enable_document_actions(True)
        self.progress.set_progress(0.0, None, time.time(), "idle")
        self.controller = CheckController(self.session, lambda: self.doc.paragraphs if self.doc else [],
                                          self.models_dir, self.settings, factories=self.factories, parent=self,
                                          log_detail=self.log_detail)
        controller = self.controller
        controller.marks_changed.connect(self._marks_changed)
        controller.progressed.connect(self._progressed)
        controller.state_changed.connect(self._state_changed)
        controller.checked_until.connect(self.editor.set_checked_until)
        if doc.notice:
            self._notify(doc.notice, kind="info")
        if not controller.has_text:
            self._notify(NO_TEXT, kind="info")
            self.progress.set_progress(0.0, None, time.time(), "idle")
        elif missing_models(self.models_dir):
            self._notify(missing_models(self.models_dir), kind="info")
        else:
            controller.start()
        self._refresh()
        self._sync_shortcuts()
        self.editor.setFocus()

    # --- closing ---

    def _ask_save_before_close(self):
        box = QMessageBox(QMessageBox.Question, TITLE, "Сохранить исправленную копию?", QMessageBox.NoButton, self)
        save = box.addButton("Сохранить", QMessageBox.AcceptRole)
        discard = box.addButton("Не сохранять", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"

    def _unsaved(self):
        if self.session is None or not self._modified:
            return False
        return self._typed or self.session.counts()["fixed"] > 0

    def close_document(self):
        """Close what is open (asking about unsaved fixes); False means the reader cancelled."""
        if self.doc is not None:
            self.editor.flush_edits()   # typing waiting for its timer counts as typed
        if self._unsaved():
            answer = self._ask_save_before_close()
            if answer == "cancel":
                return False
            if answer == "save":
                self.save_copy()
                if self._unsaved():
                    return False
        self._retire_task()
        if self.controller is not None:
            self.controller.close()
            self.controller.deleteLater()
            self.controller = None
        if self.doc is not None:
            self._remember(self.doc)
            release_document(self.doc)
        self.doc = self.session = None
        self._anchor = None
        self.card.hide()
        self.editor.set_checked_until(None)
        self.notice.clear()
        self.show_start_page()
        return True

    def closeEvent(self, event):
        started = time.monotonic()
        if self.close_document():
            for task in self._retiring:
                left = max(0, int((CLOSE_WAIT_S - (time.monotonic() - started)) * 1000))
                if not task.wait(left):
                    self.hard_exit = True   # still running: waiting longer would hang, destroying it would abort
                else:
                    task.close()
            if not self.hard_exit:
                self._retiring = []
            event.accept()
        else:
            event.ignore()

    def _remember(self, doc):
        if not doc.path or self.session is None or not self.settings["remember_recent"]:
            return
        counts = self.session.counts()
        stats = {"fixed": counts["fixed"], "skipped": counts["skipped"],
                 "handled": counts["total"] - counts["errors"] - counts["checks"], "total": counts["total"]}
        try:
            self.recent.touch(doc.path, stats)
        except OSError:
            pass  # a convenience, not data

    def _clear_recent(self):
        try:
            self.recent.clear()
        except OSError:
            pass
        self.start_screen.set_recent(self.recent.items())

    # --- check progress ---

    def _marks_changed(self, paragraphs):
        self.editor.repaint_paragraphs(paragraphs)
        self._refresh()

    def _progressed(self):
        c = self.controller
        if c is not None and c.progress is not None:
            self.progress.set_progress(c.progress.fraction(), c.progress.remaining_seconds(), time.time(), c.state)

    def _state_changed(self, state):
        self.actions["stop"].setEnabled(state == "running")
        self._progressed()
        if state == "running":
            if self._notice_kind == "resume":
                self.notice.clear()
                self._notice_kind = None
        elif state == "stopped":
            self._notify("Проверка остановлена.", RESUME, "resume")
        elif state == "failed":
            self._notify("Проверка прервалась. Найденные пометки сохранены.", RESUME, "resume")
        elif state == "done":
            self.editor.set_checked_until(None)
        self._refresh()

    def _stop(self):
        if self.controller is not None:
            self.controller.stop()

    def _notice_action(self):
        if self._notice_kind == "resume" and self.controller is not None:
            self.controller.resume()

    def _notify(self, text, action=None, kind="info"):
        self._notice_kind = kind
        self.notice.show_notice(text, action)

    def _clear_stale_notice(self):
        if self._notice_kind in ("saved", "storage", "done"):
            self.notice.clear()
            self._notice_kind = None

    # --- the review: one place that redraws the card, counters and frame ---

    def _refresh(self):
        if self.session is None:
            return
        counts = self.session.counts()
        self.status.set_counts(counts)
        self.actions["accept_all"].setEnabled(counts["errors"] > 0 and self.editor.isReadOnly())
        if not self.editor.isReadOnly():
            self.card.hide()      # the reader is typing: no marks on the screen
            return
        mark = self.session.current
        if mark is not None and mark.status == OPEN:
            text = self.session.text(mark.paragraph)
            a, b = self.session.span(mark)
            self.card.show_mark(mark, text[max(0, a - CONTEXT_CHARS):a], text[b:b + CONTEXT_CHARS])
            self.card.show()
            self.editor.show_current()
            self._place_card()
        else:
            self._anchor = None
            self.card.hide()
            self.editor.show_current()
            if self.controller is not None and self.controller.state == "done" and self._notice_kind != "saved":
                self._notify(ALL_DONE if counts["total"] else NOTHING_FOUND, kind="done")

    def _set_anchor(self, rect):
        self._anchor = rect
        self._place_card()

    def _place_card(self):
        if self._anchor is None or not self.card.isVisible():
            return
        viewport = self.editor.viewport().rect()
        width = max(200, min(CARD_WIDTH, viewport.width() - CARD_SIDE_GAP))
        self.card.setFixedWidth(width)
        layout = self.card.layout()
        height = layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else self.card.sizeHint().height()
        self.card.resize(width, max(height, self.card.sizeHint().height()))
        self.card.move(card_position(viewport, self._anchor, self.card.size()))
        self.card.raise_()

    def _mark_clicked(self, mark_id):
        if self.session is not None and self.editor.isReadOnly():
            self.session.select(mark_id)
            self._refresh()

    def _go_next(self):
        self.session.go_next()
        self._refresh()

    def _go_prev(self):
        self.session.go_prev()
        self._refresh()

    def _reviewing(self):
        return self.session is not None and self.editor.isReadOnly()

    def _changed(self, paragraphs):
        """Repaint what changed (the session already moved on to the next mark) and redraw the card."""
        self._modified = True
        self._clear_stale_notice()
        self.editor.repaint_paragraphs(paragraphs)
        self._refresh()

    def _accept(self):
        mark = self.session.current if self._reviewing() else None
        if mark is None or mark.fix is None:
            return
        edits = self.session.accept()
        self._changed({mark.paragraph} | {e.paragraph for e in edits})

    def _skip(self):
        mark = self.session.current if self._reviewing() else None
        if mark is None:
            return
        self.session.skip()
        self._changed({mark.paragraph})

    def _manual(self, text):
        mark = self.session.current if self._reviewing() else None
        if mark is None:
            return
        edits = self.session.manual(text)
        self._changed({mark.paragraph} | {e.paragraph for e in edits})

    def _to_dictionary(self):
        mark = self.session.current if self._reviewing() else None
        if mark is None or not mark.can_add_to_dictionary:
            return
        word = mark.original.strip().lower()
        affected = {m.paragraph for m in self.session.marks
                    if m.status == OPEN and m.can_add_to_dictionary and m.original.strip().lower() == word}
        try:
            self.session.add_to_dictionary()
        except OSError:
            self._notify(DICTIONARY_FAILED, kind="storage")
            return
        self._changed(affected | {mark.paragraph})

    def _accept_all(self):
        if not self._reviewing():
            return
        affected = {m.paragraph for m in self.session.marks if m.status == OPEN and m.level == "error" and m.fix}
        edits = self.session.accept_all_errors()
        self._changed(affected | {e.paragraph for e in edits})

    def _undo(self):
        if not self._reviewing():
            return
        before = {m.id: m.status for m in self.session.marks}
        try:
            edits = self.session.undo()
        except OSError:
            self._notify(DICTIONARY_FAILED_ON_UNDO, kind="storage")
            return
        changed = {m.paragraph for m in self.session.marks if before.get(m.id) != m.status}
        self._changed(changed | {e.paragraph for e in edits})

    # --- typing in a pasted text ---

    def _edit_mode_changed(self, editing):
        self._sync_shortcuts()
        self.status.set_editing(editing)
        self.actions["accept_all"].setEnabled(not editing and self.session is not None
                                              and self.session.counts()["errors"] > 0)
        if editing:
            self.card.hide()
            self._anchor = None
        else:
            self._refresh()

    def _paragraph_edited(self, index):
        self._modified = self._typed = True
        if self.controller is not None:
            self.controller.recheck([index])
        if self.session is not None:
            self.status.set_counts(self.session.counts())

    # --- saving ---

    def _stats_notice(self, report):
        text = "Сохранено: %s" % report.path
        if report.skipped:
            text += ". Не удалось применить исправлений: %d" % len(report.skipped)
        return text

    def _saved(self, report):
        self._modified = self._typed = False
        self._notify(self._stats_notice(report), kind="saved")
        self._remember(self.doc)

    def _save_failed(self, error, offer_save_as):
        if offer_save_as:
            question = "%s\n\nСохранить под другим именем?" % error
            if self._say("question", question, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.save_as()
        else:
            self._say("warning", str(error))

    def save_copy(self):
        if self.doc is None:
            return
        self.editor.flush_edits()
        if not self.doc.path:
            self.save_as()
            return
        try:
            report = export.save_corrected_copy(self.doc, self.session)
        except DocumentError as e:
            self._save_failed(e, offer_save_as=True)
        else:
            self._saved(report)

    def _default_name(self):
        if self.doc.path:
            stem = os.path.splitext(os.path.basename(self.doc.path))[0]
            return os.path.join(os.path.dirname(self.doc.path), "%s (исправлено).%s" % (stem, self.doc.saved_as))
        return "Вставленный текст.docx"

    def save_as(self, path=None):
        if self.doc is None:
            return
        self.editor.flush_edits()
        if not path:
            filters = ";;".join(label for label, _ in export.FORMATS)
            path, chosen = QFileDialog.getSaveFileName(self, "Сохранить как", self._default_name(), filters, "",
                                                       QFileDialog.DontConfirmOverwrite)
            if not path:
                return
            if not os.path.splitext(path)[1]:
                ext = next((e for label, e in export.FORMATS if label == chosen), "docx")
                path += "." + ext
        if export.needs_overwrite_confirmation(path, self.doc):
            question = "Файл «%s» уже есть. Заменить его?" % os.path.basename(path)
            if self._say("question", question, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        try:
            report = export.save_as(self.doc, self.session, path)
        except DocumentError as e:
            self._save_failed(e, offer_save_as=False)
        else:
            self._saved(report)

    def copy_with_formatting(self):
        if self.doc is None:
            return
        self.editor.flush_edits()
        export.copy_corrected(self.doc, self.session, QGuiApplication.clipboard())
        self._notify("Текст скопирован в буфер обмена.", kind="saved")

    # --- windows of Task 13 ---

    def _show_dictionary(self):
        DictionaryDialog(self.dictionary, self).exec_()

    def _show_settings(self):
        SettingsDialog(self.settings, self).exec_()
        self._apply_show_checks()

    def _show_help(self):
        HotkeysDialog(self).exec_()

    def _apply_show_checks(self):
        """Redraw the found marks after the «проверьте» setting changed (only when it really changed)."""
        value = bool(self.settings["show_checks"])
        if self.session is None or self.session.show_checks == value:
            return
        self.session.set_show_checks(value)
        self.editor.set_show_checks(value)
        self.editor.repaint_paragraphs(range(len(self.session.originals)))
        self._refresh()
