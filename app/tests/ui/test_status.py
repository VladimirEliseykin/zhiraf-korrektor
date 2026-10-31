import time

from zhiraf.ui import theme
from zhiraf.ui.status import NoticeBar, ProgressPanel, StatusPanel, progress_text

NOW = 1700000000.0
COUNTS = {"errors": 3, "checks": 2, "fixed": 1, "skipped": 4}


def test_progress_text_with_estimate():
    text = progress_text(0.42, 240, NOW)
    assert "Проверено 42%" in text and "осталось ≈ 4 мин" in text and "готово к " in text
    assert time.strftime("%H:%M", time.localtime(NOW + 240)) in text


def test_progress_text_minutes_round_up():
    assert "≈ 2 мин" in progress_text(0.5, 61, NOW)


def test_progress_text_short_or_unknown_remaining():
    assert progress_text(0.97, 10, NOW) == "Проверено 97%"
    assert progress_text(0.5, None, NOW) == "Проверено 50%"


def test_progress_text_hours():
    assert "≈ 1 ч 20 мин" in progress_text(0.1, 4800, NOW)


def test_progress_text_exact_hours_have_no_zero_minutes():
    text = progress_text(0.1, 7200, NOW)
    assert "≈ 2 ч" in text and "0 мин" not in text


def test_progress_text_states():
    assert progress_text(1.0, 0, NOW) == "Проверка завершена"
    assert progress_text(0.3, 100, NOW, "done") == "Проверка завершена"
    assert progress_text(0.42, 100, NOW, "stopped") == "Проверка остановлена на 42%"
    assert progress_text(0.42, 100, NOW, "failed") == "Проверка прервана на 42%"


def test_progress_panel_shows_text(qtbot):
    panel = ProgressPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_progress(0.42, 240, NOW, "running")
    assert "Проверено 42%" in panel.label.text()
    panel.repaint()


def test_status_panel_counts_and_colors(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.set_counts(COUNTS)
    for key, word, n in (("errors", "ошибок", 3), ("checks", "проверить", 2),
                         ("fixed", "исправлено", 1), ("skipped", "пропущено", 4)):
        label = panel.labels[key]
        assert label.text() == "%s: %d" % (word, n)
    assert theme.COLORS["error"] in panel.labels["errors"].styleSheet()
    assert theme.COLORS["check"] in panel.labels["checks"].styleSheet()
    assert theme.COLORS["fixed"] in panel.labels["fixed"].styleSheet()
    assert theme.COLORS["skipped"] in panel.labels["skipped"].styleSheet()


def test_accept_all_button_enabled_with_tooltip(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_counts(COUNTS)
    button = panel.accept_all_button
    assert button.text() == "Принять все ошибки"
    assert button.toolTip() == "Исправит все ошибки (сейчас 3). Пометки «проверить» останутся."
    assert button.isEnabled()
    assert panel.help_badge.parent() is button


def test_accept_all_button_disabled_but_visible_at_zero(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_counts({"errors": 0, "checks": 2, "fixed": 0, "skipped": 0})
    assert not panel.accept_all_button.isEnabled()
    assert panel.accept_all_button.isVisible()


def test_accept_all_click_emits(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_counts(COUNTS)
    with qtbot.waitSignal(panel.accept_all_clicked, timeout=1000):
        panel.accept_all_button.click()


def test_notice_bar(qtbot):
    bar = NoticeBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.show_notice("Проверка прервана", "Продолжить с этого места")
    assert bar.isVisible() and bar.action_button.isVisible()
    assert bar.action_button.text() == "Продолжить с этого места"
    with qtbot.waitSignal(bar.action_clicked, timeout=1000):
        bar.action_button.click()
    bar.clear()
    assert not bar.isVisible()


def test_notice_without_action_hides_button(qtbot):
    bar = NoticeBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.show_notice("Готово")
    assert bar.isVisible() and not bar.action_button.isVisible()


def _dominant(label):
    image = label.pixmap().toImage()
    counts = {}
    for x in range(image.width()):
        for y in range(image.height()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200:
                counts[c.name()] = counts.get(c.name(), 0) + 1
    return max(counts, key=counts.get)


def test_help_badge_colour_follows_enabled_state(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.set_counts({"errors": 3})
    assert _dominant(panel.help_badge) == theme.COLORS["paper"]
    panel.set_counts({"errors": 0})
    assert _dominant(panel.help_badge) == theme.COLORS["skipped"]
    assert panel.help_badge.parent() is panel.accept_all_button


def _badge_pixels(panel, color):
    from PySide2.QtGui import QColor
    image = panel.accept_all_button.grab().toImage()
    want = QColor(color).rgb()
    return sum(1 for x in range(8, 26) for y in range(image.height())
               if (image.pixelColor(x, y).rgb() & 0xffffff) == (want & 0xffffff))


def test_help_badge_is_visible_with_the_theme_stylesheet(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.setStyleSheet(theme.stylesheet())
    panel.show()
    panel.set_counts(COUNTS)
    assert _badge_pixels(panel, theme.COLORS["paper"]) > 0
    panel.set_counts({"errors": 0})
    assert _badge_pixels(panel, theme.COLORS["skipped"]) > 0


def test_notice_text_is_plain(qtbot):
    from PySide2.QtCore import Qt
    bar = NoticeBar()
    qtbot.addWidget(bar)
    bar.show_notice("a <img src=x> &lt; b")
    assert bar.text_label.text() == "a <img src=x> &lt; b"
    assert bar.text_label.textFormat() == Qt.PlainText
