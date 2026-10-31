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
                PYSIDE + "/QtNetwork.pyd", PYSIDE + "/QtWebEngineCore.pyd",
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


# --- the real PySide2 5.15.2.1 wheel: names and the Qt/pyside DLLs each binary imports (see fixtures/) ---

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
KEEP_QT_DLLS = {"Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Svg.dll", "Qt5PrintSupport.dll",
                # pyside2.abi3.dll (loaded by every PySide2 module) imports Qt5Qml.dll, which imports Qt5Network.dll:
                # without them `import PySide2.QtCore` fails on Windows. Python gets no QtQml/QtNetwork module.
                "Qt5Qml.dll", "Qt5Network.dll"}
KEEP_PLUGIN_DIRS = {"platforms", "imageformats", "iconengines", "printsupport", "platformthemes", "styles"}


def wheel_names():
    with open(os.path.join(FIXTURES, "pyside2_5.15.2.1_files.txt"), encoding="utf-8") as f:
        return [n.strip() for n in f if n.strip()]


def wheel_imports():
    out = {}
    with open(os.path.join(FIXTURES, "pyside2_5.15.2.1_imports.tsv"), encoding="utf-8") as f:
        for line in f:
            name, _, deps = line.rstrip("\n").partition("\t")
            out[name] = deps.split()
    return out


@pytest.fixture
def real_wheel(clean):
    for name in wheel_names():
        if not name.endswith("/"):
            put(clean, os.path.join("python", "Lib", "site-packages", name.replace("/", os.sep)))
    return clean


def pyside_files(dist):
    base = os.path.join(str(dist), PYSIDE)
    return {os.path.relpath(os.path.join(r, n), base).replace(os.sep, "/")
            for r, _, names in os.walk(base) for n in names}


def test_check_flags_the_qt_dlls_of_removed_modules(real_wheel):
    found = check_dist.check(str(real_wheel))
    for dll in ("Qt5WebSockets.dll", "Qt5WebChannel.dll", "Qt5NetworkAuth.dll", "Qt5RemoteObjects.dll",
                "Qt5Bluetooth.dll", "Qt5Nfc.dll", "Qt5Location.dll", "Qt5Positioning.dll", "Qt5Sensors.dll",
                "Qt5SerialPort.dll", "Qt5SerialBus.dll", "Qt5Scxml.dll", "Qt5Charts.dll",
                "Qt5DataVisualization.dll", "Qt5WebView.dll", "Qt5Pdf.dll", "Qt5Designer.dll"):
        assert any(v.endswith(dll) for v in found), dll


def test_real_wheel_keeps_only_the_qt_dlls_the_program_needs(real_wheel):
    prune_mod.prune(str(real_wheel))
    left = pyside_files(real_wheel)
    assert {n for n in left if "/" not in n and n.startswith("Qt5") and n.endswith(".dll")} == KEEP_QT_DLLS
    assert {n.split("/")[1] for n in left if n.startswith("plugins/")} <= KEEP_PLUGIN_DIRS
    assert check_dist.check(str(real_wheel)) == []


def test_real_wheel_keeps_what_must_stay(real_wheel):
    prune_mod.prune(str(real_wheel))
    left = pyside_files(real_wheel)
    for n in ("Qt5Core.dll", "Qt5Gui.dll", "Qt5Widgets.dll", "Qt5Svg.dll", "Qt5PrintSupport.dll",
              "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtSvg.pyd", "QtPrintSupport.pyd", "pyside2.abi3.dll",
              "plugins/platforms/qwindows.dll", "plugins/imageformats/qsvg.dll", "plugins/imageformats/qjpeg.dll",
              "plugins/iconengines/qsvgicon.dll", "plugins/printsupport/windowsprintersupport.dll",
              "plugins/styles/qwindowsvistastyle.dll", "translations/qtbase_ru.qm"):
        assert n in left, n
    assert any(n.startswith("plugins/platformthemes/") for n in left)


def test_every_remaining_binary_finds_its_qt_dlls(real_wheel):
    """The import test: each .pyd and .dll left must have all the Qt/PySide DLLs it links against."""
    prune_mod.prune(str(real_wheel))
    left = pyside_files(real_wheel)
    imports = wheel_imports()
    missing = []
    for name in sorted(left):
        if not name.endswith((".pyd", ".dll")) or name.startswith("plugins/platformthemes/"):
            continue   # platformthemes holds a desktop-portal theme that needs Qt5DBus; Qt skips a plugin that cannot load
        for dep in imports["PySide2/" + name]:
            if dep not in left and not dep.startswith("shiboken2"):   # shiboken2 comes from its own wheel
                missing.append((name, dep))
    assert missing == []


def test_zip_rebuild_failure_leaves_no_temporary_file(dirty, monkeypatch):
    def broken(self, zinfo, data=None, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile, "writestr", broken)
    with pytest.raises(OSError):
        prune_mod.prune(str(dirty))
    assert not [n for n in os.listdir(os.path.join(str(dirty), PY)) if n.endswith(".tmp")]
