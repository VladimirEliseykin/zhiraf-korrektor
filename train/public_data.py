"""Convert public Russian error-correction datasets to our gold format and report per-category edit counts.

Usage: python public_data.py convert   # writes data-public/converted/<name>.jsonl and stats.json
Row: {"doc", "src", "gold", "source", "domain"}. Raw data lives in data-public/ (git-ignored: dataset licenses
may forbid redistribution), never commit it.

Pipeline per dataset: read pairs -> sentence-split long texts (only when src and gold split into the same
number of sentences) -> drop full rewrites (changed chars > 30% of the longer side) -> keep every pair with
src != gold plus a capped share of clean pairs -> drop duplicates inside the data, then pairs whose normalised
text is in the evaluation sets (spike/*.jsonl, gold-annot) or in the training corpus (corpus/round2.jsonl).
"""
import csv
import difflib
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter

MAIN = "/home/general/vm/win7/"
PUB = MAIN + "data-public/"
OUT = PUB + "converted/"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, MAIN + "spike")
sys.path.insert(0, MAIN + "payload")

KEY = re.compile(r"[^\w]+")
SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"(\d—-])")
CLEAN_SHARE = 0.1  # clean pairs kept relative to the number of erroneous ones
MAX_CHANGED = 0.3
SPLIT_OVER = 300


def key(s):
    return KEY.sub(" ", s.lower().replace("ё", "е")).strip()


def jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def split_pair(src, gold):
    if len(src) <= SPLIT_OVER and len(gold) <= SPLIT_OVER:
        return [(src, gold)]
    a, b = SPLIT.split(src), SPLIT.split(gold)
    return list(zip(a, b)) if len(a) == len(b) else [(src, gold)]


def changed_share(src, gold):
    m = difflib.SequenceMatcher(a=src, b=gold, autojunk=False)
    same = sum(b.size for b in m.get_matching_blocks())
    return 1 - same / max(len(src), len(gold), 1)


# ---- readers: yield (doc, src, gold, domain) ----

def read_sc(subdir, variant):
    base = PUB + variant + "/"
    for sub, doc_by_domain in (("MultidomainGold", True), ("RUSpellRU", False), ("MedSpellchecker", False),
                               ("GitHubTypoCorpusRu", False)):
        for split in ("train", "test"):
            path = base + "%s/%s.json" % (sub, split)
            if not os.path.exists(path):
                continue
            for r in jsonl(path):
                domain = r["domain"]
                yield sub + "/" + domain, r["source"], r["correction"], domain


def reader_sc_punct():
    return read_sc(None, "spellcheck_punctuation_benchmark")


def reader_sc_plain():
    return read_sc(None, "spellcheck_benchmark")


def reader_inkoziev():
    for r in json.load(open(PUB + "inkoziev_spellchecker/test.json", encoding="utf-8")):
        if r["domain"] == "prose" and "\n" not in r["text"]:
            yield "inkoziev/" + r["error_type"].split(":")[0], r["text"], r["fixed_text"], "prose"


def reader_dreuxx():
    for r in csv.DictReader(open(PUB + "dreuxx26_russian_gec/data.csv", encoding="utf-8")):
        yield "dreuxx26", r["incorrect"], r["correct"], "synthetic-suspect"


DATASETS = [  # name, reader, source label (order matters: earlier sets win cross-dataset duplicates)
    ("sc_punct", reader_sc_punct, "ai-forever/spellcheck_punctuation_benchmark (MIT)"),
    ("sc_plain", reader_sc_plain, "ai-forever/spellcheck_benchmark (MIT)"),
    ("inkoziev", reader_inkoziev, "inkoziev/spellchecker test (MIT)"),
    ("dreuxx26", reader_dreuxx, "dreuxx26/russian_gec (CC-BY-4.0, synthetic-looking)"),
]


def known_keys():
    """Normalised texts of evaluation sets and of the training corpus."""
    ev = set()
    for p in glob.glob(MAIN + "spike/*.jsonl"):
        for r in jsonl(p):
            for k in ("src", "gold"):
                if isinstance(r.get(k), str):
                    ev.add(key(r[k]))
    for p in glob.glob(MAIN + "spike/gold-annot-*.json"):
        for r in json.load(open(p, encoding="utf-8")):
            ev.add(key(r["sentence"]))
            ev.add(key(r["gold"]))
    train = set()
    for line in open(MAIN + "corpus/round2.jsonl", encoding="utf-8"):
        train.add(key(json.loads(line)["src"]))
    return ev, train


