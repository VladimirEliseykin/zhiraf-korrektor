"""Start screen: picture, two big buttons, drop zone and the list of recent documents."""
import os
import time

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QPixmap
from PySide2.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from zhiraf import storage
from zhiraf.ui import theme

_ICONS = {".docx": "W", ".doc": "W", ".odt": "O", ".txt": "T"}


def result_text(stats):
    """Summary of a recent document: «✓ 12 исправлено, 3 пропущено» / «разобрано 14 из 23» / empty."""
    stats = stats or {}
    fixed, skipped = stats.get("fixed", 0), stats.get("skipped", 0)
    if fixed or skipped:
        return "✓ %d исправлено, %d пропущено" % (fixed, skipped)
    if stats.get("total"):
        return "разобрано %d из %d" % (stats.get("handled", 0), stats["total"])
    return ""


class _RecentRow(QFrame):
    chosen = Signal(str)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.path = item["path"]
        self.missing = not os.path.exists(self.path)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("recentRow")
        grey = theme.COLORS["skipped"]
        color = grey if self.missing else theme.COLORS["ink"]
        self.setStyleSheet("#recentRow { border-bottom: 1px solid %s; } #recentRow QLabel { color: %s; }"
                           % (theme.COLORS["moon"], color))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        badge = QLabel(_ICONS.get(os.path.splitext(self.path)[1].lower(), "?"), self)
        badge.setFixedWidth(22)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("font-weight: bold; color: %s;" % grey)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel(os.path.basename(self.path), self)
        folder = QLabel(os.path.dirname(self.path), self)
        for label in (name, folder):
            label.setTextFormat(Qt.PlainText)   # a path is never markup
        self.name_label, self.folder_label = name, folder
        names.addWidget(name)
        folder.setStyleSheet("font-size: 11px; color: %s;" % grey)
        names.addWidget(folder)
        layout.addWidget(badge)
        layout.addLayout(names, 1)
        right = QVBoxLayout()
        right.setSpacing(0)
        opened = item.get("opened_at")
        try:
            stamp = time.strftime("%d.%m.%Y", time.localtime(opened)) if opened is not None else ""
        except (OverflowError, OSError, ValueError, TypeError):
            stamp = ""
        date = QLabel(stamp, self)
        date.setAlignment(Qt.AlignRight)
        right.addWidget(date)
        summary = "файл не найден" if self.missing else result_text(item.get("stats"))
        note = QLabel(summary, self)
        note.setAlignment(Qt.AlignRight)
        right.addWidget(note)
        layout.addLayout(right)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.path)
        super().mouseReleaseEvent(event)


class _Picture(QLabel):
    """Night-sky panel with the picture scaled to the full height."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._source = QPixmap(path)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setStyleSheet("background: %s;" % theme.COLORS["sky"])
        self._rescale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if not self._source.isNull():
            scaled = self._source.scaled(self.width(), self.height(), Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation)
            self.setPixmap(scaled)


class StartScreen(QWidget):
    open_requested = Signal()
    paste_requested = Signal()
    file_dropped = Signal(str)
    recent_chosen = Signal(str)
    clear_recent_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.recent_rows = []
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.pixmap_label = _Picture(theme.art_path("start.jpg"), self)
        root.addWidget(self.pixmap_label, 1)

        right = QWidget(self)
        column = QVBoxLayout(right)
        column.setContentsMargins(32, 28, 32, 12)
        column.setSpacing(10)
        head = QHBoxLayout()
        self.logo_label = QLabel(right)
        self.logo_label.setPixmap(QPixmap(theme.art_path("logo.png")).scaled(
            56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        title = QLabel("Проверим документ на ошибки?", right)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        title.setWordWrap(True)
        head.addWidget(self.logo_label)
        head.addWidget(title, 1)
        column.addLayout(head)
        sub = QLabel("Проверка идёт на этом компьютере, текст никуда не отправляется", right)
        sub.setWordWrap(True)
        sub.setStyleSheet("color: %s;" % theme.COLORS["skipped"])
        column.addWidget(sub)

        buttons = QVBoxLayout()
        self.paste_button = QPushButton("Вставить текст  (Ctrl+V)", right)
        self.open_button = QPushButton("Открыть документ  (Ctrl+O · .docx, .doc, .odt)", right)
        self.paste_button.clicked.connect(self.paste_requested)
        self.open_button.clicked.connect(self.open_requested)
        buttons.addWidget(self.paste_button)
        buttons.addWidget(self.open_button)
        column.addLayout(buttons)

        drop = QLabel("Или перетащите документ сюда", right)
        drop.setAlignment(Qt.AlignCenter)
        drop.setMinimumHeight(70)
        drop.setStyleSheet("border: 2px dashed %s; border-radius: 6px; color: %s;"
                           % (theme.COLORS["skipped"], theme.COLORS["skipped"]))
        column.addWidget(drop)

        self.recent_block = QWidget(right)
        block = QVBoxLayout(self.recent_block)
        block.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Недавние документы", self.recent_block)
        heading.setStyleSheet("font-weight: bold;")
        block.addWidget(heading)
        self.recent_scroll = QScrollArea(self.recent_block)
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFrameShape(QFrame.NoFrame)
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch(1)
        self.recent_scroll.setWidget(self._list)
        block.addWidget(self.recent_scroll, 1)
        column.addWidget(self.recent_block, 1)

        self.clear_link = QPushButton("Очистить список", right)
        self.clear_link.setFlat(True)
        self.clear_link.setCursor(Qt.PointingHandCursor)
        self.clear_link.setStyleSheet("QPushButton { background: transparent; color: %s; text-decoration: underline;"
                                      " text-align: left; padding: 2px 0; }" % theme.COLORS["sky"])
        self.clear_link.clicked.connect(self.clear_recent_requested)
        column.addWidget(self.clear_link, 0, Qt.AlignLeft)

        footer = QLabel("F1 — горячие клавиши · Работает без интернета", right)
        footer.setStyleSheet("color: %s; font-size: 11px;" % theme.COLORS["skipped"])
        column.addWidget(footer)
        root.addWidget(right, 2)
        self.set_recent([])

    def set_recent(self, items):
        for row in self.recent_rows:
            row.setParent(None)
            row.deleteLater()
        self.recent_rows = []
        for item in list(items)[:storage.MAX_RECENT]:
            row = _RecentRow(item, self._list)
            row.chosen.connect(self.recent_chosen)
            self._list_layout.insertWidget(len(self.recent_rows), row)
            self.recent_rows.append(row)
        self.recent_block.setVisible(bool(self.recent_rows))

    @staticmethod
    def _local_paths(mime):
        if not mime.hasUrls():
            return []
        return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]

    def dragEnterEvent(self, event):
        if self._local_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._local_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.file_dropped.emit(paths[0])
