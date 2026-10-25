"""Training pairs for the SAGE fine-tune: real error pairs with only the edits we want the model to make.

The model should learn commas, word forms (endings), spelling of single words and joined/hyphen spelling.
Every other difference between src and gold (final period, dashes, colons and other punctuation, case, digits,
latin text, rewritten phrases, ё/quotes) is "normalised away": the gold text is copied INTO src, so the pair
holds no such edit and the model sees them only as text to keep. A pair with no wanted edit left becomes a
clean example (src == gold). Pairs rewritten too heavily are dropped (counted).

    python sage_data.py OUT_DIR [--root /home/general/vm/win7] [--official 10000] [--seed 7]

Writes OUT_DIR/sage_err.jsonl (pairs with >= 1 wanted edit), OUT_DIR/sage_clean.jsonl (src == gold, pool =
hard | pair | official) and OUT_DIR/sage_data_stats.json. Rows: {"src", "gold", "pool", "kinds"}.
Never used: spike gold (dev, test, official), dev2, test2: their sentences and the documents of dev2/test2 are
excluded by text and by doc id.
"""
import argparse
import collections
import difflib
import json
import os
import random
import re
import sys

TOKEN = re.compile(r"\w+(?:-\w+)*|[^\w\s]")
CYR = re.compile(r"^[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*$")
TRANS = str.maketrans({"ё": "е", "Ё": "Е", "—": "-", "–": "-", "«": '"', "»": '"', "“": '"', "”": '"', "„": '"'})
MAX_REGION_WORDS = 4     # a rewritten stretch longer than this (words) drops the pair
MAX_REWRITTEN = 6        # ... and so do more rewritten words in all
MAX_EDITS = 8            # wanted edits per sentence; more is noise
MAX_WORDS = 120          # does not fit 192 tokens anyway

_morph = None


def morph():
    global _morph
    if _morph is None:
        import pymorphy3
        _morph = pymorphy3.MorphAnalyzer()
    return _morph


