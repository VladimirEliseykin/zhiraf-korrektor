"""Throwaway spike: sample fresh sentences for the gold benchmark (dev + test)."""
import json
import random

base = "/home/general/vm/win7/spike/"
items = [json.loads(line) for line in open(base + "doc-results-guarded.jsonl", encoding="utf-8")]

reviewed = set()
for name in ["review-changed-%d.json" % n for n in range(1, 5)]:
    reviewed.update(x["original"] for x in json.load(open(base + name, encoding="utf-8")))
for name in ["review-unchanged-%d.json" % n for n in range(1, 3)]:
    reviewed.update(x["sentence"] for x in json.load(open(base + name, encoding="utf-8")))

pool = [i for i in items if i["src"] not in reviewed]
rng = random.Random(2026)
sample = rng.sample(pool, 400)
for n in range(4):
    split = "dev" if n < 2 else "test"
    batch = [{"id": "%s-%d-%03d" % (split, n + 1, k + 1), "doc": item["doc"], "sentence": item["src"]}
             for k, item in enumerate(sample[n * 100:(n + 1) * 100])]
    json.dump(batch, open(base + "gold-batch-%d.json" % (n + 1), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("excluded reviewed:", len(items) - len(pool), "pool:", len(pool))
