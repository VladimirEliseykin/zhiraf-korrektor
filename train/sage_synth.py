"""Synthetic (src, gold) pairs for the SAGE fine-tune from the clean corpus, with the realistic error generator.

    python sage_synth.py OUT_DIR [--corpus corpus/round2.jsonl] [--n-err 130000] [--n-clean 170000] [--chunk 5000]
        [--workers 4] [--seed 3] [--avoid sage_err.jsonl sage_clean.jsonl] [--root /home/general/vm/win7]

gold = the clean corpus sentence, src = corrupt_realistic(gold) whose labels restore it exactly (the recipes of the
tagger runs: commas = error rate 16, forms = error rate 4 with form scale 1.5, both at most 3 edits; half of the
sentences get each, the comma recipe also spoils some forms and the other way round). Clean pairs (src == gold) come from
OTHER corpus sentences, so a clean pair is never the twin of an erroneous one.
Excluded: every sentence whose key (overlap_check.key: no punctuation, case, yo) is an evaluation sentence (spike gold,
dev2, test2, public benchmark) or a sentence of the --avoid files (the real pairs / official clean ones).
Chunked and resumable: chunk i is written to OUT_DIR/chunks/synth-iiii.jsonl once done (a rerun skips the finished ones);
at the end the chunks are merged into OUT_DIR/synth_err.jsonl and synth_clean.jsonl (cut to --n-err / --n-clean) and
synth_stats.json. Rows: {"src", "gold", "pool": "synth", "kinds": ["comma", "form"]}.
"""
import argparse
import collections
import json
import multiprocessing
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
import overlap_check  # noqa: E402
import sage_data  # noqa: E402

RECIPES = {"comma": dict(error_rate=16.0, max_edits=3, form_scale=1.0),
           "form": dict(error_rate=4.0, max_edits=3, form_scale=1.5)}
_STATE = {}


def load_pool(a):
    from spellcheck.guards import BIBLIOGRAPHY, prepare
    texts, _ = sage_data.eval_texts(a.root)
    banned = {overlap_check.key(t) for t in texts}
    for path in a.avoid:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            banned.add(overlap_check.key(r["src"]))
            banned.add(overlap_check.key(r["gold"]))
    seen, pool, dropped = set(), [], collections.Counter()
    for line in open(os.path.join(a.root, a.corpus), encoding="utf-8"):
        s = prepare(json.loads(line)["src"])[1].strip()
        k = overlap_check.key(s)
        letters = sum(c.isalpha() for c in s)
        cyr = sum("а" <= c.lower() <= "я" or c in "ёЁ" for c in s)
        if not (5 <= sage_data.words(s) <= 60 and 25 <= len(s) <= 400) or cyr < 0.8 * max(letters, 1) or BIBLIOGRAPHY.search(s):
            dropped["shape"] += 1
        elif k in banned:
            dropped["eval_or_real_overlap"] += 1
        elif k in seen:
            dropped["duplicate"] += 1
        else:
            seen.add(k)
            pool.append(s)
    random.Random(a.seed).shuffle(pool)
    return pool, dict(dropped)


def work(i):
    from corrupt import corrupt_realistic, restore
    a, pool, n_corrupt = _STATE["a"], _STATE["pool"], _STATE["n_corrupt"]
    path = os.path.join(a.out, "chunks", "synth-%04d.jsonl" % i)
    if os.path.exists(path):
        return i, None
    rng = random.Random(a.seed * 1_000_003 + i)
    part = pool[i * a.chunk:(i + 1) * a.chunk]
    rows, stats = [], collections.Counter()
    for j, gold in enumerate(part):
        if j >= n_corrupt:
            rows.append({"src": gold, "gold": gold, "pool": "synth", "kinds": []})
            stats["clean"] += 1
            continue
        recipe = "comma" if rng.random() < 0.5 else "form"
        text, comma, form = corrupt_realistic(gold, rng, **RECIPES[recipe])
        if text == gold:
            stats["no_edit"] += 1
            continue
        if restore(text, comma, form) != gold:
            stats["restore_mismatch"] += 1
            continue
        kinds = (["comma"] if any(c != "KEEP" for c in comma) else []) + (["form"] if any(f != "KEEP" for f in form) else [])
        rows.append({"src": text, "gold": gold, "pool": "synth", "kinds": kinds})
        stats["err_" + recipe] += 1
        for k in kinds:
            stats["kind_" + k] += 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.rename(tmp, path)
    return i, dict(stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--corpus", default="corpus/round2.jsonl")
    ap.add_argument("--n-err", type=int, default=130000)
    ap.add_argument("--n-clean", type=int, default=170000)
    ap.add_argument("--chunk", type=int, default=5000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--root", default="/home/general/vm/win7")
    ap.add_argument("--avoid", nargs="*", default=[])
    ap.add_argument("--yield", dest="yld", type=float, default=0.44, help="share of corrupted sentences that get an error")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "chunks"), exist_ok=True)
    sys.path.insert(0, os.path.join(a.root, "spike"))
    pool, dropped = load_pool(a)
    n_corrupt_total = int(a.n_err / a.yld * 1.05)
    share = n_corrupt_total / (n_corrupt_total + a.n_clean)
    n_corrupt = round(a.chunk * share)
    n_chunks = -(-(n_corrupt_total + a.n_clean) // a.chunk)
    print("pool %d sentences (dropped %s); %d chunks of %d (%d corrupted + %d clean each)" % (
        len(pool), dropped, n_chunks, a.chunk, n_corrupt, a.chunk - n_corrupt), flush=True)
    if n_chunks * a.chunk > len(pool):
        raise SystemExit("the corpus pool is too small for %d chunks" % n_chunks)
    _STATE.update(a=a, pool=pool, n_corrupt=n_corrupt)
    total, t0 = collections.Counter(), time.time()
    with multiprocessing.get_context("fork").Pool(a.workers) as p:
        for i, st in p.imap_unordered(work, range(n_chunks)):
            if st:
                total.update(st)
            print("chunk %d done%s %.0fs" % (i, "" if st else " (kept)", time.time() - t0), flush=True)
    err, clean = [], []
    for i in range(n_chunks):
        for line in open(os.path.join(a.out, "chunks", "synth-%04d.jsonl" % i), encoding="utf-8"):
            r = json.loads(line)
            (err if r["src"] != r["gold"] else clean).append(line)
    err, clean = err[:a.n_err], clean[:a.n_clean]
    for name, data in (("synth_err.jsonl", err), ("synth_clean.jsonl", clean)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            f.writelines(data)
    stats = {"err": len(err), "clean": len(clean), "pool_dropped": dropped, "generation": dict(total),
             "kinds": dict(collections.Counter(k for l in err for k in json.loads(l)["kinds"]))}
    json.dump(stats, open(os.path.join(a.out, "synth_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
