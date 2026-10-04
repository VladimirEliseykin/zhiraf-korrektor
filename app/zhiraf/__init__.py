"""Жираф.Корректор: the program around the spellcheck engine.

Every module must run on the embeddable Python 3.7 of Windows 7 (checked by vermin in tests).
Layout (development and the shipped folder alike): <root>/app/zhiraf, <root>/engine/spellcheck,
models in <root>/models (shipped) or <root>/engine/models (development).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE_DIR = os.path.join(ROOT, "engine")
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)


def models_dir():
    """Folder with sage/, commas/, forms/ and vocab.tsv."""
    override = os.environ.get("ZHIRAF_MODELS")
    if override:
        return override
    shipped = os.path.join(ROOT, "models")
    # a folder that merely exists is not enough: stale unrelated "models" folders must not shadow ours
    return shipped if os.path.isfile(os.path.join(shipped, "vocab.tsv")) else os.path.join(ENGINE_DIR, "models")


def missing_models(folder):
    """A message in Russian naming the first thing missing in the models folder, or None if it is complete."""
    if not os.path.isdir(folder):
        return "Не найдена папка с моделями: %s." % folder
    for name, is_dir in (("vocab.tsv", False), ("sage", True), ("commas", True), ("forms", True)):
        path = os.path.join(folder, name)
        if not (os.path.isdir(path) if is_dir else os.path.isfile(path)):
            what = "папка «%s»" % name if is_dir else "файл «%s»" % name
            return "В папке с моделями (%s) не хватает: %s." % (folder, what)
    return None
