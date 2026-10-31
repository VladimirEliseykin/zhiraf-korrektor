import os
import subprocess
import sys
import threading
import time

from PySide2.QtCore import QSysInfo
from PySide2.QtWidgets import QMessageBox

from docfactory import P, R, make_docx
from zhiraf import storage
from zhiraf.ui import app, loader
from zhiraf.ui.main_window import MainWindow


def test_second_acquire_is_refused_until_unlock():
    first = app.acquire_single_instance()
    assert first is not None
    assert app.acquire_single_instance() is None
    first.unlock()
    again = app.acquire_single_instance()
    assert again is not None
    again.unlock()


def test_lock_of_a_dead_process_is_taken_over():
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    path = os.path.join(storage.data_dir(), app.LOCK_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("%d\nzhiraf\n%s\n" % (dead.pid, QSysInfo.machineHostName()))
    lock = app.acquire_single_instance()
    assert lock is not None
    lock.unlock()


def test_log_error_has_class_and_place_but_no_text():
    try:
        raise ValueError("секретный текст")
    except ValueError as exc:
        app.log_error(exc)
    with open(app.log_path(), encoding="utf-8") as f:
        text = f.read()
    assert "ValueError" in text and "test_app.py:" in text and "test_log_error_has_class" in text
    assert "секретный" not in text and " · " in text


def test_log_is_truncated_when_too_big():
    with open(app.log_path(), "w", encoding="utf-8") as f:
        f.write("старая строка\n" * 30000)
    assert os.path.getsize(app.log_path()) > app.LOG_LIMIT
    app.log_error_detail("новая: x.py:1:f")
    assert os.path.getsize(app.log_path()) < app.LOG_LIMIT
    with open(app.log_path(), encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[-1].endswith("новая: x.py:1:f") and lines[0] == "старая строка"


def test_log_write_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(app, "log_path", lambda: os.path.join(os.devnull, "x", "журнал.txt"))
    app.log_error_detail("anything")   # must not raise


def test_main_without_models_shows_the_folder_and_returns_2(qtbot, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setenv("ZHIRAF_MODELS", str(tmp_path / "нет-такой"))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    assert app.main(["zhiraf"]) == 2
    assert len(shown) == 1 and str(tmp_path / "нет-такой") in shown[0]
    lock = app.acquire_single_instance()   # the lock was released
    assert lock is not None
    lock.unlock()


def test_main_second_copy_gets_the_message_and_0(qtbot, monkeypatch, capfd):
    monkeypatch.setenv("ZHIRAF_TEST_NO_DIALOG", "1")
    held = app.acquire_single_instance()
    try:
        assert app.main(["zhiraf"]) == 0
    finally:
        held.unlock()
    assert "Жираф.Корректор уже открыт" in capfd.readouterr().err


def test_close_is_bounded_when_a_retiring_open_hangs(qtbot, full_models_dir, tmp_path, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(loader, "open_document", lambda path: release.wait(10))
    w = MainWindow(full_models_dir, factories="fakes:make_factories")
    qtbot.addWidget(w)
    w.show()
    w.open_path(make_docx(tmp_path / "a.docx", P(R("Текст."))))
    qtbot.wait(300)     # the worker is inside open_document
    started = time.monotonic()
    w.close()
    assert time.monotonic() - started < 3.6
    assert w.hard_exit is True
    release.set()   # let the thread end so that the test process can exit cleanly
    assert all(t.wait(5000) for t in w._retiring)


def test_excepthook_never_raises(monkeypatch):
    monkeypatch.setattr(app, "log_error", lambda exc: 1 / 0)
    monkeypatch.setattr(app, "_tell", lambda *a: 1 / 0)
    app._install_excepthook()
    try:
        sys.excepthook(ValueError, ValueError("x"), None)   # must not raise
    finally:
        sys.excepthook = sys.__excepthook__
