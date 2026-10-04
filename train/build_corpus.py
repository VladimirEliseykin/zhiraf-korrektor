"""Assemble a training corpus from sentence files with per-source caps and repeats.

Usage: python build_corpus.py <out.jsonl> <seed> <path>:<limit>:<repeat>[:admin] ...
limit 0 = take everything; repeat > 1 duplicates a source (each copy is corrupted differently
during training, so this gives the domain-matched text more weight without overfitting a single
corruption). The ":admin" flag applies the genre filter for the ruwikisource admin pass:
works with an author in parentheses are literature (letters of writers, speeches), and letters,
reports and reviews count only with an official requisite (number or date).
"""
import json
import random
import re
import sys

AUTHOR = re.compile(r"\([^)]*\)")
PERSONAL_GENRE = re.compile(r"^(Письмо|Доклад|Обзор|Разъяснение|Информационное письмо)", re.I)
REQUISITE = re.compile(r"№|\bот \d{1,2}\.\d{2}\.\d{2,4}|\b(19[6-9]\d|20\d\d)\b")


def admin_ok(title):
    if AUTHOR.search(title):
        return False
    if PERSONAL_GENRE.match(title):
        return bool(REQUISITE.search(title))
    return True


def main():
    out_path, seed = sys.argv[1], int(sys.argv[2])
    rng = random.Random(seed)
    corpus = []
    for spec in sys.argv[3:]:
        parts = spec.split(":")
        path, limit, repeat = parts[0], int(parts[1]), int(parts[2])
        rows = [json.loads(l) for l in open(path, encoding="utf-8")]
        if "admin" in parts[3:]:
            rows = [r for r in rows if admin_ok(r["doc"])]
        if limit and len(rows) > limit:
            rows = rng.sample(rows, limit)
        corpus += rows * repeat
        print("%-60s %8d x%d" % (path.rsplit("/", 1)[-1], len(rows), repeat))
    rng.shuffle(corpus)
    with open(out_path, "w", encoding="utf-8") as out:
        for r in corpus:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("total %d" % len(corpus))


if __name__ == "__main__":
    main()
