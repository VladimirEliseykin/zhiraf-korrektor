"""Add the models to a folder built with --no-models (host only).

Usage: python -m build.add_models <dist folder> <models dir>

Copies (real copies, the result goes to a USB stick) every model folder and vocab.tsv into <dist>/models, removes
the placeholder note and runs the folder check. Exit code 1 and the list when anything is wrong.
"""
import os
import shutil
import sys

from build.check_dist import check
from build.layout import MODELS_PLACEHOLDER


def _copy(src, dst):
    """Copy through a .part file, so an interrupted copy never leaves a half file under the final name."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + ".part"
    try:
        with open(src, "rb") as s, open(part, "wb") as d:
            shutil.copyfileobj(s, d, 1 << 22)
        shutil.copystat(src, part)
        os.replace(part, dst)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise


def add_models(dist, models):
    """Copy the models in; return the number of files copied."""
    target = os.path.join(dist, "models")
    count = 0
    for name in sorted(os.listdir(models)):
        source = os.path.join(models, name)
        if os.path.isdir(source):
            for root, _dirs, names in os.walk(source):
                for n in sorted(names):
                    src = os.path.join(root, n)
                    _copy(src, os.path.join(target, os.path.relpath(src, models)))
                    count += 1
        elif name == "vocab.tsv":
            _copy(source, os.path.join(target, name))
            count += 1
    placeholder = os.path.join(target, MODELS_PLACEHOLDER)
    if os.path.exists(placeholder):
        os.remove(placeholder)
    return count


def main(argv):
    if len(argv) != 2:
        print("usage: python -m build.add_models <dist folder> <models dir>")
        return 2
    dist, models = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    for path in (os.path.join(dist, "models"), models):
        if not os.path.isdir(path):
            print("нет папки: %s" % path)
            return 1
    if not os.path.isfile(os.path.join(models, "vocab.tsv")):
        print("в папке моделей нет vocab.tsv: %s" % models)
        return 1
    try:
        count = add_models(dist, models)
    except OSError as e:
        print("копирование не удалось: %s" % e)
        return 1
    violations = check(dist, models)
    for v in violations:
        print("VIOLATION: " + v)
    if violations:
        print("%d violation(s)" % len(violations))
        return 1
    print("готово: скопировано файлов моделей: %d, папка проверена" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
