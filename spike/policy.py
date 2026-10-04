"""Throwaway spike: edit policies on top of the raw SAGE output.

"guards": protective layer only (lists, digits, latin, abbreviations, quotes...).
"C": guards + allow only comma insertions, dictionary-confirmed typo fixes,
     same-lemma word-form fixes and joined/hyphenated spellings.
"C+rm": C + comma removals.
"""
import difflib
import re
import subprocess

import pymorphy3

from guards import TOKEN, allowed as guard_allowed

WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
DICT = "/home/general/vm/win7/spike/dict/ru_RU"
morph = pymorphy3.MorphAnalyzer()
_unknown = None


def preload_lexicon(texts):
    """hunspell is a CLI here, so look up the whole vocabulary once."""
    global _unknown
    words = sorted({w for t in texts for w in WORD.findall(t)})
    result = subprocess.run(["hunspell", "-d", DICT, "-l", "-i", "utf-8"],
                            input="\n".join(words), capture_output=True, text=True)
    _unknown = set(result.stdout.split())


def known(text):
    return all(w not in _unknown for w in WORD.findall(text))


def has_unknown(text):
    return any(w in _unknown for w in WORD.findall(text))


def lemmas(word):
    return {p.normal_form for p in morph.parse(word.lower())}


def same_word_forms(before, after):
    a, b = WORD.findall(before), WORD.findall(after)
    if not a or len(a) != len(b):
        return False
    if WORD.sub("", before).replace(" ", "") != WORD.sub("", after).replace(" ", ""):
        return False
    if any(x[0].isupper() != y[0].isupper() for x, y in zip(a, b)):
        return False
    return all(lemmas(x) & lemmas(y) for x, y in zip(a, b))


def edit_class(before, after):
    b, a = before.strip(), after.strip()
    if not b and a == ",":
        return "comma_add"
    if b == "," and not a:
        return "comma_remove"
    if WORD.findall(b) and WORD.findall(a):
        if b.replace(" ", "").replace("-", "").lower() == a.replace(" ", "").replace("-", "").lower() and b.lower() != a.lower():
            return "join"
        if has_unknown(b) and known(a) and len(WORD.findall(b)) == len(WORD.findall(a)):
            return "typo"
        if known(b) and known(a) and same_word_forms(b, a):
            return "form"
    return "other"


ALLOWED = {
    "guards": None,
    "C": {"comma_add", "typo", "form", "join"},
    "C+rm": {"comma_add", "comma_remove", "typo", "form", "join"},
    "words": {"typo", "form", "join"},
}


def apply_policy(src, out, mode):
    """Rebuild src keeping only the model edits the policy allows. Returns (text, classes)."""
    a, b = TOKEN.findall(src), TOKEN.findall(out)
    first_lower = src.lstrip()[:1].islower()
    last_word = max((i for i, t in enumerate(a) if t.strip()), default=0)
    pieces, classes = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            pieces.extend(a[i1:i2])
            continue
        before, after = a[i1:i2], b[j1:j2]
        ok = guard_allowed(before, after, i1 == 0, i2 > last_word, first_lower)
        cls = edit_class("".join(before), "".join(after)) if ok else "guarded"
        if ok and ALLOWED[mode] is not None and cls not in ALLOWED[mode]:
            ok = False
        pieces.extend(after if ok else before)
        if ok:
            classes.append(cls)
    return "".join(pieces), classes
