"""Comma vote with a widened tagger band: a SAGE comma edit becomes an ERROR when the three comma taggers give the same
edit a combined score >= lo (below the shipped "check" threshold min >= 0.5 as well). Tagger candidates SAGE does not
reproduce stay as shipped (the widened band shows nothing on its own).

    python sage_comma_band.py EVAL_DIR [--sets dev test official]

Sweeps the lower bound and the combiner (min / mean / max over the members) separately for added and deleted commas,
from the cached member predictions (runs/<member>/bench-preds*.json), the shipped engine findings of the
non-SAGE stages and the SAGE outputs of EVAL_DIR (sage_eval.py). Scoring as in sage_policy_eval.py.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sage_policy_eval as P  # noqa: E402
from sage_policy_eval import bench, checker, rules, sage, score  # noqa: E402
from spellcheck.guards import prepare  # noqa: E402
from spellcheck.text import words_of  # noqa: E402

COMMA_RUNS = ["gpu-ft8-gpu-ft5-r6-commas", "gpu-ft8-gpu-ft-r3-commas", "gpu-ft8-large-commas-e0"]
COMBINE = {"min": min, "mean": lambda xs: sum(xs) / len(xs), "max": max}


def load_cache(run):
    cache = {}
    for f in ("bench-preds.json", "bench-preds2.json"):
        p = os.path.join(P.ROOT, "runs", run, f)
        if os.path.exists(p):
            cache.update(json.load(open(p, encoding="utf-8")))
    return cache


def tagger_scores(src, c, caches):
    """{combiner: score} of the tagger members for the SAGE comma edit c (None if the cache does not cover it)."""
    marker, body = prepare(src)
    ms = words_of(body)
    pos = c["start"] - len(marker)
    word = next((i for i, m in enumerate(ms) if m.end() == pos), None)
    if word is None:
        return None
    label = "ADD" if c["cls"] == "comma" else "DEL"
    probs = []
    for cache in caches:
        ent = cache.get(src)
        if not ent or ent[1] != body or word >= len(ent[3]):
            return None
        probs.append(ent[3][word]["comma"][label])
    return {k: f(probs) for k, f in COMBINE.items()}


def build(src, eng, cands, scores, rule):
    """Findings: shipped state (ft typo/join, ending vote) + comma votes. rule = (comb_add, lo_add, comb_del, lo_del) or None."""
    base = P.variant_fn("x", promote=("ending",))(src, eng, cands)
    if rule is None:
        return base
    ca, la, cd, ld = rule
    out = list(base)
    for c in cands:
        if c["cls"] not in ("comma", "comma_del"):
            continue
        s = scores.get(id(c))
        if s is None:
            continue
        comb, lo = (ca, la) if c["cls"] == "comma" else (cd, ld)
        if s[comb] < lo:
            continue
        # replace what the engine has at that place unless it already is an error with the same edit
        same = P.edit_keys(src, dict(c, level="error"))
        clash = [f for f in out if checker.overlaps(c, f)]
        if any(f["level"] == "error" and P.edit_keys(src, f) == same for f in clash):
            continue
        if any(f["level"] == "error" for f in clash):
            continue
        out = [f for f in out if f not in clash] + [dict(c, level="error")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir")
    ap.add_argument("--sets", nargs="+", default=["dev", "test", "official"])
    ap.add_argument("--engine-findings", default="/home/general/vm/win7-profiles/work/findings-R8b.json")
    a = ap.parse_args()
    sets = bench.load_sets()
    eng = json.load(open(a.engine_findings, encoding="utf-8"))
    lex = rules.Lexicon(None, os.path.join(P.ROOT, "engine/models/vocab.tsv"))
    caches = [load_cache(r) for r in COMMA_RUNS]
    cands, scores = {}, {}
    for name in a.sets:
        outs = {json.loads(l)["src"]: json.loads(l)["out"] for l in open(os.path.join(a.eval_dir, "out-%s.jsonl" % name), encoding="utf-8")}
        for item in sets[name]:
            src = item["src"]
            cands[src] = P.candidates(src, outs[src], lex)
            for c in cands[src]:
                if c["cls"] in ("comma", "comma_del"):
                    scores[id(c)] = tagger_scores(src, c, caches)
    cover = [s for s in scores.values()]
    print("SAGE comma edits %d, covered by the tagger cache %d" % (len(cover), sum(s is not None for s in cover)))
    rules_ = [("shipped state (ending vote)", None)]
    for comb in ("min", "mean", "max"):
        for lo in (0.5, 0.3, 0.2, 0.1, 0.05):
            rules_.append(("ADD+DEL %s >= %.2f" % (comb, lo), (comb, lo, comb, lo)))
    # added and deleted commas separately: "off" (2.0) = never promoted by the widened band
    for comb in ("min", "mean", "max"):
        for lo in (0.7, 0.5, 0.4, 0.3, 0.2, 0.1):
            rules_.append(("ADD off, DEL %s >= %.2f" % (comb, lo), ("min", 2.0, comb, lo)))
            rules_.append(("ADD min >= 0.5, DEL %s >= %.2f" % (comb, lo), ("min", 0.5, comb, lo)))
    for comb in ("min", "mean", "max"):
        for lo in (0.5, 0.3, 0.1):
            rules_.append(("ADD %s >= %.2f, DEL off" % (comb, lo), (comb, lo, "min", 2.0)))
    print("%-34s | %s" % ("rule", "  ".join("%-38s" % s for s in a.sets)))
    for label, rule in rules_:
        cells = []
        for name in a.sets:
            items = sets[name]
            res = {i["src"]: checker.merge(build(i["src"], eng[i["src"]], cands[i["src"]], scores, rule)) for i in items}
            r, n = score(items, res), len(items)
            if name == "official":
                cells.append("false err %.2f chk %.2f" % (100.0 * r["false_error"] / n, 100.0 * r["false_check"] / n))
            else:
                cells.append("fix %2.0f%% flg %2.0f%% fe %.2f fc %.2f c%d/e%d  (comma errors right %d false %d)" % (
                    100.0 * r["fixed"] / r["gold"], 100.0 * r["flagged"] / r["gold"], 100.0 * r["false_error"] / n,
                    100.0 * r["false_check"] / n, r["fixed_comma"], r["fixed_ending"],
                    r.get("sage_right", 0), r.get("sage_false", 0)))
        print("%-34s | %s" % (label, "  ".join("%-38s" % c for c in cells)), flush=True)


if __name__ == "__main__":
    main()
