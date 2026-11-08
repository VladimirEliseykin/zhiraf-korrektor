"""Fail the build when the Windows 7 folder holds a network module or lacks something it needs (host only).

Usage: python -m build.check_dist <dist> [<source models dir>]   (prints the violations, exits with 1 when there are any)
"""
import ast
import os
import sys

from build import prune as prune_mod
from build.layout import MODELS_PLACEHOLDER, REQUIRED_DLLS

# Source files must not import these (the same rule as app/tests/test_constraints.py, which imports it from here).
FORBIDDEN = {"socket", "ssl", "urllib", "urllib2", "http", "httplib", "ftplib", "smtplib", "poplib", "imaplib",
             "telnetlib", "xmlrpc", "requests", "asyncio", "websocket", "websockets", "selectors"}
FORBIDDEN_QT_NAMES = ("QtNetwork", "QtWebEngine", "QtQml", "QtMultimedia", "QLocalServer", "QTcpSocket")

SOCKET_NOTE = ("allowed: socket.py, _socket.pyd and select.pyd stay in the folder because multiprocessing needs "
               "them; the program does not use socket")

REQUIRED_FILES = (
    os.path.join("python", "pythonw.exe"),
    "Жираф.Корректор.exe",
    "ИНСТРУКЦИЯ.txt",
    os.path.join("engine", "art", "start.jpg"),
    os.path.join("app", "zhiraf", "ui", "art", "logo.png"),
    # hard to find when missing: without qt.conf Qt loses its plugins under a Cyrillic or spaced path (the window
    # does not open), without the ._pth the shipped Python does not see the program and its libraries
    os.path.join("python", "qt.conf"),
    os.path.join("python", "python37._pth"),
)


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


def is_network_import(name):
    return name.split(".")[0] in FORBIDDEN or any(q in name for q in FORBIDDEN_QT_NAMES)


def _source_violations(dist):
    for top in ("app", "engine"):
        for folder, _, names in os.walk(os.path.join(dist, top)):
            for name in sorted(names):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                try:
                    names = {n for n in imported_names(path) if is_network_import(n)}
                    # 'from urllib import request' yields urllib and urllib.request: report the longer one
                    bad = sorted(n for n in names if not any(o.startswith(n + ".") for o in names))
                except SyntaxError as e:
                    yield "unreadable source %s: %s" % (os.path.relpath(path, dist), e)
                    continue
                for n in bad:
                    yield "network import in %s: %s" % (os.path.relpath(path, dist), n)


def _model_violations(dist, models):
    """Every model folder of the source models dir must be in the folder with all its ONNX files non-empty.

    A missing or half-copied one degrades the quality silently (the checker skips what it cannot load).
    """
    for name in sorted(os.listdir(models)):
        source = os.path.join(models, name)
        if not os.path.isdir(source):
            continue
        for part in sorted(os.listdir(source)):
            if not (part.endswith(".onnx") or part.endswith(".onnx.data")):
                continue
            path = os.path.join(dist, "models", name, part)
            if not os.path.isfile(path):
                yield "missing: %s" % os.path.join("models", name, part)
            elif os.path.getsize(path) == 0:
                yield "empty model file: %s" % os.path.join("models", name, part)


def check(dist, models=None, require_models=True):
    """Violations found in the folder; an empty list means it is clean.

    `models` is the source models dir the build was given: its folders are the list of models the folder must hold.
    `require_models=False` is the build without models: vocab.tsv and the model folders are not needed, but the
    placeholder note must be there (add_models removes it).
    """
    found = []
    zip_path = os.path.join(dist, prune_mod.PYTHON_DIR, prune_mod.ZIP_NAME)
    if os.path.isfile(zip_path):
        found += ["forbidden module in python37.zip: %s" % n for n in prune_mod.forbidden_zip_members(zip_path)]
    found += ["forbidden file: %s" % p for p in prune_mod.forbidden_binaries(dist) + prune_mod.forbidden_qt_paths(dist)]
    found += list(_source_violations(dist))
    for rel in [os.path.join("python", n) for n in REQUIRED_DLLS] + list(REQUIRED_FILES):
        if not os.path.isfile(os.path.join(dist, rel)):
            found.append("missing: %s" % rel)
    if require_models:
        if not os.path.isfile(os.path.join(dist, "models", "vocab.tsv")):
            found.append("missing: %s" % os.path.join("models", "vocab.tsv"))
    elif not os.path.isfile(os.path.join(dist, "models", MODELS_PLACEHOLDER)):
        found.append("missing: %s" % os.path.join("models", MODELS_PLACEHOLDER))
    if require_models and models is not None:
        found += list(_model_violations(dist, models))
    return found


def main(argv):
    if len(argv) not in (1, 2):
        print("usage: python -m build.check_dist <dist> [<source models dir>]")
        return 2
    violations = check(argv[0], argv[1] if len(argv) == 2 else None)
    print(SOCKET_NOTE)
    for v in violations:
        print("VIOLATION: " + v)
    if violations:
        print("%d violation(s)" % len(violations))
        return 1
    print("the folder is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
