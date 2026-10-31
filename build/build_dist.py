"""Build the Windows 7 folder with one command (host only).

Usage: python -m build.build_dist --out <dir> [--cache DIR] [--models DIR] [--copy-models]
"""
import argparse
import os
import shutil
import sys
import tarfile
import tempfile

from build.check_dist import check
from build.fetch import fetch_all
from build.icon import make_icon
from build.layout import lay_out
from build.make_launcher import make_launcher
from build.prune import prune

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NAME = "Жираф.Корректор"
CLANG = os.path.join("bin", "x86_64-w64-mingw32-clang")


def toolchain_dir(files, cache):
    """The unpacked llvm-mingw; unpack the downloaded archive into <cache>/toolchain on first use."""
    target = os.path.join(cache, "toolchain")
    if os.path.isfile(os.path.join(target, CLANG)):
        return target
    tmp = target + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with tarfile.open(files["toolchain"]) as t:
        for m in t.getmembers():
            parts = m.name.split("/", 1)  # drop the single top-level folder
            if len(parts) < 2 or not parts[1]:
                continue
            m.name = parts[1]
            t.extract(m, tmp)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return target


def _stats(path):
    size = count = 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            count += 1
            size += os.path.getsize(os.path.join(root, n))
    return size, count


def build(out, cache, models, repo, copy_models):
    final = os.path.join(out, NAME)
    tmp = final + ".tmp"
    if os.path.exists(final):
        raise FileExistsError("папка %s уже есть, удалите её" % final)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    try:
        files = fetch_all(cache_dir=cache)
        lay_out(tmp, files, repo, models, link_models=not copy_models)
        prune(tmp)
        with tempfile.TemporaryDirectory() as work:
            ico = os.path.join(work, "zhiraf.ico")
            make_icon(os.path.join(repo, "app", "zhiraf", "ui", "art", "logo.png"), ico)
            make_launcher(toolchain_dir(files, cache), os.path.join(tmp, NAME + ".exe"), ico)
        violations = check(tmp)
        if violations:
            raise RuntimeError("проверка папки не пройдена:\n" + "\n".join("  " + v for v in violations))
        os.replace(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return final


def main(argv):
    p = argparse.ArgumentParser(prog="build.build_dist")
    p.add_argument("--out", required=True)
    p.add_argument("--cache", default="~/vm/win7/dist-cache")
    p.add_argument("--models", default=os.path.join(ROOT, "engine", "models"))
    p.add_argument("--repo", default=ROOT)
    p.add_argument("--copy-models", action="store_true",
                   help="copy the models instead of hard-linking them (for another filesystem)")
    a = p.parse_args(argv)
    try:
        final = build(os.path.abspath(os.path.expanduser(a.out)), os.path.expanduser(a.cache),
                      os.path.abspath(a.models), os.path.abspath(a.repo), a.copy_models)
    except Exception as e:
        print("сборка не удалась: %s" % e)
        return 1
    size, count = _stats(final)
    print("готово: %s" % final)
    print("размер: %.2f ГБ, файлов: %d" % (size / 1e9, count))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