def convert():
    os.makedirs(OUT, exist_ok=True)
    ev, train = known_keys()
    seen = set()
    stats = {}
    for name, reader, label in DATASETS:
        c = Counter()
        bad, clean = [], []
        for doc, src, gold, domain in reader():
            if not src or not gold:
                c["null"] += 1
                continue
            for s, g in split_pair(src.strip(), gold.strip()):
                c["pairs"] += 1
                if not s or not g:
                    continue
                if s != g and changed_share(s, g) > MAX_CHANGED:
                    c["dropped_rewrite"] += 1
                    continue
                row = {"doc": doc + "#" + hashlib.md5(src.encode()).hexdigest()[:8], "src": s, "gold": g, "source": name, "domain": domain}
                (bad if s != g else clean).append(row)
        keep = bad + clean[:int(len(bad) * CLEAN_SHARE)]
        c["clean_total"], c["clean_kept"] = len(clean), len(keep) - len(bad)
        rows = []
        for row in keep:
            k = key(row["src"])
            if k in seen or key(row["gold"]) in seen:
                c["dup_inside_or_earlier_set"] += 1
            elif k in ev or key(row["gold"]) in ev:
                c["overlap_eval_spike"] += 1
            elif k in train or key(row["gold"]) in train:
                c["overlap_train_round2"] += 1
            else:
                seen.add(k)
                seen.add(key(row["gold"]))
                rows.append(row)
        c["kept"] = len(rows)
        with open(OUT + name + ".jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        stats[name] = dict(c, source=label)
        print(name, dict(c))
    json.dump(stats, open(OUT + "convert-stats.json", "w"), ensure_ascii=False, indent=1)


def kinds():
    """Edit counts by our types per dataset and per (dataset, domain)."""
    import bench
    import coverage
    result = {}
    for p in sorted(glob.glob(OUT + "*.jsonl")):
        name = os.path.basename(p)[:-6]
        per = {}
        for r in jsonl(p):
            for e in bench.edits(r["src"], r["gold"]):
                for scope in (name, name + " / " + r["doc"]):
                    per.setdefault(scope, Counter())[coverage.kind(e)] += 1
            per.setdefault(name + " #sent", Counter())["sent"] += 1
        # comma edits in text that already carries punctuation (a missed comma, not a wholly unpunctuated text)
        for r in jsonl(p):
            if any(ch in r["src"] for ch in ",;:—–"):
                n = sum(1 for e in bench.edits(r["src"], r["gold"]) if coverage.kind(e) == "запятая")
                per.setdefault(name + " #comma-in-punctuated", Counter())["comma"] += n if n <= 2 else 0
        result.update(per)
    json.dump({k: dict(v) for k, v in result.items()}, open(OUT + "kinds.json", "w"), ensure_ascii=False, indent=1)
    for k, v in result.items():
        print(k, dict(v))


EVAL_DOMAINS = ("MedSpellchecker/", "GitHubTypoCorpusRu/", "MultidomainGold/news", "MultidomainGold/web",
                "MultidomainGold/literature", "MultidomainGold/social_media")
MIXED_DOMAINS = ("MultidomainGold/reviews", "RUSpellRU/")  # a quarter of the documents goes to eval
EVAL_SHARE = 25


def bucket(doc):
    return int(hashlib.md5(doc.encode()).hexdigest(), 16) % 100


def split():
    """Document-disjoint split: dev2/test2 (eval) and train_pub. Whole documents never straddle the splits."""
    out = {"dev2": [], "test2": [], "train_pub": []}
    pre = [r for r in jsonl(OUT + "sc_punct.jsonl")]
    for r in pre:
        b = bucket(r["doc"])
        if r["doc"].startswith(EVAL_DOMAINS):
            out["dev2" if b % 2 == 0 else "test2"].append(r)
        elif r["doc"].startswith(MIXED_DOMAINS) and b < EVAL_SHARE:
            out["dev2" if b % 2 == 0 else "test2"].append(r)
        else:
            out["train_pub"].append(r)
    prefixes = {key(r["src"])[:30] for rs in (out["dev2"], out["test2"]) for r in rs}
    prefixes |= {key(r["gold"])[:30] for rs in (out["dev2"], out["test2"]) for r in rs}
    leaked = 0
    for r in jsonl(OUT + "sc_plain.jsonl"):  # near-duplicates of eval sentences must not reach training
        if key(r["src"])[:30] in prefixes or key(r["gold"])[:30] in prefixes:
            leaked += 1
        else:
            out["train_pub"].append(r)
    for name, rows in out.items():
        with open(OUT + name + ".jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(name, len(rows))
    print("sc_plain rows withheld as near-duplicates of eval:", leaked)


if __name__ == "__main__":
    {"convert": convert, "kinds": kinds, "split": split}[sys.argv[1]]()
