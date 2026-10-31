"""Small dialogs: the hotkeys help, the user's dictionary and the settings.

Every write to the profile can fail (no access to the folder): the dialog then says so calmly in its own
label and keeps showing what is really stored.
"""
from typing import List, Tuple

from PySide2.QtCore import Qt
from PySide2.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout)

from . import theme

HOTKEYS = [("← →", "К предыдущей или следующей пометке"), ("Enter", "Принять исправление"),
           ("Ctrl+Z", "Отменить последнее действие"), ("Ctrl+O", "Открыть документ"),
           ("Ctrl+V", "Вставить текст"), ("Ctrl+S", "Сохранить исправленную копию"),
           ("Esc", "Вернуться к разбору пометок"), ("F1", "Эта справка")]  # type: List[Tuple[str, str]]

DICTIONARY_FAILED = "Не удалось записать словарь: нет доступа к папке профиля. Список остался прежним."
EXPORT_FAILED = "Не удалось сохранить файл. Выберите другую папку."
IMPORT_FAILED = "Не удалось прочитать файл."
SETTINGS_FAILED = "Не удалось записать настройки: нет доступа к папке профиля. Прежние значения сохранены."
TEXT_FILTER = "Текстовые файлы (*.txt);;Все файлы (*)"
DICTIONARY_TITLE = "Словарь"

SETTING_LABELS = (("show_checks", "Показывать пометки «проверьте»"),
                  ("strict_mode", "Строгий режим: заглавные буквы посреди предложения"),
                  ("remember_recent", "Запоминать недавние документы"))
SETTING_HINTS = {"show_checks": "Скрытые пометки появятся снова; новые — со следующей проверки.",
                 "strict_mode": "Начнёт действовать при следующей проверке"}


def _error_label():
    label = QLabel("")
    label.setWordWrap(True)
    label.setStyleSheet("color: %s;" % theme.COLORS["error"])
    label.hide()
    return label


def _show_error(label, text):
    label.setText(text)
    label.setVisible(bool(text))


class HotkeysDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Справка")
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        for row, (keys, text) in enumerate(HOTKEYS):
            key_label = QLabel("<b>%s</b>" % keys)
            key_label.setTextFormat(Qt.RichText)
            grid.addWidget(key_label, row, 0)
            grid.addWidget(QLabel(text), row, 1)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def rows(self):
        return list(HOTKEYS)


class DictionaryDialog(QDialog):
    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle(DICTIONARY_TITLE)
        self.resize(420, 480)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск")
        self.search.setClearButtonEnabled(True)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.error = _error_label()
        self.remove_button = QPushButton("Удалить")
        self.export_button = QPushButton("Выгрузить…")
        self.import_button = QPushButton("Загрузить…")
        close = QPushButton("Закрыть")
        buttons = QHBoxLayout()
        for button in (self.remove_button, self.export_button, self.import_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.error)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self._fill)
        self.remove_button.clicked.connect(self.remove_selected)
        self.export_button.clicked.connect(self.export_words)
        self.import_button.clicked.connect(self.import_words)
        close.clicked.connect(self.accept)
        self._fill()

    def shown_words(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _fill(self, *_):
        needle = self.search.text().strip().lower()
        self.list.clear()
        self.list.addItems([w for w in self.dictionary.words() if needle in w.lower()])

    def remove_selected(self):
        _show_error(self.error, "")
        try:
            for item in self.list.selectedItems():
                self.dictionary.remove(item.text())
        except OSError:
            _show_error(self.error, DICTIONARY_FAILED)
        self._fill()

    def export_words(self):
        _show_error(self.error, "")
        path, _ = QFileDialog.getSaveFileName(self, "Выгрузить словарь", "словарь.txt", TEXT_FILTER)
        if not path:
            return
        try:
            self.dictionary.export(path)
        except OSError:
            _show_error(self.error, EXPORT_FAILED)

    def import_words(self):
        _show_error(self.error, "")
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить словарь", "", TEXT_FILTER)
        if not path:
            return
        try:
            added = self.dictionary.import_from(path)
        except OSError:
            _show_error(self.error, DICTIONARY_FAILED)
            self._fill()
            return
        self.setWindowTitle("%s — добавлено %d" % (DICTIONARY_TITLE, added))
        self._fill()


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Настройки")
        layout = QVBoxLayout(self)
        self.boxes = {}
        for key, text in SETTING_LABELS:
            box = QCheckBox(text)
            self.boxes[key] = box
            layout.addWidget(box)
            if key in SETTING_HINTS:
                hint = QLabel(SETTING_HINTS[key])
                hint.setWordWrap(True)
                hint.setContentsMargins(24, 0, 0, 6)
                hint.setStyleSheet("color: %s;" % theme.COLORS["skipped"])
                layout.addWidget(hint)
        self.error = _error_label()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Принять")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._load()

    def _load(self):
        for key, box in self.boxes.items():
            box.setChecked(bool(self.settings[key]))

    def accept(self):
        written = []   # (key, value before this apply)
        try:
            for key, box in self.boxes.items():
                value = box.isChecked()
                old = self.settings[key]
                if value != old:
                    self.settings.set(key, value)
                    written.append((key, old))
        except OSError:
            for key, old in reversed(written):
                try:
                    self.settings.set(key, old)
                except OSError:
                    pass   # the file is not writable at all; memory is already restored by Settings
            self._load()
            _show_error(self.error, SETTINGS_FAILED)
            return
        super().accept()
