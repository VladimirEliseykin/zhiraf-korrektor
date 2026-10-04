"""Count training sentences that coincide with evaluation sentences, ignoring punctuation and case.

Usage: python overlap_check.py <corpus.jsonl> <eval_file>...
Exact-match exclusion in tagger.load_corpus misses an evaluation sentence that differs from
its training twin only by the very commas or endings the model is scored on; this finds those.
"""
import json
import re
import sys

KEY = re.compile(r"[^\w]+")


def key(s):
    return KEY.sub(" ", s.lower().replace("ё", "е")).strip()


def eval_keys(path):
    keys = set()
    if path.endswith(".jsonl"):
        for line in open(path, encoding="utf-8"):
            keys.add(key(json.loads(line)["src"]))
    else:
        for x in json.load(open(path, encoding="utf-8")):
            keys.update(key(v) for k, v in x.items() if k in ("src", "gold", "sentence", "original"))
    return keys


def main():
    corpus, evals = sys.argv[1], sys.argv[2:]
    keys = set()
    for p in evals:
        keys |= eval_keys(p)
    hits = [json.loads(l)["src"] for l in open(corpus, encoding="utf-8") if key(json.loads(l)["src"]) in keys]
    print("%s: %d overlapping sentences" % (corpus.rsplit("/", 1)[-1], len(hits)))
    for h in hits[:10]:
        print("  ", h[:150])


if __name__ == "__main__":
    main()
