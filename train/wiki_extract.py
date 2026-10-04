"""Extract clean sentences from Russian Wikipedia parquet shards (wikimedia/wikipedia, 20231101.ru).

Usage: python wiki_extract.py <out.jsonl> <max_sentences> <shard.parquet>...
"""
import json
import random
import sys

import pyarrow.parquet as pq

from corpus_extract import SENTENCE_END, checkable


def main():
    out_path, limit, shards = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    rng = random.Random(0)
    seen = set()
    kept = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for shard in shards:
            table = pq.read_table(shard, columns=["title", "text"])
            titles, texts = table.column("title").to_pylist(), table.column("text").to_pylist()
            order = list(range(len(texts)))
            rng.shuffle(order)
            for k in order:
                for paragraph in texts[k].split("\n"):
                    paragraph = " ".join(paragraph.split())
                    for s in SENTENCE_END.split(paragraph):
                        s = s.strip()
                        if s in seen or not checkable(s):
                            continue
                        seen.add(s)
                        out.write(json.dumps({"doc": "wiki:" + titles[k], "src": s}, ensure_ascii=False) + "\n")
                        kept += 1
                        if kept >= limit:
                            print("done:", kept)
                            return
            print("shard done, sentences so far:", kept, flush=True)
    print("done:", kept)


if __name__ == "__main__":
    main()
