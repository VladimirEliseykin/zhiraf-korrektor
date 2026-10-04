"""Gold expansion 3 (2026-10-04): 2100 more sentences in 14 batches (9-22), excluding everything
already reviewed or annotated. Batches 9-15 are dev, 16-22 test."""
import json
import os
import random

base = os.path.dirname(os.path.abspath(__file__)) + "/"
items = [json.loads(line) for line in open(base + "doc-results-guarded.jsonl", encoding="utf-8")]

used = set()
for n in range(1, 5):
    used.update(x["original"] for x in json.load(open(base + "review-changed-%d.json" % n, encoding="utf-8")))
for n in range(1, 9):
    used.update(x["sentence"] for x in json.load(open(base + "gold-batch-%d.json" % n, encoding="utf-8")))
for n in range(1, 3):
    used.update(x["sentence"] for x in json.load(open(base + "review-unchanged-%d.json" % n, encoding="utf-8")))

pool = [i for i in items if i["src"] not in used]
sample = random.Random(20261004).sample(pool, 2100)
for n in range(14):
    split = "dev3" if n < 7 else "test3"
    batch = [{"id": "%s-%d-%03d" % (split, n + 9, k + 1), "doc": item["doc"], "sentence": item["src"]}
             for k, item in enumerate(sample[n * 150:(n + 1) * 150])]
    json.dump(batch, open(base + "gold-batch-%d.json" % (n + 9), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("used before:", len(used), "pool:", len(pool))
