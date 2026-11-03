"""Lay out the Windows 7 folder from fetched dependencies (host only)."""
import os
import posixpath
import shutil
import tarfile
import zipfile

REQUIRED_DLLS = ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")

PTH_LINES = ("python37.zip", ".", "Lib\\site-packages", "..\\app")
# VC runtime DLLs taken from the shiboken2 wheel (newer than the embed's vcruntime140.dll)
_VC_PREFIXES = ("vcruntime", "msvcp", "concrt", "vcomp", "vcamp", "vccorlib")
_UCRT_DIR = "Library/bin/"
_SKIP_DIRS = ("__pycache__", "tests")

README = (
    "Жираф.Корректор проверяет русский текст без интернета. Чтобы начать, откройте «Жираф.Корректор.exe».\r\n"
    "Ваш текст никуда не отправляется: программа не выходит в сеть.\r\n"
    "Журнал ошибок (файл «журнал.txt») — в папке «Жираф.Корректор», её можно открыть, "
    "введя %APPDATA% в строке проводника.\r\n"
    "В нём нет текста документов.\r\n"
    "Папку можно переносить целиком, например на флешку.\r\n"
)


def _safe_join(base, name):
    target = os.path.abspath(os.path.join(base, name))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("unsafe archive member: %r" % name)
    return target


def _extract_zip(path, dest, skip=None):
    base = os.path.abspath(dest)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if skip and skip(info.filename):
                continue
            target = _safe_join(base, info.filename)
            if info.filename.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


def _is_wheel_script(name):
    parts = name.split("/")
    return len(parts) > 2 and parts[0].endswith(".data") and parts[1] == "scripts"


def _copy_python_tree(src, dst):
    ignore = shutil.ignore_patterns(*_SKIP_DIRS)
    shutil.copytree(src, dst, ignore=ignore)


def _put_ucrt(tar_path, py_dir):
    with tarfile.open(tar_path) as t:
        for m in t.getmembers():
            if not (m.isfile() and m.name.startswith(_UCRT_DIR) and m.name.lower().endswith(".dll")):
                continue
            name = posixpath.basename(m.name)
            with t.extractfile(m) as src, open(os.path.join(py_dir, name), "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


def _put_vc_dlls(shiboken_wheel, py_dir):
    with zipfile.ZipFile(shiboken_wheel) as z:
        for info in z.infolist():
            parts = info.filename.split("/")
            if len(parts) == 2 and parts[0] == "shiboken2" and parts[1].lower().endswith(".dll") \
                    and parts[1].lower().startswith(_VC_PREFIXES):
                with z.open(info) as src, open(os.path.join(py_dir, parts[1]), "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)


def _put_models(models, dest, link):
    """Place the models; return how many files had to be copied because linking failed."""
    fallback = fallback_bytes = 0
    for root, dirs, names in os.walk(models):
        rel = os.path.relpath(root, models)
        out = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(out, exist_ok=True)
        for n in names:
            src, dst = os.path.join(root, n), os.path.join(out, n)
            if link:
                try:
                    os.link(src, dst)
                    continue
                except OSError:
                    fallback += 1  # different filesystem: fall back to a copy
                    fallback_bytes += os.path.getsize(src)
            shutil.copy2(src, dst)
    return fallback, fallback_bytes


def lay_out(dist, files, repo, models, link_models=True):
    """Build the folder in `dist`, which must be absent or empty."""
    if os.path.exists(dist) and os.listdir(dist):
        raise FileExistsError("dist folder is not empty: %s" % dist)
    os.makedirs(dist, exist_ok=True)
    py = os.path.join(dist, "python")
    site = os.path.join(py, "Lib", "site-packages")

    _extract_zip(files["python-embed"], py)
    os.makedirs(site, exist_ok=True)
    for key in sorted(files):
        if key.startswith("wheel:"):
            _extract_zip(files[key], site, skip=_is_wheel_script)

    _put_ucrt(files["ucrt"], py)
    _put_vc_dlls(files["wheel:shiboken2"], py)
    for n in REQUIRED_DLLS:
        if not os.path.isfile(os.path.join(py, n)):
            raise FileNotFoundError("runtime DLL missing from the layout: %s" % n)

    with open(os.path.join(py, "python37._pth"), "wb") as f:
        f.write(("\r\n".join(PTH_LINES) + "\r\n").encode("ascii"))

    # Qt 5.15 derives its plugin folder from the DLL path and finds nothing when that path has Cyrillic letters
    # (VM check without qt.conf: an ASCII path with a space works, a Cyrillic path without a space fails, so spaces
    # are not the cause); a qt.conf in the application directory (next to pythonw.exe) names it explicitly
    with open(os.path.join(py, "qt.conf"), "wb") as f:
        f.write(b"[Paths]\r\nPrefix = Lib/site-packages/PySide2\r\n")

    _copy_python_tree(os.path.join(repo, "app", "zhiraf"), os.path.join(dist, "app", "zhiraf"))
    _copy_python_tree(os.path.join(repo, "engine", "spellcheck"),
                      os.path.join(dist, "engine", "spellcheck"))
    art = os.path.join(dist, "engine", "art")
    os.makedirs(art)
    shutil.copy2(os.path.join(repo, "engine", "art", "start.jpg"), os.path.join(art, "start.jpg"))

    copied, size = _put_models(models, os.path.join(dist, "models"), link_models)
    if copied:
        print("модели: жёсткие ссылки не удались, скопировано %d файлов (%.1f ГБ)" % (copied, size / 1e9))

    with open(os.path.join(dist, "ЧИТАЙ-МЕНЯ.txt"), "wb") as f:
        f.write(README.encode("utf-8-sig"))
