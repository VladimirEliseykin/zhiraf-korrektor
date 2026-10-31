import os
import subprocess
import sys
import zipfile

import pytest

from build import check_dist, prune as prune_mod
from build.layout import REQUIRED_DLLS

PY = os.path.join("python")
PYSIDE = os.path.join("python", "Lib", "site-packages", "PySide2")


def put(dist, rel, data=b"x"):
    path = os.path.join(str(dist), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def make_zip(dist, names):
    path = os.path.join(str(dist), PY, "python37.zip")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, "# %s\n" % n)
    return path


def zip_names(dist):
    with zipfile.ZipFile(os.path.join(str(dist), PY, "python37.zip")) as z:
        return sorted(z.namelist())


@pytest.fixture
def clean(tmp_path):
    """A folder with everything check() requires and nothing it forbids."""
    dist = tmp_path / "dist"
    for n in REQUIRED_DLLS:
        put(dist, os.path.join(PY, n))
    for rel in ("python/pythonw.exe", "Жираф.Корректор.exe", "models/vocab.tsv", "engine/art/start.jpg",
                "app/zhiraf/ui/art/logo.png", "python/socket.py", "python/_socket.pyd", "python/select.pyd"):
        put(dist, rel)
    put(dist, "app/zhiraf/ok.py", b"import os\n")
    make_zip(dist, ["json/__init__.py", "urllib/parse.py"])
    return dist


@pytest.fixture
def dirty(tmp_path):
    dist = tmp_path / "dist"
    for n in REQUIRED_DLLS:
        put(dist, os.path.join(PY, n))
    for rel in ("python/pythonw.exe", "Жираф.Корректор.exe", "models/vocab.tsv", "engine/art/start.jpg",
                "app/zhiraf/ui/art/logo.png", "python/socket.py", "python/_socket.pyd", "python/select.pyd",
                "python/_ssl.pyd", "python/_hashlib.pyd", "python/libssl-1_1.dll", "python/libcrypto-1_1.dll",
                "python/_asyncio.pyd", "python/_overlapped.pyd", "python/_msi.pyd", "python/winsound.pyd",
                PYSIDE + "/QtNetwork.pyd", PYSIDE + "/Qt5Network.dll", PYSIDE + "/QtWebEngineCore.pyd",
                PYSIDE + "/Qt5WebEngineCore.dll", PYSIDE + "/QtQml.pyd", PYSIDE + "/Qt5Quick.dll",
                PYSIDE + "/Qt53DCore.dll", PYSIDE + "/QtMultimedia.pyd", PYSIDE + "/QtCharts.pyd",
                PYSIDE + "/QtWebEngineProcess.exe", PYSIDE + "/designer.exe", PYSIDE + "/lupdate.exe",
                PYSIDE + "/plugins/bearer/x.dll", PYSIDE + "/plugins/geoservices/x.dll",
                PYSIDE + "/plugins/platforms/qwindows.dll", PYSIDE + "/qml/Qt/x.qml", PYSIDE + "/examples/a.py",
                PYSIDE + "/include/a.h", PYSIDE + "/QtCore.pyd", PYSIDE + "/Qt5Core.dll",
                PYSIDE + "/translations/qtbase_ru.qm", PYSIDE + "/translations/qtbase_de.qm"):
        put(dist, rel)
    make_zip(dist, ["ssl.py", "http/client.py", "urllib/request.py", "urllib/parse.py", "json/__init__.py",
                    "xmlrpc/client.py", "asyncio/base_events.py", "socketserver.py", "webbrowser.py", "cgi.py"])
    return dist


