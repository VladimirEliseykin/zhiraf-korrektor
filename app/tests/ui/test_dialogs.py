import os

import pytest
from PySide2.QtWidgets import QFileDialog

from zhiraf import storage
from zhiraf.ui import dialogs
from zhiraf.ui.dialogs import HOTKEYS, DictionaryDialog, HotkeysDialog, SettingsDialog

EXPECTED = [("← →", "К предыдущей или следующей пометке"), ("Enter", "Принять исправление"),
            ("Ctrl+Z", "Отменить последнее действие"), ("Ctrl+O", "Открыть документ"),
            ("Ctrl+V", "Вставить текст"), ("Ctrl+S", "Сохранить исправленную копию"),
            ("Esc", "Вернуться к разбору пометок"), ("F1", "Эта справка")]


def test_hotkeys_list_is_verbatim_and_shown(qtbot):
    assert HOTKEYS == EXPECTED
    d = HotkeysDialog()
    qtbot.addWidget(d)
    assert d.rows() == EXPECTED
    from PySide2.QtWidgets import QLabel
    texts = " ".join(label.text() for label in d.findChildren(QLabel))
    for keys, text in EXPECTED:
        assert keys in texts and text in texts


def make_dictionary(tmp_path, *words):
    d = storage.Dictionary(str(tmp_path / "d.txt"))
    for w in words:
        d.add(w)
    return d


def test_dictionary_search_is_case_insensitive(qtbot, tmp_path):
    dlg = DictionaryDialog(make_dictionary(tmp_path, "Жирафик", "Слон"))
    qtbot.addWidget(dlg)
    assert dlg.shown_words() == ["Жирафик", "Слон"]
    dlg.search.setText("жир")
    assert dlg.shown_words() == ["Жирафик"]


def test_dictionary_remove_selected_updates_file(qtbot, tmp_path):
    d = make_dictionary(tmp_path, "Жирафик", "Слон")
    dlg = DictionaryDialog(d)
    qtbot.addWidget(dlg)
    dlg.list.item(0).setSelected(True)
    dlg.remove_button.click()
    assert dlg.shown_words() == ["Слон"]
    assert storage.Dictionary(d.path).words() == ["Слон"]


def test_dictionary_import_cp1251_merges_and_counts(qtbot, tmp_path, monkeypatch):
    d = make_dictionary(tmp_path, "Слон")
    src = tmp_path / "in.txt"
    src.write_bytes("Жирафик\nСлон\nЗебра\n".encode("cp1251"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    dlg = DictionaryDialog(d)
    qtbot.addWidget(dlg)
    dlg.import_button.click()
    assert dlg.shown_words() == ["Жирафик", "Зебра", "Слон"]
    assert "добавлено 2" in dlg.windowTitle()


def test_dictionary_export_writes_the_words(qtbot, tmp_path, monkeypatch):
    out = tmp_path / "out.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    dlg = DictionaryDialog(make_dictionary(tmp_path, "Слон"))
    qtbot.addWidget(dlg)
    dlg.export_button.click()
    assert out.read_text(encoding="utf-8").split() == ["Слон"]


def test_dictionary_write_failure_shows_message_and_keeps_list(qtbot, tmp_path, monkeypatch):
    d = make_dictionary(tmp_path, "Жирафик", "Слон")
    os.remove(d.path)
    os.mkdir(d.path)      # a folder in place of the file: every write fails
    src = tmp_path / "in.txt"
    src.write_text("Зебра\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    dlg = DictionaryDialog(d)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.list.item(0).setSelected(True)
    dlg.remove_button.click()
    assert dlg.error.isVisible() and dlg.error.text() == dialogs.DICTIONARY_FAILED
    assert "OSError" not in dlg.error.text() and dlg.shown_words() == ["Жирафик", "Слон"]
    dlg.import_button.click()
    assert dlg.error.isVisible() and dlg.shown_words() == ["Жирафик", "Слон"]


def test_settings_boxes_reflect_and_write(qtbot, tmp_path):
    s = storage.Settings(str(tmp_path / "s.json"))
    s.set("strict_mode", True)
    dlg = SettingsDialog(s)
    qtbot.addWidget(dlg)
    assert [dlg.boxes[k].isChecked() for k in ("show_checks", "strict_mode", "remember_recent")] == [True, True, True]
    dlg.boxes["show_checks"].setChecked(False)
    dlg.accept()
    assert storage.Settings(s.path)["show_checks"] is False


def test_settings_write_failure_keeps_old_values(qtbot, tmp_path):
    s = storage.Settings(str(tmp_path / "s.json"))
    s.set("show_checks", True)
    os.remove(s.path)
    os.mkdir(s.path)
    dlg = SettingsDialog(s)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.boxes["show_checks"].setChecked(False)
    dlg.accept()
    assert dlg.error.isVisible() and dlg.boxes["show_checks"].isChecked() and s["show_checks"] is True


def test_settings_failure_on_second_key_rolls_back_the_first(qtbot, tmp_path, monkeypatch):
    s = storage.Settings(str(tmp_path / "s.json"))
    real = storage.Settings.set
    calls = []

    def flaky(self, key, value):
        calls.append(key)
        if len(calls) == 2:
            raise OSError("disk")
        return real(self, key, value)
    monkeypatch.setattr(storage.Settings, "set", flaky)
    dlg = SettingsDialog(s)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.boxes["show_checks"].setChecked(False)
    dlg.boxes["strict_mode"].setChecked(True)
    dlg.accept()
    assert s["show_checks"] is True and s["strict_mode"] is False
    assert dlg.boxes["show_checks"].isChecked() and not dlg.boxes["strict_mode"].isChecked()
    assert dlg.error.isVisible()
    assert storage.Settings(s.path)["show_checks"] is True


def test_strict_mode_hint_is_shown(qtbot, tmp_path):
    from PySide2.QtWidgets import QLabel
    dlg = SettingsDialog(storage.Settings(str(tmp_path / "s.json")))
    qtbot.addWidget(dlg)
    texts = [label.text() for label in dlg.findChildren(QLabel)]
    assert "Начнёт действовать при следующей проверке" in texts
    assert "Скрытые пометки появятся снова; новые — со следующей проверки." in texts
