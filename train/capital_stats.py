"""Which common nouns are legitimately written with a capital in the middle of a sentence.

Usage: python capital_stats.py <corpus.jsonl> [--out engine/spellcheck/capital_lemmas.txt] [--max-share 0.02]

Streams the clean corpus (one JSON object per line, field "src") and counts, per noun lemma, how often the
word stands mid-sentence with a capital ("Министерство", "Служба") and how often without. A lemma whose
capitalised share exceeds --max-share is a title word of official language: LOWER corruptions must never
use it (corrupt.py) and the checker never lowers it (checker.py). The result is written as a data file,
one lemma per line, no sentences; the hand-picked title nouns the checker used to carry are kept in it.
"""
import argparse
import collections
import json
import os
import sys

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")
sys.path.insert(0, ENGINE)
from spellcheck.guards import BIBLIOGRAPHY, protected, quoted_spans  # noqa: E402
from spellcheck.morph import morph  # noqa: E402
from spellcheck.text import words_of  # noqa: E402

NOT_COMMON = ("Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad")
HAND_PICKED = ("федерация", "республика", "конституция", "правительство", "президент", "дума", "собрание",
               "совет", "союз", "государство", "кодекс", "палата", "суд")
DEFAULT_OUT = os.path.join(ENGINE, "spellcheck", "capital_lemmas.txt")


def noun_lemma(low, cache):
    """Lemma of a common noun (as the LOWER places see it) or None."""
    if low not in cache:
        parse = morph.parse(low)[0]
        ok = parse.score >= 0.4 and parse.tag.POS == "NOUN" and not any(g in parse.tag for g in NOT_COMMON)
        cache[low] = parse.normal_form if ok else None
    return cache[low]


def count(path):
    counts = collections.defaultdict(lambda: [0, 0])  # lemma -> [capitalised, lowercase]
    cache = {}
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            body = json.loads(line)["src"]
            n += 1
            if BIBLIOGRAPHY.search(body):
                continue
            quotes = quoted_spans(body)
            ms = words_of(body)
            for i in range(1, len(ms)):
                m, prev = ms[i], ms[i - 1]
                w = m.group(0)
                # the places LOWER uses: a letter word, one space, then the noun
                if len(w) < 4 or not w.isalpha() or body[prev.end():m.start()] != " " or not prev.group(0)[:1].isalpha():
                    continue
                if protected(w) or any(a < m.start() < b for a, b in quotes):
                    continue
                if w.islower():
                    kind = 1
                elif w[0].isupper() and w[1:].islower():
                    kind = 0
                else:
                    continue
                lemma = noun_lemma(w.lower(), cache)
                if lemma:
                    counts[lemma][kind] += 1
    return counts, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-share", type=float, default=0.02)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    counts, n = count(args.corpus)
    shares = {lemma: cap / (cap + low) for lemma, (cap, low) in counts.items()}
    excluded = sorted(lemma for lemma, s in shares.items() if s > args.max_share)
    kept = sorted(set(excluded) | set(HAND_PICKED))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Common-noun lemmas that official text writes with a capital in the middle of a sentence.\n")
        f.write("# Made by train/capital_stats.py over the clean corpus (%d sentences): every noun lemma whose\n" % n)
        f.write("# mid-sentence capitalised share is above %.0f%% (%d lemmas), plus the hand-picked title nouns.\n"
                % (100 * args.max_share, len(excluded)))
        f.write("# The checker never lowers these and corrupt.py never builds LOWER errors from them. Lemmas only.\n")
        f.write("\n".join(kept) + "\n")
    print("sentences %d, noun lemmas %d, excluded (share > %.2f) %d, file %d lemmas" % (
        n, len(counts), args.max_share, len(excluded), len(kept)))
    top = sorted(excluded, key=lambda l: -sum(counts[l]))[:args.top]
    for lemma in top:
        cap, low = counts[lemma]
        print("%-20s capitalised %6d lowercase %6d share %.3f" % (lemma, cap, low, shares[lemma]))


if __name__ == "__main__":
    main()
