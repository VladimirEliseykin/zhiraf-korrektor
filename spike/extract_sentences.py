"""Throwaway spike: split extracted document texts into checkable Russian sentences."""
import glob
import json
import os
import re
import sys

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"\d")


def checkable(sentence):
    words = sentence.split()
    if len(words) < 5 or len(words) > 60:
        return False
    letters = len(CYRILLIC.findall(sentence))
    if letters < 0.6 * len(sentence.replace(" ", "")):
        return False
    if len(LATIN.findall(sentence)) > 0.2 * letters:
        return False
    if len(DIGIT.findall(sentence)) > 0.15 * len(sentence):
        return False
    if "\t" in sentence or "...." in sentence:
        return False
    return sentence[-1] in ".!?…:;"


def main():
    src_dir, out_path = sys.argv[1], sys.argv[2]
    seen = set()
    total = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for path in sorted(glob.glob(os.path.join(src_dir, "*.txt"))):
            doc = os.path.basename(path)[:-4]
            kept = 0
            with open(path, encoding="utf-8-sig") as f:
                for paragraph in f:
                    paragraph = re.sub(r"\s+", " ", paragraph).strip()
                    for sentence in SENTENCE_END.split(paragraph):
                        sentence = sentence.strip()
                        if sentence in seen or not checkable(sentence):
                            continue
                        seen.add(sentence)
                        out.write(json.dumps({"doc": doc, "src": sentence}, ensure_ascii=False) + "\n")
                        kept += 1
            total += kept
            print("%6d  %s" % (kept, doc))
    print("%6d  TOTAL" % total)


if __name__ == "__main__":
    main()
