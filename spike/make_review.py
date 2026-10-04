"""Throwaway spike: build random review batches from the guarded document results."""
import json
import random
import sys

sys.path.insert(0, "/home/general/vm/win7/spike")
from diff_docs import edits  # noqa: E402

base = "/home/general/vm/win7/spike/"
items = [json.loads(line) for line in open(base + "doc-results-guarded.jsonl", encoding="utf-8")]
rng = random.Random(42)
changed = [i for i in items if i["changed"]]
unchanged = [i for i in items if not i["changed"]]
changed_sample = rng.sample(changed, 300)
unchanged_sample = rng.sample(unchanged, 150)

for n in range(4):
    batch = []
    for k, item in enumerate(changed_sample[n * 75:(n + 1) * 75]):
        batch.append({
            "id": "C%d-%02d" % (n + 1, k + 1),
            "original": item["src"],
            "corrected": item["out"],
            "edits": [{"было": b, "стало": a} for b, a in edits(item["src"], item["out"])],
        })
    json.dump(batch, open(base + "review-changed-%d.json" % (n + 1), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

for n in range(2):
    batch = [{"id": "U%d-%02d" % (n + 1, k + 1), "sentence": item["src"]}
             for k, item in enumerate(unchanged_sample[n * 75:(n + 1) * 75])]
    json.dump(batch, open(base + "review-unchanged-%d.json" % (n + 1), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("changed population:", len(changed), "unchanged population:", len(unchanged))
