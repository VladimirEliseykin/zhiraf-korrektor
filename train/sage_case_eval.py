"""SAGE's letter-case edits against the gold: right / false per kind, on dev, test and clean official.

    python sage_case_eval.py EVAL_DIR [--show N]

Kinds: start-up / start-down (first word of the sentence), mid-up / mid-down (inside it, lower -> capital / capital ->
lower), other (all-caps and the like). Also lists the gold case errors, to see what they look like.
"""
import argparse
import collections
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage  # noqa: E402
from spellcheck import checker, sage  # noqa: E402
from spellcheck.guards import TOKEN, prepare  # noqa: E402

bench = coverage.bench


def case_edits(body, out):
    """[(start, end, before, after, kind)] for the single-word case-only edits of the SAGE output."""
    a, b = TOKEN.findall(body), TOKEN.findall(out)
    starts, pos = [], 0
    for t in a:
        starts.append(pos)
        pos += len(t)
    starts.append(pos)
    first_word = next((i for i, t in enumerate(a) if t[:1].isalnum()), 0)
    res = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "replace" or i2 - i1 != 1 or j2 - j1 != 1:
            continue
        x, y = a[i1], b[j1]
        if x == y or x.lower() != y.lower() or not x[:1].isalpha():
            continue
        if x[:1].islower() and y[:1].isupper() and x[1:] == y[1:]:
            d = "up"
        elif x[:1].isupper() and y[:1].islower() and x[1:] == y[1:]:
            d = "down"
        else:
            d = "other"
        res.append((starts[i1], starts[i2], x, y, ("start-" if i1 == first_word else "mid-") + d if d != "other" else "other"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir")
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    sets = bench.load_sets()
    stats = collections.defaultdict(collections.Counter)
    gold_cases = []
    for name in ("dev", "test", "official"):
        outs = {json.loads(l)["src"]: json.loads(l)["out"] for l in open(os.path.join(a.eval_dir, "out-%s.jsonl" % name), encoding="utf-8")}
        for item in sets[name]:
            src = item["src"]
            marker, body = prepare(src)
            out = sage.postprocess(body, outs[src])
            gold = list(bench.edits(src, item["gold"]))
            gk = {g[:3] for g in gold}
            for g in gold:
                if coverage.kind(g) == "регистр":
                    gold_cases.append((name, src, g))
            for s, e, x, y, kind in case_edits(body, out):
                s, e = s + len(marker), e + len(marker)
                keys = {k[:3] for k in bench.edits(src, src[:s] + y + src[e:])}
                ok = keys <= gk and bool(keys)
                stats[(name if name == "official" else "dev+test", kind)]["right" if ok else "false"] += 1
                if a.show and not ok and name != "official" and stats[(name, kind)]["shown"] < a.show:
                    stats[(name, kind)]["shown"] += 1
                    print("FALSE", name, kind, repr(src[max(0, s - 30):e + 20]), "->", y)
    for k in sorted(stats):
        print("%-10s %-12s right %3d false %3d" % (k[0], k[1], stats[k]["right"], stats[k]["false"]))
    print("gold case errors (dev+test):")
    for name, src, g in gold_cases:
        print("  ", name, g[3], "->", g[2], "|", src[:90])


if __name__ == "__main__":
    main()
