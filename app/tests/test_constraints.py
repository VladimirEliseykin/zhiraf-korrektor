import os
import subprocess
import sys

import zhiraf

if zhiraf.ROOT not in sys.path:   # build/ lives at the repo root, outside app/
    sys.path.insert(0, zhiraf.ROOT)

from build.check_dist import FORBIDDEN, FORBIDDEN_QT_NAMES as FORBIDDEN_QT, imported_names  # noqa: E402  (one rule, shared with the folder check)

SOURCE_DIRS = [os.path.join(zhiraf.ROOT, "app", "zhiraf"), os.path.join(zhiraf.ENGINE_DIR, "spellcheck")]


def python_files():
    for top in SOURCE_DIRS:
        for folder, _, names in os.walk(top):
            for name in names:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)


def test_sources_import_no_network_modules():
    bad = []
    for path in python_files():
        for name in imported_names(path):
            if name.split(".")[0] in FORBIDDEN or any(q in name for q in FORBIDDEN_QT):
                bad.append((os.path.relpath(path, zhiraf.ROOT), name))
    assert bad == []


def test_forbidden_import_is_caught(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import socket\nfrom urllib import request\n", encoding="utf-8")
    names = set(imported_names(str(sample)))
    assert "socket" in names and "urllib.request" in names


def test_forbidden_qt_names_are_caught(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("from PySide2.QtNetwork import QTcpSocket\nfrom PySide2 import QtWebEngineWidgets\n"
                      "from PySide2.QtCore import QLocalServer\n", encoding="utf-8")
    names = set(imported_names(str(sample)))
    assert all(any(q in n for q in FORBIDDEN_QT) for n in ("PySide2.QtNetwork", "PySide2.QtCore.QLocalServer"))
    assert {"PySide2.QtNetwork", "PySide2.QtNetwork.QTcpSocket", "PySide2.QtWebEngineWidgets",
            "PySide2.QtCore.QLocalServer"} <= names


def test_sources_run_on_python37():
    cmd = [sys.executable, "-c", "import sys; from vermin.main import main; sys.exit(main())",
           "--target=3.7-", "--violations", "--no-tips"] + SOURCE_DIRS
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 0, result.stdout
