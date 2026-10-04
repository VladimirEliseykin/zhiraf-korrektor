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
