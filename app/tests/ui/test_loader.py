import pytest
import time

from PySide2.QtCore import QCoreApplication, QElapsedTimer
from PySide2.QtWidgets import QWidget

from docfactory import P, R, make_docx
from zhiraf.ui.loader import OpenTask


def run(task, qapp, timeout=10000):
    got = {}
    task.opened.connect(lambda d: got.setdefault("opened", d))
    task.failed.connect(lambda m: got.setdefault("failed", m))
    task.start()
    timer = QElapsedTimer()
    timer.start()
    while not got and timer.elapsed() < timeout:
        QCoreApplication.processEvents()
        qapp.thread().msleep(5)
    task.close()
    return got


def test_opens_docx(tmp_path, qapp):
    path = make_docx(tmp_path / "a.docx", P(R("Привет")))
    got = run(OpenTask(path), qapp)
    assert got["opened"].paragraphs[0].text == "Привет"
    assert "failed" not in got


def test_missing_file(tmp_path, qapp):
    got = run(OpenTask(str(tmp_path / "нет.docx")), qapp)
    assert "Файл не найден" in got["failed"]


def test_corrupt_file(tmp_path, qapp):
    path = tmp_path / "bad.docx"
    path.write_bytes(b"not a zip at all")
    got = run(OpenTask(str(path)), qapp)
    assert "файл повреждён" in got["failed"] and "bad.docx" in got["failed"]
    assert "Traceback" not in got["failed"]


def test_unexpected_exception_has_no_details(tmp_path, qapp, monkeypatch):
    import zhiraf.ui.loader as loader

    def boom(path):
        raise ValueError("secret detail")
    monkeypatch.setattr(loader, "open_document", boom)
    got = run(OpenTask(str(tmp_path / "x.docx")), qapp)
    assert got["failed"] == "Не удалось открыть «x.docx»: файл повреждён."


def test_cancel_discards_result(tmp_path, qapp):
    path = make_docx(tmp_path / "a.docx", P(R("Привет")))
    task = OpenTask(path)
    fired = []
    task.opened.connect(fired.append)
    task.failed.connect(fired.append)
    task.start()
    task.cancel()
    for _ in range(20):
        QCoreApplication.processEvents()
        qapp.thread().msleep(5)
    assert fired == []
    task.close()
    assert not task.is_running()


def test_txt_cp1251(tmp_path, qapp):
    path = tmp_path / "t.txt"
    path.write_bytes("Привет, мир".encode("cp1251"))
    got = run(OpenTask(str(path)), qapp)
    assert got["opened"].paragraphs[0].text == "Привет, мир"


def slow_open(monkeypatch, seconds=1.0):
    import zhiraf.ui.loader as loader
    monkeypatch.setattr(loader, "open_document", lambda path: time.sleep(seconds))


def test_cancel_does_not_block(tmp_path, qapp, monkeypatch):
    slow_open(monkeypatch)
    task = OpenTask(str(tmp_path / "a.docx"))
    task.start()
    t0 = time.time()
    task.cancel()
    assert time.time() - t0 < 0.1
    task.close()
    assert not task.is_running()


def test_thread_ends_by_itself_after_result(tmp_path, qapp):
    task = OpenTask(make_docx(tmp_path / "a.docx", P(R("x"))))
    got = {}
    task.opened.connect(lambda d: got.setdefault("o", d))
    task.start()
    thread = task._thread
    timer = QElapsedTimer()
    timer.start()
    while thread.isRunning() and timer.elapsed() < 5000:
        QCoreApplication.processEvents()
        qapp.thread().msleep(5)
    assert not thread.isRunning()
    task.close()


def test_parent_deleted_during_open(tmp_path, qapp, monkeypatch, capfd):
    slow_open(monkeypatch, 0.5)
    parent = QWidget()
    task = OpenTask(str(tmp_path / "a.docx"), parent)
    task.start()
    parent.deleteLater()
    for _ in range(5):
        QCoreApplication.processEvents()
        qapp.thread().msleep(10)
    time.sleep(0.7)
    QCoreApplication.processEvents()
    err = capfd.readouterr()
    assert "Destroyed while thread is still running" not in err.err + err.out


def test_cancelled_open_removes_the_temp_copy(tmp_path, qapp, monkeypatch):
    import zhiraf.ui.loader as loader
    tmpdir = tmp_path / "converted"
    tmpdir.mkdir()
    (tmpdir / "x.docx").write_bytes(b"secret")

    class FakeDoc:
        source = {"tmpdir": str(tmpdir)}

    def slow(path):
        time.sleep(0.3)
        return FakeDoc()

    monkeypatch.setattr(loader, "open_document", slow)
    task = OpenTask(str(tmp_path / "a.doc"))
    fired = []
    task.opened.connect(fired.append)
    task.start()
    task.cancel()
    timer = QElapsedTimer()
    timer.start()
    while tmpdir.exists() and timer.elapsed() < 5000:
        QCoreApplication.processEvents()
        qapp.thread().msleep(5)
    task.close()
    assert fired == [] and not tmpdir.exists()
