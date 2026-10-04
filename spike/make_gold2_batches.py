"""Throwaway spike: 600 more gold sentences, excluding everything already reviewed or annotated."""
import json
import random

base = "/home/general/vm/win7/spike/"
items = [json.loads(line) for line in open(base + "doc-results-guarded.jsonl", encoding="utf-8")]

used = set()
for n in range(1, 5):
    used.update(x["original"] for x in json.load(open(base + "review-changed-%d.json" % n, encoding="utf-8")))
    used.update(x["sentence"] for x in json.load(open(base + "gold-batch-%d.json" % n, encoding="utf-8")))
for n in range(1, 3):
    used.update(x["sentence"] for x in json.load(open(base + "review-unchanged-%d.json" % n, encoding="utf-8")))

pool = [i for i in items if i["src"] not in used]
sample = random.Random(777).sample(pool, 600)
for n in range(4):
    split = "dev2" if n < 2 else "test2"
    batch = [{"id": "%s-%d-%03d" % (split, n + 5, k + 1), "doc": item["doc"], "sentence": item["src"]}
             for k, item in enumerate(sample[n * 150:(n + 1) * 150])]
    json.dump(batch, open(base + "gold-batch-%d.json" % (n + 5), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("used before:", len(used), "pool:", len(pool))
