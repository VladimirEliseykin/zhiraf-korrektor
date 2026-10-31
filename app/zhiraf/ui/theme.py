"""Palette, status icons (inline SVG) and the stylesheet of the window."""
import os

from PySide2.QtCore import QByteArray, Qt
from PySide2.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide2.QtSvg import QSvgRenderer

import zhiraf

COLORS = {
    "sky": "#56708f", "paper": "#f6f3ec", "ink": "#2b2f36", "moon": "#e9e4d8",
    "error": "#b9524a", "check": "#d9a521", "fixed": "#3f9a4e", "skipped": "#8792a2",
}
LEVEL_LABEL = {"error": "Ошибка", "check": "Проверьте"}

_STROKE = 'fill="none" stroke="%(c)s" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'
_SVG = {
    "error": '<path d="M6 6L18 18M18 6L6 18" %s/>',
    "check": '<path d="M12 3.5L22 20H2Z" %s/><path d="M12 10V14.5" %s/><circle cx="12" cy="17.4" r="0.6" %s/>',
    "fixed": '<circle cx="12" cy="12" r="9.5" %s/><path d="M7.5 12.5L10.8 15.8L16.8 9" %s/>',
    "skipped": '<path d="M5 14A7.5 7.5 0 0 1 18.5 9.5" %s/><path d="M19.5 4.5V10H14" %s/>',
    "help": '<circle cx="12" cy="12" r="9.5" %s/><path d="M9.2 9.6A2.9 2.9 0 0 1 14.8 10.4C14.8 12.4 12 12.4 12 14.6" %s/>'
            '<circle cx="12" cy="17.6" r="0.6" %s/>',
}
_DEFAULT_COLOR = {"error": "error", "check": "check", "fixed": "fixed", "skipped": "skipped", "help": "sky"}


def status_color(name):
    return COLORS[name]


def _svg(name, color):
    body = _SVG[name].replace("%s", _STROKE)
    body = body % {"c": color}
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">%s</svg>' % body


def icon(name, color=None, size=18):
    """QIcon of a status symbol, rendered from SVG at `size` (and 2x for sharp high-DPI screens)."""
    color = color or COLORS[_DEFAULT_COLOR[name]]
    renderer = QSvgRenderer(QByteArray(_svg(name, color).encode("utf-8")))
    result = QIcon()
    for scale in (1, 2):
        side = size * scale
        image = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        result.addPixmap(QPixmap.fromImage(image))
    return result


def art_path(name):
    """Picture shipped with the program: <root>/art if present, else the window's own art, else engine/art."""
    folders = (os.path.join(zhiraf.ROOT, "art"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "art"),
               os.path.join(zhiraf.ENGINE_DIR, "art"))
    for folder in folders:
        if os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return os.path.join(folders[0], name)


def stylesheet():
    c = COLORS
    return """
QMainWindow, QDialog { background: %(paper)s; color: %(ink)s; }
QWidget { color: %(ink)s; }
QToolTip { background: %(ink)s; color: %(paper)s; border: 0; padding: 4px 6px; }
QPushButton { background: %(sky)s; color: %(paper)s; border: 0; border-radius: 4px; padding: 6px 14px; }
QPushButton:disabled { background: %(moon)s; color: %(skipped)s; }
QProgressBar { background: %(moon)s; border: 0; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: %(sky)s; border-radius: 3px; }
""" % c
