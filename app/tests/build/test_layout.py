import io
import os
import tarfile
import zipfile

import pytest

from build import layout
from build.layout import REQUIRED_DLLS, lay_out


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return str(path)


@pytest.fixture
def world(tmp_path):
    files = {
        "python-embed": _zip(tmp_path / "embed.zip", {
            "python.exe": b"py", "pythonw.exe": b"pyw", "python37.dll": b"dll",
            "python37.zip": b"stdlib", "python37._pth": b"python37.zip\r\n.\r\nimport site\r\n",
            "vcruntime140.dll": b"old-vc"}),
        "wheel:shiboken2": _zip(tmp_path / "shiboken2.whl", {
            "shiboken2/msvcp140.dll": b"msvcp", "shiboken2/vcruntime140.dll": b"new-vc",
            "shiboken2/vcruntime140_1.dll": b"vc1", "shiboken2/shiboken2.abi3.dll": b"sb",
            "shiboken2-5.15.dist-info/METADATA": b"m"}),
        "wheel:tool": _zip(tmp_path / "tool.whl", {
            "tool/__init__.py": b"", "tool-1.data/scripts/tool.exe": b"x",
            "tool-1.data/purelib/extra.py": b"e", "tool-1.dist-info/METADATA": b"m"}),
    }
    tar_path = tmp_path / "ucrt.tar.bz2"
    with tarfile.open(str(tar_path), "w:bz2") as t:
        for name in ("Library/bin/ucrtbase.dll", "Library/bin/api-ms-win-crt-runtime-l1-1-0.dll",
                     "ucrtbase.dll", "info/index.json"):
            data = b"U" + name.encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    files["ucrt"] = str(tar_path)
    files["toolchain"] = str(tmp_path / "not-used.tar.xz")

    repo = tmp_path / "repo"
    (repo / "app" / "zhiraf" / "__pycache__").mkdir(parents=True)
    (repo / "app" / "zhiraf" / "tests").mkdir()
    (repo / "app" / "zhiraf" / "__init__.py").write_text("x")
    (repo / "app" / "zhiraf" / "tests" / "t.py").write_text("t")
    (repo / "app" / "zhiraf" / "__pycache__" / "a.pyc").write_bytes(b"c")
    (repo / "app" / "tests").mkdir()
    (repo / "app" / "tests" / "x.py").write_text("t")
    (repo / "engine" / "spellcheck" / "__pycache__").mkdir(parents=True)
    (repo / "engine" / "spellcheck" / "tests").mkdir()
    (repo / "engine" / "spellcheck" / "core.py").write_text("c")
    (repo / "engine" / "spellcheck" / "tests" / "t.py").write_text("t")
    (repo / "engine" / "spellcheck" / "__pycache__" / "a.pyc").write_bytes(b"c")
    (repo / "engine" / "art").mkdir()
    (repo / "engine" / "art" / "start.jpg").write_bytes(b"jpg")
    (repo / "engine" / "art" / "other.png").write_bytes(b"png")
    models = tmp_path / "models"
    (models / "sage").mkdir(parents=True)
    (models / "sage" / "model.onnx").write_bytes(b"m" * 10)
    (models / "vocab.tsv").write_text("a\n")
    return files, str(repo), str(models), str(tmp_path / "dist")


