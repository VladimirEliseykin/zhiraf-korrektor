"""Offline comparison of ways to use a fine-tuned SAGE in the engine, on cached engine findings.

    python sage_policy_eval.py EVAL_DIR [--engine-findings work/findings-R8b.json] [--sets dev test official]

EVAL_DIR holds out-<set>.jsonl written by sage_eval.py. The engine findings (shipped models, all stages) come from a
train/engine_eval.py run (findings-R8b.json). A variant builds the final findings of each sentence from them and the
SAGE candidates (sage.findings with every class at "check"), merges with checker.merge and scores like engine_eval:
fixed / highlighted / missed of the gold and false marks per 100 sentences (error / check), official clean separately.
No model is loaded here: it is a cheap sweep (seconds), the end-to-end check is engine_eval.py itself.
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage  # noqa: E402  (pins this checkout's engine, reads the gold from the main checkout)
import engine_eval as ee  # noqa: E402
from spellcheck import checker, rules, sage  # noqa: E402
from spellcheck.guards import prepare  # noqa: E402

bench = coverage.bench
ROOT = "/home/general/vm/win7"
ALL_CHECK = {"typo": "check", "join": "check", "comma": "check", "comma_del": "check", "ending": "check"}
KINDS = {"запятая": "comma", "окончание": "ending", "слитно/дефис": "join", "орфография/слово": "spell"}


def edit_keys(src, f):
    g = dict(f, fix=f["fix"] if f.get("fix") is not None else ee.MARK)
    return frozenset(e[:3] for e in bench.edits(src, checker.apply(src, [g], levels=(f["level"],))))


def candidates(src, out_text, lex):
    marker, body = prepare(src)
    out = sage.postprocess(body, out_text)
    found = sage.findings(body, out, lex, levels=ALL_CHECK)
    return [dict(f, start=f["start"] + len(marker), end=f["end"] + len(marker), cls=f["rule"][5:].lower()) for f in found]


def variant_fn(name, **kw):
    """name -> function(src, engine findings, candidates) -> findings."""
    def no_sage(fs):
        return [f for f in fs if not f["rule"].startswith("SAGE_")]

    def fn(src, eng, cands):
        if name == "shipped":
            return eng
        base = no_sage(eng)
        add = [dict(c, level="error") for c in cands if c["cls"] in ("typo", "join")] if kw.get("tj", True) else []
        if kw.get("tj_old"):
            add = [f for f in eng if f["rule"].startswith("SAGE_")]
        keys = {}
        for c in cands:
            keys.setdefault(edit_keys(src, dict(c, level="error")), []).append(c)
        if kw.get("promote"):
            classes = kw["promote"]
            new = []
            for f in base:
                if f["level"] == "check" and f["rule"] in ("MODEL_COMMA", "MODEL_FORM") and \
                        any(c["cls"] in classes for c in keys.get(edit_keys(src, dict(f, level="error")), [])):
                    f = dict(f, level="error", voted=True)
                new.append(f)
            base = new
        only = kw.get("only", {})   # class -> level for SAGE edits that no engine finding touches
        for c in cands:
            lvl = only.get(c["cls"])
            if lvl and not any(checker.overlaps(c, f) for f in base):
                add.append(dict(c, level=lvl))
        if kw.get("confirm_check"):    # SAGE edit equal to an engine check finding is kept as that finding (no change); placeholder
            pass
        return base + add
    return fn


VARIANTS = [
    ("shipped (R8b)", "shipped", {}),
    ("old SAGE typo/join only", "x", {"tj_old": True}),
    ("ft typo/join error", "x", {}),
    ("A: +comma check", "x", {"only": {"comma": "check"}}),
    ("A: +ending check", "x", {"only": {"ending": "check"}}),
    ("A: +comma+ending check", "x", {"only": {"comma": "check", "ending": "check"}}),
    ("A: +comma error", "x", {"only": {"comma": "error"}}),
    ("A: +comma+ending error", "x", {"only": {"comma": "error", "ending": "error"}}),
    ("B: promote comma+ending", "x", {"promote": ("comma", "ending")}),
    ("B: promote comma", "x", {"promote": ("comma",)}),
    ("B: promote ending", "x", {"promote": ("ending",)}),
    ("B: promote comma+del+ending", "x", {"promote": ("comma", "comma_del", "ending")}),
    ("B+: promote + only comma_del check", "x", {"promote": ("comma", "comma_del", "ending"), "only": {"comma_del": "check"}}),
    ("B+: promote + only comma_del error", "x", {"promote": ("comma", "comma_del", "ending"), "only": {"comma_del": "error"}}),
    ("B+: promote + only comma_del+comma check", "x", {"promote": ("comma", "comma_del", "ending"), "only": {"comma_del": "check", "comma": "check"}}),
    ("B+: promote + only comma_del+ending check", "x", {"promote": ("comma", "comma_del", "ending"), "only": {"comma_del": "check", "ending": "check"}}),
]


def score(items, results):
    r = collections.Counter()
    for item in items:
        fs = results[item["src"]]
        sure, check = ee.edits_of(item, fs, "error"), ee.edits_of(item, fs, "check")
        gold = list(bench.edits(item["src"], item["gold"]))
        for g in gold:
            k = KINDS.get(coverage.kind(g), "other")
            r["gold"] += 1
            r["gold_" + k] += 1
            if any(s[:3] == g[:3] for s in sure):
                r["fixed"] += 1
                r["fixed_" + k] += 1
            elif any(coverage.touches(g, s) for s in sure + check):
                r["flagged"] += 1
        ranges = bench.disputed_ranges(item["src"], item["disputed"])
        for f in fs:
            for e in ee.edits_of(item, [f], f["level"]):
                if any(e[:3] == g[:3] for g in gold) or any(coverage.touches(e, g) for g in gold) or \
                        any(e[0] < q[1] and e[1] > q[0] or e[0] == q[0] for q in ranges):
                    continue
                r["false_" + f["level"]] += 1
                r["false_" + f["rule"] + "_" + f["level"]] += 1
    return r


def breakdown(items, eng, cands):
    """SAGE candidates no engine finding overlaps: exact / place / false per class (comma split into add / delete)."""
    r = collections.Counter()
    for item in items:
        src = item["src"]
        gold = list(bench.edits(src, item["gold"]))
        base = [f for f in eng[src] if not f["rule"].startswith("SAGE_")]
        for c in cands[src]:
            if any(checker.overlaps(c, f) for f in base):
                continue
            kind = c["cls"]
            es = edit_keys(src, dict(c, level="error"))
            verdict = "exact" if any(e[:3] in es for e in gold) else "place" if any(coverage.touches(e, g) for e in bench.edits(src, checker.apply(src, [c], levels=("check",))) for g in gold) else "false"
            r[(kind, verdict)] += 1
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir")
    ap.add_argument("--engine-findings", default="/home/general/vm/win7-profiles/work/findings-R8b.json")
    ap.add_argument("--sets", nargs="+", default=["dev", "test", "official"])
    ap.add_argument("--detail", help="print per-rule false counts of the variants whose label contains this")
    a = ap.parse_args()
    sets = bench.load_sets()
    eng = json.load(open(a.engine_findings, encoding="utf-8"))
    lex = rules.Lexicon(None, os.path.join(ROOT, "engine/models/vocab.tsv"))
    cands = {}
    for name in a.sets:
        outs = {json.loads(l)["src"]: json.loads(l)["out"] for l in open(os.path.join(a.eval_dir, "out-%s.jsonl" % name), encoding="utf-8")}
        for item in sets[name]:
            cands[item["src"]] = candidates(item["src"], outs[item["src"]], lex)
    for name in a.sets:
        if name != "official":
            print("SAGE-only candidates", name, sorted(breakdown(sets[name], eng, cands).items()))
        else:
            print("SAGE-only candidates official (all false)", sorted(breakdown(sets[name], eng, cands).items()))
    print("%-40s | %s" % ("variant", "  ".join("%-34s" % s for s in a.sets)))
    for label, mode, kw in VARIANTS:
        fn = variant_fn(mode, **kw)
        cells = []
        for name in a.sets:
            items = sets[name]
            res = {i["src"]: checker.merge(fn(i["src"], eng[i["src"]], cands[i["src"]])) for i in items}
            r, n = score(items, res), len(items)
            if name == "official":
                cells.append("false err %.2f chk %.2f /100" % (100.0 * r["false_error"] / n, 100.0 * r["false_check"] / n))
            else:
                cells.append("fix %2.0f%% flg %2.0f%% fe %.2f fc %.2f c%d/e%d" % (
                    100.0 * r["fixed"] / r["gold"], 100.0 * r["flagged"] / r["gold"], 100.0 * r["false_error"] / n,
                    100.0 * r["false_check"] / n, r["fixed_comma"], r["fixed_ending"]))
            if a.detail and a.detail in label:
                print("   ", name, {k: v for k, v in r.items() if k.startswith("false_") and "_" in k[6:]})
        print("%-40s | %s" % (label, "  ".join("%-34s" % c for c in cells)), flush=True)


if __name__ == "__main__":
    main()