def lev(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = row
    return previous[-1]


def same_lemma(a, b):
    la = {p.normal_form for p in morph().parse(a.lower())[:3]}
    lb = {p.normal_form for p in morph().parse(b.lower())[:3]}
    return bool(la & lb)


def classify(before, after):
    """Kind of an edit (tokens before -> after) if we want it taught, else None (to be normalised away)."""
    if not before or not after:
        side = before or after
        return "comma" if side == [","] else None
    if before == [","] or after == [","]:
        return None
    b, a = " ".join(before), " ".join(after)
    if b.lower().translate(TRANS) == a.lower().translate(TRANS):
        return None                                          # case, yo, quotes, dash glyphs
    if not all(CYR.match(t) for t in before + after):
        return None                                          # digits, latin, punctuation
    if b.replace(" ", "").replace("-", "").lower() == a.replace(" ", "").replace("-", "").lower():
        return "join"
    if len(before) == len(after) == 1:
        if before[0][0].isupper() != after[0][0].isupper():
            return None
        if same_lemma(before[0], after[0]):
            return "ending"
        if 1 <= lev(before[0].lower(), after[0].lower()) <= 3:
            return "spelling"
    return None


def units(tag, i1, i2, j1, j2):
    if tag == "replace" and i2 - i1 == j2 - j1:
        return [(i + 0, i + 1, j + 0, j + 1) for i, j in zip(range(i1, i2), range(j1, j2))]
    return [(i1, i2, j1, j2)]


def normalise(src, gold):
    """(src_norm, gold_norm, kinds) or (None, reason)."""
    ts = [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(src)]
    tg = [(m.group(0), m.start(), m.end()) for m in TOKEN.finditer(gold)]
    if not any(t[0][0].isalpha() for t in ts) or sum(1 for t in ts if t[0][0].isalnum()) > MAX_WORDS:
        return None, "no_words_or_too_long"
    ks = [t[0].translate(TRANS) for t in ts]
    kg = [t[0].translate(TRANS) for t in tg]
    sm = difflib.SequenceMatcher(a=ks, b=kg, autojunk=False)
    edits = []        # (src start, src end, gold text, wanted)
    kinds = []
    rewritten = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        for a1, a2, b1, b2 in units(tag, i1, i2, j1, j2):
            before, after = [t[0] for t in ts[a1:a2]], [t[0] for t in tg[b1:b2]]
            kind = classify(before, after)
            if kind is None and a2 - a1 != b2 - b1 and (a2 - a1 > 1 or b2 - b1 > 1) and \
                    any(t.isalpha() for t in before + after):
                n = max(a2 - a1, b2 - b1)
                if n > MAX_REGION_WORDS:
                    return None, "rewrite_too_long"
                rewritten += n
            # span in src and replacement text from gold
            if a1 < a2:
                start, end = ts[a1][1], ts[a2 - 1][2]
                if b1 < b2:
                    repl = gold[tg[b1][1]:tg[b2 - 1][2]]
                else:                                      # deletion: take the gap before the tokens with it
                    if a1 > 0:
                        start = ts[a1 - 1][2]
                    else:
                        end = ts[a2][1] if a2 < len(ts) else len(src)
                    repl = ""
            else:                                          # insertion after src token a1-1
                start = end = ts[a1 - 1][2] if a1 > 0 else 0
                gap_from = tg[b1 - 1][2] if b1 > 0 else 0
                repl = gold[gap_from:tg[b2 - 1][2]]
                if b1 == 0 and a1 == 0 and src[:1].isspace():
                    repl = repl.lstrip()
            edits.append((start, end, repl, kind))
            if kind:
                kinds.append(kind)
    if rewritten > MAX_REWRITTEN:
        return None, "too_much_rewriting"
    if len(kinds) > MAX_EDITS:
        return None, "too_many_edits"
    s, g = src, src
    for start, end, repl, kind in sorted(edits, key=lambda e: -e[0]):
        g = g[:start] + repl + g[end:]
        if not kind:
            s = s[:start] + repl + s[end:]
    clean = lambda x: re.sub(r"\s+", " ", x).strip()     # noqa: E731
    s, g = clean(s), clean(g)
    if kinds and s == g:
        return None, "edits_vanished"
    return (s, g, kinds if s != g else []), None


def read(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def eval_texts(root):
    """Everything that must never be trained on: spike dev/test/official, dev2, test2 (sentences and docs)."""
    sys.path.insert(0, os.path.join(root, "spike"))
    sys.path.insert(0, os.path.join(root, "engine"))
    import bench
    texts, docs = set(), set()
    sets = bench.load_sets()
    for name in ("dev", "test", "official", "public"):
        for item in sets[name]:
            texts.add(item["src"])
            texts.add(item["gold"])
    for name in ("dev2", "test2"):
        for r in read(os.path.join(root, "data-public/converted/%s.jsonl" % name)):
            texts.add(r["src"])
            texts.add(r["gold"])
            docs.add(r["doc"])
    return texts, docs


def words(text):
    return sum(1 for t in TOKEN.findall(text) if t[0].isalnum())


def official_clean(root, n, seed, banned):
    rng = random.Random(seed)
    by_doc = collections.defaultdict(list)
    for r in read(os.path.join(root, "corpus/official-sentences.jsonl")):
        s = r["src"].strip()
        letters = sum(c.isalpha() for c in s)
        cyr = sum("а" <= c.lower() <= "я" or c in "ёЁ" for c in s)
        if 6 <= words(s) <= 45 and 40 <= len(s) <= 380 and cyr >= 0.8 * max(letters, 1) and s not in banned \
                and not any(ord(c) < 32 for c in s):
            by_doc[r["doc"]].append(s)
    docs = sorted(by_doc)
    rng.shuffle(docs)
    picked, left = [], []
    for d in docs:
        rng.shuffle(by_doc[d])
        picked += by_doc[d][:2]
        left += by_doc[d][2:6]
    rng.shuffle(picked)
    if len(picked) < n:
        rng.shuffle(left)
        picked += left[:n - len(picked)]
    return picked[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--root", default="/home/general/vm/win7")
    ap.add_argument("--official", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    banned, banned_docs = eval_texts(a.root)
    stats = collections.defaultdict(collections.Counter)
    rows = {}                       # src_norm -> row; an error row wins over a clean one

    def add(row):
        old = rows.get(row["src"])
        if old is None or (old["src"] == old["gold"] and row["src"] != row["gold"]):
            rows[row["src"]] = row

    sources = [("real", "data-public/converted/train_pub.jsonl"), ("llm", "data-public/llm-errors/llm_pairs.jsonl"),
               ("llm", "data-public/llm-errors/llm_pairs3.jsonl")]
    for pool, rel in sources:
        name = os.path.basename(rel)
        for r in read(os.path.join(a.root, rel)):
            stats[name]["input"] += 1
            if r["src"] in banned or r["gold"] in banned or r.get("doc") in banned_docs:
                stats[name]["eval_overlap"] += 1
                continue
            res, reason = normalise(r["src"], r["gold"])
            if res is None:
                stats[name]["drop_" + reason] += 1
                continue
            s, g, kinds = res
            if s in banned:
                stats[name]["eval_overlap"] += 1
                continue
            stats[name]["err" if kinds else "clean"] += 1
            for k in set(kinds):
                stats[name]["kind_" + k] += 1
            add({"src": s, "gold": g, "pool": pool if kinds else "pair", "kinds": sorted(set(kinds))})
    for rel in ("hard_neg", "del_neg", "add_neg"):
        for r in read(os.path.join(a.root, "data-public/hard-negatives/%s.jsonl" % rel)):
            stats[rel]["input"] += 1
            if r["gold"] in banned:
                stats[rel]["eval_overlap"] += 1
                continue
            stats[rel]["clean"] += 1
            add({"src": r["gold"], "gold": r["gold"], "pool": "hard", "kinds": []})
    for s in official_clean(a.root, a.official, a.seed, banned | set(rows)):
        add({"src": s, "gold": s, "pool": "official", "kinds": []})
        stats["official"]["clean"] += 1
    err = [r for r in rows.values() if r["src"] != r["gold"]]
    clean = [r for r in rows.values() if r["src"] == r["gold"]]
    rng = random.Random(a.seed)
    rng.shuffle(err)
    rng.shuffle(clean)
    for name, data in (("sage_err.jsonl", err), ("sage_clean.jsonl", clean)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"err": len(err), "clean": len(clean), "clean_by_pool": dict(collections.Counter(r["pool"] for r in clean)),
              "err_by_pool": dict(collections.Counter(r["pool"] for r in err)),
              "err_by_kind": dict(collections.Counter(k for r in err for k in r["kinds"])),
              "per_source": {k: dict(v) for k, v in stats.items()}}
    json.dump(summary, open(os.path.join(a.out, "sage_data_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
