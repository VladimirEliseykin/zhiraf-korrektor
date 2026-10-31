import time
import os

from PySide2.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide2.QtGui import QDropEvent
from PySide2.QtTest import QTest
from PySide2.QtWidgets import QLabel

from zhiraf import storage
from zhiraf.ui import theme
from zhiraf.ui.start_screen import StartScreen


def _item(path, fixed=0, skipped=0, handled=0, total=0):
    return {"path": path, "opened_at": 1700000000,
            "stats": {"fixed": fixed, "skipped": skipped, "handled": handled, "total": total}}


def _drop(screen, mime):
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    screen.dropEvent(event)
    return event


def _texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def test_buttons_emit(qapp):
    screen = StartScreen()
    seen = []
    screen.open_requested.connect(lambda: seen.append("open"))
    screen.paste_requested.connect(lambda: seen.append("paste"))
    screen.open_button.click()
    screen.paste_button.click()
    assert seen == ["open", "paste"]
    assert "Ctrl+V" in screen.paste_button.text() and "Ctrl+O" in screen.open_button.text()


def test_no_shortcuts_here(qapp):
    from PySide2.QtWidgets import QShortcut
    assert StartScreen().findChildren(QShortcut) == []


def test_texts_and_picture(qapp):
    screen = StartScreen()
    screen.resize(900, 600)
    screen.show()
    texts = _texts(screen)
    assert "Проверим документ на ошибки?" in texts
    assert "F1 — горячие клавиши · Работает без интернета" in texts
    assert screen.pixmap_label.pixmap().isNull() is False
    assert screen.logo_label.pixmap().isNull() is False
    screen.resize(500, 300)
    assert screen.pixmap_label.pixmap().height() <= 300


def test_recent_rows(qapp, tmp_path):
    real = tmp_path / "a.docx"
    real.write_text("x")
    screen = StartScreen()
    screen.set_recent([_item(str(real), fixed=12, skipped=3), _item(str(real), handled=14, total=23),
                       _item(str(tmp_path / "gone.odt"))])
    assert len(screen.recent_rows) == 3
    texts = _texts(screen)
    assert "✓ 12 исправлено, 3 пропущено" in texts
    assert "разобрано 14 из 23" in texts
    assert time.strftime("%d.%m.%Y", time.localtime(1700000000)) in texts
    assert "файл не найден" in _texts(screen.recent_rows[2])
    assert "файл не найден" not in _texts(screen.recent_rows[0])
    assert theme.COLORS["skipped"] in screen.recent_rows[2].styleSheet()


def test_recent_empty_hides_block(qapp):
    screen = StartScreen()
    screen.show()
    screen.set_recent([])
    assert screen.recent_block.isHidden()
    assert not screen.clear_link.isHidden()
    screen.set_recent([_item("/x/a.docx")])
    assert not screen.recent_block.isHidden()


def test_recent_click_and_missing(qapp, tmp_path):
    screen = StartScreen()
    missing = str(tmp_path / "gone.docx")
    screen.set_recent([_item(missing)])
    chosen = []
    screen.recent_chosen.connect(chosen.append)
    QTest.mouseClick(screen.recent_rows[0], Qt.LeftButton)
    assert chosen == [missing]


def test_clear_link(qapp):
    screen = StartScreen()
    hits = []
    screen.clear_recent_requested.connect(lambda: hits.append(1))
    screen.clear_link.click()
    assert hits == [1]


def test_recent_limit(qapp):
    screen = StartScreen()
    screen.set_recent([_item("/x/%d.docx" % i) for i in range(100)])
    assert len(screen.recent_rows) <= storage.MAX_RECENT


def test_drop_any_local_file(qapp, tmp_path):
    screen = StartScreen()
    got = []
    screen.file_dropped.connect(got.append)
    for name in ("a.pdf", "b.docx"):
        path = str(tmp_path / name)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        _drop(screen, mime)
        assert got[-1] == path
    assert len(got) == 2


def test_drop_ignores_non_files(qapp):
    screen = StartScreen()
    got = []
    screen.file_dropped.connect(got.append)
    web = QMimeData()
    web.setUrls([QUrl("http://example.com/a.docx")])
    _drop(screen, web)
    text = QMimeData()
    text.setText("hello")
    _drop(screen, text)
    assert got == []


def test_malformed_recent_does_not_crash(qapp, tmp_path):
    import json
    real = tmp_path / "a.docx"
    real.write_text("x")
    raw = [{"path": str(real), "opened_at": "bad", "stats": {"fixed": 1, "handled": None, "total": 3}}]
    p = tmp_path / "r.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    items = storage.Recent(storage.Settings(), str(p)).items()
    screen = StartScreen()
    screen.set_recent(items)
    assert len(screen.recent_rows) == 1
    assert "01.01.1970" not in _texts(screen)


def test_small_window_not_pinned_by_picture(qapp):
    from PySide2.QtWidgets import QApplication
    screen = StartScreen()
    screen.resize(600, 300)
    screen.show()
    QApplication.processEvents()
    assert screen.width() <= 600
    assert screen.pixmap_label.pixmap().height() <= screen.pixmap_label.height()


def test_recent_scrolls_when_small(qapp):
    from PySide2.QtWidgets import QApplication
    screen = StartScreen()
    screen.resize(900, 400)
    screen.show()
    screen.set_recent([_item("/x/%d.docx" % i) for i in range(100)])
    QApplication.processEvents()
    assert len(screen._list.findChildren(type(screen.recent_rows[0]))) <= storage.MAX_RECENT
    assert screen.recent_scroll.verticalScrollBar().maximum() > 0


def test_recent_path_is_plain_text(qapp, tmp_path):
    from PySide2.QtCore import Qt
    screen = StartScreen()
    screen.set_recent([_item(str(tmp_path / "<i>x.docx"))])
    row = screen.recent_rows[0]
    assert row.name_label.textFormat() == Qt.PlainText and row.folder_label.textFormat() == Qt.PlainText
    assert row.name_label.text() == "<i>x.docx"
