"""Throwaway spike: replay reviewer verdicts under a stricter edit policy."""
import collections
import json
import re
import subprocess
import sys

sys.path.insert(0, "/home/general/vm/win7/spike")
from diff_docs import kind  # noqa: E402

base = "/home/general/vm/win7/spike/"
WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")

verdicts = []
for n in range(1, 5):
    verdicts += json.load(open(base + "verdicts-changed-%d.json" % n, encoding="utf-8"))

words = sorted({w for v in verdicts for w in WORD.findall(v.get("было", "") + " " + v.get("стало", ""))})
result = subprocess.run(["hunspell", "-d", base + "dict/ru_RU", "-l", "-i", "utf-8"],
                        input="\n".join(words), capture_output=True, text=True)
unknown = set(result.stdout.split())


def known(text):
    return all(w not in unknown for w in WORD.findall(text))


def has_unknown(text):
    return any(w in unknown for w in WORD.findall(text))


import pymorphy3  # noqa: E402

morph = pymorphy3.MorphAnalyzer()


def lemmas(word):
    return {p.normal_form for p in morph.parse(word.lower())}


def same_lemmas(before, after):
    """Grammar fix = same words in another form; substitution = a different word."""
    a, b = WORD.findall(before), WORD.findall(after)
    if not a or len(a) != len(b):
        return False
    if WORD.sub("", before).replace(" ", "") != WORD.sub("", after).replace(" ", ""):
        return False  # punctuation changed together with the word
    if any(x[0].isupper() != y[0].isupper() for x, y in zip(a, b)):
        return False  # case changed together with the word
    return all(lemmas(x) & lemmas(y) for x, y in zip(a, b))


def policy(before, after):
    k = kind(before, after)
    if k == "запятая":
        return "add" if not before else "remove"
    if k == "замена слова":
        if has_unknown(before) and known(after):
            return "word"
        if known(before) and known(after) and same_lemmas(before, after):
            return "form"
        return None
    if k == "слитно/раздельно/дефис":
        return "join" if known(after) else None
    return None


kept = collections.defaultdict(collections.Counter)
dropped = collections.Counter()
for v in verdicts:
    rule = policy(v.get("было", ""), v.get("стало", ""))
    if rule:
        kept[rule][v["verdict"]] += 1
    else:
        dropped[v["verdict"]] += 1

for variant, rules in (("A: +запятые, слова по словарю, слитно", ("add", "word", "join")),
                       ("C: A + формы слов (та же лемма)", ("add", "word", "join", "form")),
                       ("B: C + удаление запятых", ("add", "remove", "word", "join", "form"))):
    total = collections.Counter()
    for r in rules:
        total.update(kept[r])
    precision = total["fix"] / max(1, total["fix"] + total["harm"])
    print("%-40s fix=%d harm=%d neutral=%d  точность=%.0f%%" % (variant, total["fix"], total["harm"], total["neutral"], 100 * precision))
for r, c in kept.items():
    print("  правило %-7s %s" % (r, dict(c)))
print("отброшено политикой:", dict(dropped))
