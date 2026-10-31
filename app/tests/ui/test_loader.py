import pytest
from PySide2.QtCore import QCoreApplication, QElapsedTimer

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
    assert not task.is_running()


def test_txt_cp1251(tmp_path, qapp):
    path = tmp_path / "t.txt"
    path.write_bytes("Привет, мир".encode("cp1251"))
    got = run(OpenTask(str(path)), qapp)
    assert got["opened"].paragraphs[0].text == "Привет, мир"
