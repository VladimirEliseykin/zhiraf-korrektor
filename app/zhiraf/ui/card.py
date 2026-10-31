"""The wide card that pops up under the current mark (layout variant B)."""
from html import escape

from PySide2.QtCore import QPoint, QSize, Qt, Signal
from PySide2.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from zhiraf.ui import theme

MARGIN = 12
_OWN_KEYS = (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)
HINTS = "← → — к другой пометке · Ctrl+Z — отменить"


def card_position(viewport, anchor, size, gap=8):
    """Top-left corner of the card: under the mark if it fits, else above it; kept inside the viewport sides."""
    x = min(anchor.left(), viewport.right() + 1 - MARGIN - size.width())
    x = max(x, viewport.left() + MARGIN)
    below = anchor.bottom() + 1 + gap
    if below + size.height() <= viewport.bottom() + 1:
        y = below
    else:
        y = max(viewport.top(), anchor.top() - gap - size.height())
    return QPoint(x, y)


class _ManualEdit(QLineEdit):
    """Line edit that reports Esc instead of passing it on to the window."""
    escaped = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            event.accept()
            self.escaped.emit()
            return
        super().keyPressEvent(event)
        if event.key() in _OWN_KEYS:
            event.accept()  # QLineEdit ignores these; the window must not see them


class MarkCard(QFrame):
    accept_clicked = Signal()
    skip_clicked = Signal()
    dictionary_clicked = Signal()
    manual_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        c = theme.COLORS
        self.setObjectName("markCard")
        self.setStyleSheet(
            "QFrame#markCard { background: %(moon)s; border: 1px solid %(skipped)s; border-radius: 8px; }"
            "QFrame#markCard QLabel { background: transparent; }" % c)
        self.setFocusPolicy(Qt.NoFocus)

        self.icon_label = QLabel()
        self.level_label = QLabel()
        self.context_label = QLabel()
        self.context_label.setTextFormat(Qt.PlainText)   # a document's words must never be read as markup
        self.context_label.setStyleSheet("color: %s;" % c["skipped"])
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self.icon_label)
        head.addWidget(self.level_label)
        head.addWidget(self.context_label, 1)

        self.fix_label = QLabel()
        self.fix_label.setTextFormat(Qt.RichText)
        self.message_label = QLabel()
        self.message_label.setTextFormat(Qt.PlainText)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: %s;" % c["skipped"])
        self.message_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line = QHBoxLayout()
        line.addWidget(self.fix_label)
        line.addStretch(1)
        line.addWidget(self.message_label, 1)

        self.accept_button = QPushButton("Принять (Enter)")
        self.skip_button = QPushButton("Пропустить")
        self.dictionary_button = QPushButton("В словарь")
        self.manual_button = QPushButton("Исправить вручную")
        self.manual_edit = _ManualEdit()
        self.manual_edit.hide()
        buttons = QHBoxLayout()
        for button in (self.accept_button, self.skip_button, self.dictionary_button, self.manual_button):
            button.setFocusPolicy(Qt.NoFocus)
            buttons.addWidget(button)
        buttons.addWidget(self.manual_edit, 1)
        buttons.addStretch(0)

        self.hints_label = QLabel(HINTS)
        self.hints_label.setStyleSheet("color: %s;" % c["skipped"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addLayout(line)
        layout.addLayout(buttons)
        layout.addWidget(self.hints_label)

        self.accept_button.clicked.connect(self.accept_clicked)
        self.skip_button.clicked.connect(self.skip_clicked)
        self.dictionary_button.clicked.connect(self.dictionary_clicked)
        self.manual_button.clicked.connect(self._open_manual)
        self.manual_edit.returnPressed.connect(lambda: self.manual_submitted.emit(self.manual_edit.text()))
        self.manual_edit.escaped.connect(self._close_manual)
        self._original = ""

    def show_mark(self, mark, before, after):
        color = theme.status_color(mark.level)
        self._original = mark.original
        self.icon_label.setPixmap(theme.icon(mark.level, size=18).pixmap(18, 18))
        self.level_label.setText(theme.LEVEL_LABEL[mark.level])
        self.level_label.setStyleSheet("color: %s; font-weight: bold;" % color)
        self.context_label.setText("…%s%s%s…" % (before, mark.original, after) if (before or after) else "")
        self.fix_label.setText(self._fix_html(mark))
        self.message_label.setText(mark.message)
        self.accept_button.setEnabled(mark.fix is not None)
        self.dictionary_button.setVisible(mark.can_add_to_dictionary)
        self._close_manual()

    @staticmethod
    def _fix_html(mark):
        if mark.fix is None:
            return escape(mark.original)
        old = "<s>%s</s>" % escape(mark.original) if mark.original else "нет запятой" if mark.fix.strip() == "," \
            else "нужно добавить"
        return "%s → <b>%s</b>" % (old, escape(mark.fix))

    def _open_manual(self):
        self.manual_edit.setText(self._original)
        self.manual_edit.show()
        self.manual_edit.setFocus()
        self.manual_edit.selectAll()

    def _close_manual(self):
        self.manual_edit.hide()

    def sizeHint(self):
        base = super().sizeHint()
        return QSize(max(base.width(), 640), base.height())
