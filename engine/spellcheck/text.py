"""Word segmentation and inflection shared by training (label generation) and checking.

The tagger was trained with labels aligned to words_of(); the checker must split words the same way.
"""
import re

from .morph import morph

WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:[-‑][А-Яа-яЁёA-Za-z0-9]+)*")


def words_of(text):
    return list(WORD.finditer(text))


def inflect(word, label):
    """Put word into the grammemes of a form label ("case:gent|number:plur"); None if impossible."""
    grammemes = {kv.split(":")[1] for kv in label.split("|")}
    for p in morph.parse(word.lower()):
        new = p.inflect(grammemes)
        if new and new.word != word.lower():
            return new.word if word[0].islower() else new.word.capitalize()
    return None