def test_prune_removes_network_modules_and_keeps_the_rest(dirty):
    removed = prune_mod.prune(str(dirty))
    assert zip_names(dirty) == ["json/__init__.py", "urllib/parse.py"]
    for rel in ("python/_ssl.pyd", "python/_hashlib.pyd", "python/libssl-1_1.dll", "python/libcrypto-1_1.dll",
                "python/_asyncio.pyd", "python/_overlapped.pyd", "python/_msi.pyd", "python/winsound.pyd",
                PYSIDE + "/QtNetwork.pyd", PYSIDE + "/Qt5Network.dll", PYSIDE + "/QtWebEngineCore.pyd",
                PYSIDE + "/QtQml.pyd", PYSIDE + "/Qt5Quick.dll", PYSIDE + "/Qt53DCore.dll",
                PYSIDE + "/QtMultimedia.pyd", PYSIDE + "/QtCharts.pyd", PYSIDE + "/QtWebEngineProcess.exe",
                PYSIDE + "/designer.exe", PYSIDE + "/lupdate.exe", PYSIDE + "/plugins/bearer",
                PYSIDE + "/plugins/geoservices", PYSIDE + "/qml", PYSIDE + "/examples", PYSIDE + "/include",
                PYSIDE + "/translations/qtbase_de.qm"):
        assert not os.path.exists(os.path.join(str(dirty), rel)), rel
    for rel in ("python/socket.py", "python/_socket.pyd", "python/select.pyd", PYSIDE + "/QtCore.pyd",
                PYSIDE + "/Qt5Core.dll", PYSIDE + "/plugins/platforms/qwindows.dll",
                PYSIDE + "/translations/qtbase_ru.qm", "python/pythonw.exe"):
        assert os.path.exists(os.path.join(str(dirty), rel)), rel
    assert "python/_ssl.pyd" in [r.replace(os.sep, "/") for r in removed]
    assert any(r.replace(os.sep, "/").endswith("python37.zip/ssl.py") for r in removed)
    assert all(not os.path.isabs(r) for r in removed)
    assert check_dist.check(str(dirty)) == []


def test_prune_leaves_no_temporary_zip(dirty):
    prune_mod.prune(str(dirty))
    assert sorted(os.listdir(os.path.join(str(dirty), PY))).count("python37.zip") == 1
    assert not [n for n in os.listdir(os.path.join(str(dirty), PY)) if n.endswith(".tmp")]


def test_prune_is_idempotent(dirty):
    prune_mod.prune(str(dirty))
    assert prune_mod.prune(str(dirty)) == []


def test_check_is_clean_on_a_clean_folder(clean):
    assert check_dist.check(str(clean)) == []


def test_check_names_each_violation(clean):
    put(clean, PYSIDE + "/QtNetwork.pyd")
    put(clean, "app/zhiraf/x.py", b"import socket\n")
    found = check_dist.check(str(clean))
    assert len(found) == 2, found
    assert any("QtNetwork.pyd" in v for v in found) and any("socket" in v for v in found)


def test_check_sees_names_inside_the_zip(clean):
    make_zip(clean, ["json/__init__.py", "http/client.py"])
    found = check_dist.check(str(clean))
    assert len(found) == 1 and "http/client.py" in found[0]


def test_check_reports_missing_required_files(clean):
    os.remove(os.path.join(str(clean), "models", "vocab.tsv"))
    os.remove(os.path.join(str(clean), PY, "msvcp140.dll"))
    found = check_dist.check(str(clean))
    assert len(found) == 2 and any("vocab.tsv" in v for v in found) and any("msvcp140.dll" in v for v in found)


def test_check_sees_network_imports_of_every_form(clean):
    put(clean, "engine/spellcheck/a.py", b"from urllib import request\n")
    put(clean, "app/zhiraf/b.py", b"from PySide2 import QtNetwork\n")
    put(clean, "app/zhiraf/c.py", b"import asyncio.tasks\n")
    assert len(check_dist.check(str(clean))) == 3


def test_check_allows_socket_files_and_says_so(clean, capsys):
    assert check_dist.check(str(clean)) == []
    assert check_dist.main([str(clean)]) == 0
    out = capsys.readouterr().out
    assert "socket" in out and "multiprocessing" in out


def test_module_exits_with_1_on_a_dirty_folder(dirty):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    result = subprocess.run([sys.executable, "-m", "build.check_dist", str(dirty)], cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 1
    assert "_ssl.pyd" in result.stdout and "QtNetwork.pyd" in result.stdout


def test_module_exits_with_0_on_a_clean_folder(clean):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    result = subprocess.run([sys.executable, "-m", "build.check_dist", str(clean)], cwd=root,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 0, result.stdout
