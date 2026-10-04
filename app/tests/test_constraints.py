import ast
import os
import subprocess
import sys

import zhiraf

FORBIDDEN = {"socket", "ssl", "urllib", "urllib2", "http", "httplib", "ftplib", "smtplib", "poplib", "imaplib",
             "telnetlib", "xmlrpc", "requests", "asyncio", "websocket", "websockets", "selectors"}
SOURCE_DIRS = [os.path.join(zhiraf.ROOT, "app", "zhiraf"), os.path.join(zhiraf.ENGINE_DIR, "spellcheck")]


def python_files():
    for top in SOURCE_DIRS:
        for folder, _, names in os.walk(top):
            for name in names:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)


def imported_names(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield node.module + "." + alias.name


def test_sources_import_no_network_modules():
    bad = []
    for path in python_files():
        for name in imported_names(path):
            if name.split(".")[0] in FORBIDDEN or "QtNetwork" in name:
                bad.append((os.path.relpath(path, zhiraf.ROOT), name))
    assert bad == []


def test_forbidden_import_is_caught(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import socket\nfrom urllib import request\n", encoding="utf-8")
    names = set(imported_names(str(sample)))
    assert "socket" in names and "urllib.request" in names


def test_sources_run_on_python37():
    cmd = [sys.executable, "-c", "import sys; from vermin.main import main; sys.exit(main())",
           "--target=3.7-", "--violations", "--no-tips"] + SOURCE_DIRS
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 0, result.stdout
