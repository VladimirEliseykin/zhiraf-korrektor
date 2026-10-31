"""Strip network modules out of the Windows 7 folder (host only)."""
import fnmatch
import os
import shutil
import zipfile

# Removed from python37.zip and from the .pyd/.dll files next to python.exe. Built-in _sha*/_md5 stay in python37.dll.
# socket.py, _socket.pyd and select.pyd are NOT here: multiprocessing.connection imports socket at load time,
# although the check talks over pipes on Windows; the program itself never imports socket (check_dist verifies it).
# urllib.parse stays too: pathlib.as_uri and lxml use its string parsing, which has no network in it.
FORBIDDEN_STDLIB = (
    "ssl", "_ssl", "http", "urllib.request", "urllib.response", "urllib.error", "urllib.robotparser",
    "ftplib", "smtplib", "smtpd", "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc", "socketserver",
    "asyncio", "_asyncio", "_overlapped",
    "wsgiref", "webbrowser", "mailbox", "cgi", "cgitb",
    "_msi", "winsound",
    "libssl-1_1.dll", "libcrypto-1_1.dll", "_hashlib",
)

# Names (glob patterns) inside PySide2/. An entry with a slash is a path under PySide2/; a trailing slash is a folder.
FORBIDDEN_QT = (
    "QtNetwork*", "Qt5Network.dll",
    "QtWebEngine*", "Qt5WebEngine*", "QtWebChannel*", "QtWebSockets*",
    "QtQml*", "QtQuick*", "Qt5Qml*", "Qt5Quick*", "Qt3D*", "Qt53D*",
    "QtMultimedia*", "Qt5Multimedia*", "QtPositioning*", "QtLocation*", "QtBluetooth*", "QtNfc*",
    "QtRemoteObjects*", "QtSensors*", "QtSerialPort*", "QtScxml*", "QtCharts*", "QtDataVisualization*",
    "plugins/bearer", "plugins/geoservices", "plugins/position", "plugins/sensors", "plugins/qmltooling",
    "plugins/webview",
    "qml/", "translations/", "examples/", "include/",
    "*.exe",
)
KEEP_TRANSLATIONS = ("qtbase_ru.qm",)

PYTHON_DIR = "python"
ZIP_NAME = "python37.zip"
PYSIDE_DIR = os.path.join("python", "Lib", "site-packages", "PySide2")
_BINARY_EXT = (".pyd", ".dll")


def forbidden_module(name):
    """True when a dotted module name is, or lies inside, a forbidden one."""
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN_STDLIB if not f.endswith(".dll"))


def zip_member_module(member):
    """'http/client.py' -> 'http.client'; 'asyncio/__init__.pyc' -> 'asyncio'; None for non-code members."""
    base, ext = os.path.splitext(member)
    if ext not in (".py", ".pyc", ".pyo"):
        return None
    parts = base.split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts and parts[0] else None


def forbidden_zip_members(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        return [n for n in z.namelist() if not n.endswith("/") and _member_forbidden(n)]


def _member_forbidden(member):
    module = zip_member_module(member)
    return module is not None and forbidden_module(module)


def forbidden_binaries(dist):
    """Relative paths of forbidden .pyd/.dll files that sit next to python.exe."""
    folder = os.path.join(dist, PYTHON_DIR)
    found = []
    if not os.path.isdir(folder):
        return found
    for name in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in _BINARY_EXT:
            continue
        if name.lower() in FORBIDDEN_STDLIB or stem in FORBIDDEN_STDLIB:
            found.append(os.path.join(PYTHON_DIR, name))
    return found


def forbidden_qt_paths(dist):
    """Relative paths (files or whole folders) under PySide2/ that must not be shipped."""
    base = os.path.join(dist, PYSIDE_DIR)
    if not os.path.isdir(base):
        return []
    found = []
    names = sorted(os.listdir(base))
    for entry in FORBIDDEN_QT:
        if "/" in entry.rstrip("/"):                      # a path: plugins/bearer
            if os.path.exists(os.path.join(base, entry)):
                found.append(os.path.join(PYSIDE_DIR, entry))
        elif entry.endswith("/"):                         # a top-level folder
            folder = entry.rstrip("/")
            target = os.path.join(base, folder)
            if folder == "translations" and os.path.isdir(target):
                found += [os.path.join(PYSIDE_DIR, folder, n) for n in sorted(os.listdir(target))
                          if n not in KEEP_TRANSLATIONS]
            elif os.path.exists(target):
                found.append(os.path.join(PYSIDE_DIR, folder))
        else:
            found += [os.path.join(PYSIDE_DIR, n) for n in names
                      if fnmatch.fnmatchcase(n.lower(), entry.lower())]
    return sorted(set(found))


def _strip_zip(zip_path):
    removed = []
    tmp = zip_path + ".tmp"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if not info.filename.endswith("/") and _member_forbidden(info.filename):
                removed.append(info.filename)
                continue
            dst.writestr(info, src.read(info.filename))
    os.replace(tmp, zip_path)
    return removed


def _remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


def prune(dist):
    """Delete the network modules from the folder. Returns the removed paths, relative to `dist`."""
    removed = []
    zip_path = os.path.join(dist, PYTHON_DIR, ZIP_NAME)
    if os.path.isfile(zip_path) and forbidden_zip_members(zip_path):
        removed += [os.path.join(PYTHON_DIR, ZIP_NAME, n) for n in _strip_zip(zip_path)]
    for rel in forbidden_binaries(dist) + forbidden_qt_paths(dist):
        _remove(os.path.join(dist, rel))
        removed.append(rel)
    return removed
