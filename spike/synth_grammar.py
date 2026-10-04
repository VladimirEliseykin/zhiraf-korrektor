"""Throwaway spike: inject one grammatical error (wrong word form) per clean sentence."""
import json
import random
import re

import pymorphy3

BASE = "/home/general/vm/win7/spike/"
WORD = re.compile(r"[А-Яа-яЁё]+")
morph = pymorphy3.MorphAnalyzer()
CASES = ["nomn", "gent", "datv", "accs", "ablt", "loct"]


def corrupt_word(word, rng):
    parse = morph.parse(word)[0]
    tag = parse.tag
    if parse.score < 0.6 or word[0].isupper():
        return None
    options = []
    if tag.POS in ("NOUN", "ADJF", "PRTF") and tag.case:
        for case in CASES:
            if case != tag.case:
                options.append({case})
    if tag.POS == "VERB" and tag.number:
        options.append({"plur" if tag.number == "sing" else "sing"})
        if tag.gender:
            options.append({g for g in ("masc", "femn", "neut") if g != tag.gender} and {rng.choice([g for g in ("masc", "femn", "neut") if g != tag.gender])})
    rng.shuffle(options)
    for grammemes in options:
        new = parse.inflect(grammemes)
        if new and new.word != word.lower() and new.word not in {p.word for p in morph.parse(word)}:
            # the new string must not also be a valid reading of the original form
            if not any(p.tag == tag for p in morph.parse(new.word)):
                return new.word
    return None


def main():
    rng = random.Random(7)
    sentences = [json.loads(line)["src"] for line in open(BASE + "official-sentences.jsonl", encoding="utf-8")]
    rng.shuffle(sentences)
    out = []
    for s in sentences:
        words = [m for m in WORD.finditer(s) if len(m.group(0)) > 3]
        rng.shuffle(words)
        for m in words:
            new = corrupt_word(m.group(0), rng)
            if new:
                out.append({"src": s[:m.start()] + new + s[m.end():], "gold": s,
                            "orig_word": m.group(0), "bad_word": new, "start": m.start()})
                break
        if len(out) == 1000:
            break
    for name, part in (("synth-dev", out[:500]), ("synth-test", out[500:])):
        json.dump(part, open(BASE + name + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for x in out[:8]:
        print(x["orig_word"], "->", x["bad_word"], "|", x["src"][:110])
    print(len(out))


if __name__ == "__main__":
    main()
