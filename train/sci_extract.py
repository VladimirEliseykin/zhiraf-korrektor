"""Extract sentences from RuSciBench Russian abstracts (scientific style, close to coursework texts).

Usage: python sci_extract.py <out.jsonl> <parquet>...
Abstracts are written by authors and are not proofread, so sentences with lowercase words
unknown to the morphological dictionary (likely typos) are dropped.
"""
import json
import re
import sys

import pyarrow.parquet as pq
import pymorphy3

from corpus_extract import SENTENCE_END, checkable

morph = pymorphy3.MorphAnalyzer()
LOWER_WORD = re.compile(r"\b[а-яё]+(?:-[а-яё]+)*\b")


def no_typos(sentence):
    return all(morph.word_is_known(w) for w in LOWER_WORD.findall(sentence) if "-" not in w)


def main():
    out_path, shards = sys.argv[1], sys.argv[2:]
    seen, kept, dropped = set(), 0, 0
    with open(out_path, "w", encoding="utf-8") as out:
        for shard in shards:
            table = pq.read_table(shard, columns=["paper_id", "abstract"])
            for pid, abstract in zip(table.column("paper_id").to_pylist(), table.column("abstract").to_pylist()):
                for s in SENTENCE_END.split(" ".join((abstract or "").split())):
                    s = s.strip()
                    if s in seen or not checkable(s):
                        continue
                    seen.add(s)
                    if not no_typos(s):
                        dropped += 1
                        continue
                    out.write(json.dumps({"doc": "sci:%s" % pid, "src": s}, ensure_ascii=False) + "\n")
                    kept += 1
    print("done: kept %d, dropped as possible typos %d" % (kept, dropped))


if __name__ == "__main__":
    main()
