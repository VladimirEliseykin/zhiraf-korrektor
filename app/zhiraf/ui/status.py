"""Status bar: counters with «accept all», progress bar with the moon, and the notice bar."""
import math
import time

from PySide2.QtCore import QRectF, Qt, Signal
from PySide2.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PySide2.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from zhiraf.ui import theme

_COUNT_WORDS = (("errors", "ошибок"), ("checks", "проверить"), ("fixed", "исправлено"), ("skipped", "пропущено"))
_ICON_FOR = {"errors": "error", "checks": "check", "fixed": "fixed", "skipped": "skipped"}
_TOOLTIP = "Исправит все ошибки (сейчас %d). Пометки «проверить» останутся."


def _duration(seconds):
    """«≈ 4 мин», «≈ 1 ч 20 мин», «≈ 2 ч»; minutes are rounded up."""
    minutes = int(math.ceil(seconds / 60.0))
    if minutes < 60:
        return "≈ %d мин" % minutes
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return "≈ %d ч" % hours
    return "≈ %d ч %d мин" % (hours, rest)


def progress_text(fraction, remaining, now, state="running"):
    percent = min(100, max(0, int(fraction * 100 + 1e-9)))
    if state == "stopped":
        return "Проверка остановлена на %d%%" % percent
    if state == "failed":
        return "Проверка прервана на %d%%" % percent
    if state == "done" or fraction >= 1:
        return "Проверка завершена"
    text = "Проверено %d%%" % percent
    if remaining is None or remaining < 30:
        return text
    finish = time.strftime("%H:%M", time.localtime(now + remaining))
    return "%s · осталось %s · готово к %s" % (text, _duration(remaining), finish)


class _Bar(QWidget):
    """Blue bar with a softly glowing moon at its end."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fraction = 0.0
        self.setFixedHeight(18)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        track = QRectF(0, h / 2.0 - 3, self.width(), 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.COLORS["moon"]))
        painter.drawRoundedRect(track, 3, 3)
        end = max(0.0, min(1.0, self.fraction)) * self.width()
        painter.setBrush(QColor(theme.COLORS["sky"]))
        painter.drawRoundedRect(QRectF(0, h / 2.0 - 3, end, 6), 3, 3)
        if end > 0:
            glow = QRadialGradient(end, h / 2.0, h / 2.0)
            moon = QColor(theme.COLORS["moon"])
            glow.setColorAt(0, moon)
            faded = QColor(moon)
            faded.setAlpha(0)
            glow.setColorAt(1, faded)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QRectF(end - h / 2.0, 0, h, h))
        painter.end()


class ProgressPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar = _Bar(self)
        self.label = QLabel("", self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.bar)
        layout.addWidget(self.label)

    def set_progress(self, fraction, remaining, now, state="running"):
        self.bar.fraction = 1.0 if state == "done" else fraction
        self.bar.update()
        self.label.setText(progress_text(fraction, remaining, now, state))


class StatusPanel(QWidget):
    accept_all_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.labels = {}
        self.icons = {}
        for key, word in _COUNT_WORDS:
            name = _ICON_FOR[key]
            icon_label = QLabel(self)
            icon_label.setPixmap(theme.icon(name).pixmap(18, 18))
            label = QLabel("%s: 0" % word, self)
            label.setStyleSheet("color: %s;" % theme.COLORS[name])
            self.icons[key] = icon_label
            self.labels[key] = label
            layout.addWidget(icon_label)
            layout.addWidget(label)
        layout.addStretch(1)
        self.accept_all_button = QPushButton("Принять все ошибки", self)
        self.accept_all_button.setStyleSheet("padding-left: 30px;")
        self.help_badge = QLabel(self.accept_all_button)
        self.help_badge.setPixmap(theme.icon("help", color=theme.COLORS["paper"]).pixmap(18, 18))
        self.help_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.help_badge.setGeometry(8, 0, 18, 18)
        self.accept_all_button.clicked.connect(self.accept_all_clicked)
        layout.addWidget(self.accept_all_button)
        self.set_counts({})

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_badge()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_badge()

    def _place_badge(self):
        button = self.accept_all_button
        self.help_badge.move(8, (button.height() - self.help_badge.height()) // 2)

    def set_counts(self, counts):
        for key, word in _COUNT_WORDS:
            self.labels[key].setText("%s: %d" % (word, counts.get(key, 0)))
        errors = counts.get("errors", 0)
        badge = theme.COLORS["paper"] if errors > 0 else theme.COLORS["skipped"]
        self.help_badge.setPixmap(theme.icon("help", color=badge).pixmap(18, 18))
        self.accept_all_button.setEnabled(errors > 0)
        self.accept_all_button.setToolTip(_TOOLTIP % errors)
        self._place_badge()


class NoticeBar(QFrame):
    action_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("NoticeBar { background: %s; border: 1px solid %s; border-radius: 4px; }"
                           % (theme.COLORS["moon"], theme.COLORS["check"]))
        layout = QHBoxLayout(self)
        self.text_label = QLabel("", self)
        self.text_label.setWordWrap(True)
        self.action_button = QPushButton(self)
        self.action_button.clicked.connect(self.action_clicked)
        layout.addWidget(self.text_label, 1)
        layout.addWidget(self.action_button)
        self.hide()

    def show_notice(self, text, action=None):
        self.text_label.setText(text)
        self.action_button.setText(action or "")
        self.action_button.setVisible(bool(action))
        self.show()

    def clear(self):
        self.text_label.setText("")
        self.hide()