def test_pth_is_four_crlf_lines(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    with open(os.path.join(dist, "python", "python37._pth"), "rb") as f:
        assert f.read() == b"python37.zip\r\n.\r\nLib\\site-packages\r\n..\\app\r\n"


def test_qt_conf_next_to_python_exe(world):
    # Qt 5.15 finds no plugins when the folder path has Cyrillic letters (Windows 7 VM: an ASCII path with a space
    # works, a Cyrillic path without a space fails):
    # a qt.conf next to python.exe, the application directory, points it at the PySide2 folder.
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    with open(os.path.join(dist, "python", "qt.conf"), "rb") as f:
        assert f.read() == b"[Paths]\r\nPrefix = Lib/site-packages/PySide2\r\n"


def test_embed_and_wheels(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    py = os.path.join(dist, "python")
    for n in ("python.exe", "pythonw.exe", "python37.dll", "python37.zip"):
        assert os.path.isfile(os.path.join(py, n))
    sp = os.path.join(py, "Lib", "site-packages")
    assert os.path.isfile(os.path.join(sp, "tool", "__init__.py"))
    assert os.path.isfile(os.path.join(sp, "shiboken2", "msvcp140.dll"))
    assert os.path.isfile(os.path.join(sp, "tool-1.data", "purelib", "extra.py"))
    assert not os.path.exists(os.path.join(sp, "tool-1.data", "scripts"))


def test_runtime_dlls_next_to_python_exe(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    py = os.path.join(dist, "python")
    for n in REQUIRED_DLLS:
        assert os.path.isfile(os.path.join(py, n)), n
    # VC DLLs come from shiboken2 (newer than the embed's), UCRT from Library/bin
    with open(os.path.join(py, "vcruntime140.dll"), "rb") as f:
        assert f.read() == b"new-vc"
    with open(os.path.join(py, "ucrtbase.dll"), "rb") as f:
        assert f.read() == b"ULibrary/bin/ucrtbase.dll"
    assert not os.path.exists(os.path.join(py, "info"))


def test_missing_required_dll_is_an_error(world, tmp_path):
    files, repo, models, dist = world
    files["wheel:shiboken2"] = _zip(tmp_path / "bad.whl", {"shiboken2/x.dll": b"x"})
    with pytest.raises(FileNotFoundError):
        lay_out(dist, files, repo, models)


def test_app_and_engine_copied_clean(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    assert os.path.isfile(os.path.join(dist, "app", "zhiraf", "__init__.py"))
    assert os.path.isfile(os.path.join(dist, "engine", "spellcheck", "core.py"))
    assert os.path.isfile(os.path.join(dist, "engine", "art", "start.jpg"))
    assert not os.path.exists(os.path.join(dist, "engine", "art", "other.png"))
    assert not os.path.exists(os.path.join(dist, "app", "tests"))
    for root, dirs, _ in os.walk(dist):
        assert "__pycache__" not in dirs
        assert "tests" not in dirs


def test_models_hard_linked(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    a = os.stat(os.path.join(models, "sage", "model.onnx"))
    b = os.stat(os.path.join(dist, "models", "sage", "model.onnx"))
    assert a.st_ino == b.st_ino
    assert os.path.isfile(os.path.join(dist, "models", "vocab.tsv"))


def test_models_copied_when_not_linked(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models, link_models=False)
    a = os.stat(os.path.join(models, "sage", "model.onnx"))
    b = os.stat(os.path.join(dist, "models", "sage", "model.onnx"))
    assert a.st_ino != b.st_ino
    assert b.st_size == a.st_size


def test_non_empty_dist_refused(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    with pytest.raises(FileExistsError):
        lay_out(dist, files, repo, models)


def test_readme_utf8_bom(world):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    with open(os.path.join(dist, "ЧИТАЙ-МЕНЯ.txt"), "rb") as f:
        raw = f.read()
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines()
    assert 3 <= len([l for l in lines if l.strip()]) <= 5
    assert b"\r\n" in raw
    text = raw.decode("utf-8-sig")
    for needle in ("%APPDATA%", "журнал.txt", "Жираф.Корректор.exe"):
        assert needle in text


def test_model_copy_fallback_is_counted_and_reported(world, monkeypatch, capsys):
    files, repo, models, dist = world

    def no_link(src, dst, *a, **k):
        raise OSError("cross-device")
    monkeypatch.setattr(os, "link", no_link)
    lay_out(dist, files, repo, models)
    assert os.path.isfile(os.path.join(dist, "models", "sage", "model.onnx"))
    assert os.path.isfile(os.path.join(dist, "models", "vocab.tsv"))
    assert "скопировано 2 файлов" in capsys.readouterr().out
    n = layout._put_models(models, os.path.join(dist, "models2"), True)
    assert n[0] == 2


def test_no_fallback_line_when_links_work(world, capsys):
    files, repo, models, dist = world
    lay_out(dist, files, repo, models)
    assert "скопировано" not in capsys.readouterr().out


def test_dist_dot(world, monkeypatch, tmp_path):
    files, repo, models, _ = world
    cwd = tmp_path / "empty"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    lay_out(".", files, repo, models)
    assert os.path.isfile(cwd / "python" / "python.exe")
