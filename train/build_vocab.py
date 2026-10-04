"""Word-form frequency list from the clean corpora, for the spelling check.

Usage: python build_vocab.py <out.tsv> <min_count> <corpus.jsonl>...
Lowercased Cyrillic word forms with their counts. It extends the dictionaries with modern terms
("кибербезопасность", "фишинг") and ranks spelling suggestions by frequency. Evaluation sentences
never reach it: the corpora are built without them.
"""
import collections
import json
import re
import sys

WORD = re.compile(r"[а-яё]+(?:-[а-яё]+)*")


def main():
    out_path, min_count, paths = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    counts = collections.Counter()
    for path in paths:
        for line in open(path, encoding="utf-8"):
            counts.update(WORD.findall(json.loads(line)["src"].lower()))
    kept = [(w, n) for w, n in counts.items() if n >= min_count]
    kept.sort(key=lambda x: -x[1])
    with open(out_path, "w", encoding="utf-8") as out:
        for w, n in kept:
            out.write("%s\t%d\n" % (w, n))
    print("forms %d, kept %d (count >= %d)" % (len(counts), len(kept), min_count))


if __name__ == "__main__":
    main()
