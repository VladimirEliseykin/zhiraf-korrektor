import os

from PySide2.QtWidgets import QApplication, QMessageBox

from zhiraf import storage
from zhiraf.ui import app, shortcut


class FakeWindow:
    def __init__(self):
        self.notices = []

    def _notify(self, text, action=None, kind="info"):
        self.notices.append(text)


class Asker:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def __call__(self, window):
        self.calls += 1
        return self.answer


class Maker:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def __call__(self, target, desktop):
        self.calls.append((target, desktop))
        if self.error:
            raise self.error
        return os.path.join(desktop, shortcut.LINK_NAME)


def _setup(monkeypatch, tmp_path, launcher="C:/z/Жираф.Корректор.exe", desktop=True):
    monkeypatch.setattr(shortcut, "launcher_path", lambda: launcher)
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: str(tmp_path) if desktop else None)
    return storage.Settings(str(tmp_path / "s.json"))


def test_default_flag_is_false():
    assert storage.DEFAULT_SETTINGS["shortcut_offered"] is False


def test_no_launcher_on_linux_and_no_question(tmp_path):
    assert shortcut.launcher_path() is None
    ask, make = Asker(True), Maker()
    shortcut.offer_shortcut(FakeWindow(), storage.Settings(str(tmp_path / "s.json")), ask=ask, create=make)
    assert ask.calls == 0 and make.calls == []


def test_yes_creates_once_and_sets_flag(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)
    ask, make = Asker(True), Maker()
    shortcut.offer_shortcut(FakeWindow(), settings, ask=ask, create=make)
    assert len(make.calls) == 1 and settings["shortcut_offered"] is True
    shortcut.offer_shortcut(FakeWindow(), settings, ask=ask, create=make)
    assert ask.calls == 1 and len(make.calls) == 1   # the second start asks nothing


def test_no_does_not_create_but_sets_flag(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)
    ask, make = Asker(False), Maker()
    shortcut.offer_shortcut(FakeWindow(), settings, ask=ask, create=make)
    assert ask.calls == 1 and make.calls == [] and settings["shortcut_offered"] is True


def test_create_failure_shows_notice(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)
    window = FakeWindow()
    shortcut.offer_shortcut(window, settings, ask=Asker(True), create=Maker(OSError("x")))
    assert window.notices == ["Не удалось создать ярлык: рабочий стол недоступен."]


def test_no_desktop_shows_notice(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path, desktop=False)
    window, make = FakeWindow(), Maker()
    shortcut.offer_shortcut(window, settings, ask=Asker(True), create=make)
    assert make.calls == [] and len(window.notices) == 1


def test_existing_shortcut_is_kept_without_question(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)
    (tmp_path / shortcut.LINK_NAME).write_text("x")
    ask, make = Asker(True), Maker()
    shortcut.offer_shortcut(FakeWindow(), settings, ask=ask, create=make)
    assert ask.calls == 0 and make.calls == []


def test_settings_write_failure_is_ignored(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)

    def broken(key, value):
        raise OSError("disk")
    monkeypatch.setattr(settings, "set", broken)
    make = Maker()
    shortcut.offer_shortcut(FakeWindow(), settings, ask=Asker(True), create=make)
    assert len(make.calls) == 1


def test_window_closed_before_answer_breaks_nothing(monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)

    def gone(window):
        raise RuntimeError("Internal C++ object already deleted")
    shortcut.offer_shortcut(FakeWindow(), settings, ask=gone, create=Maker())


def test_default_question_uses_the_window_dialog(qtbot, monkeypatch, tmp_path):
    settings = _setup(monkeypatch, tmp_path)
    asked = []

    class Window(FakeWindow):
        def _say(self, kind, text, buttons=None):
            asked.append((kind, text))
            return QMessageBox.Yes
    make = Maker()
    shortcut.offer_shortcut(Window(), settings, create=make)
    assert asked == [("question", "Создать ярлык «Жираф.Корректор» на рабочем столе?")] and len(make.calls) == 1


def test_main_offers_the_shortcut_after_showing_the_window(qtbot, full_models_dir, monkeypatch):
    monkeypatch.setenv("ZHIRAF_MODELS", full_models_dir)
    seen = []
    monkeypatch.setattr(shortcut, "offer_shortcut",
                        lambda window, settings: seen.append((window.isVisible(), settings)))
    monkeypatch.setattr(QApplication, "exec_", staticmethod(lambda: QApplication.processEvents() or 0))
    assert app.main(["zhiraf"]) == 0
    assert len(seen) == 1 and seen[0][0] is True
