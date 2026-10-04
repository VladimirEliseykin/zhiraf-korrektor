"""Throwaway spike: syntax comma rules alone and on top of the best SAGE pipeline."""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
import policy  # noqa: E402
from punct_rules import apply, check  # noqa: E402


def main():
    sets = bench.load_sets()
    policy.preload_lexicon([x for s in sets.values() for i in s for x in (i["src"], i["raw"], i["gold"])])
    rupunct = json.load(open(bench.BASE + "rupunct-body-small.json", encoding="utf-8"))
    per_rule = collections.defaultdict(collections.Counter)
    for name in ("dev", "test", "official", "public"):
        items = sets[name]
        rules_out, best_out, both_out = [], [], []
        for item in items:
            edits = check(item["src"])
            rules_out.append(apply(item["src"], edits))
            best = bench.arbiter(item, rupunct.get(item["src"], []), "C")
            best_out.append(best)
            # rule edits are positions in src; re-run them on the SAGE output when its text still matches
            both_out.append(apply(best, check(best)))
            gold = {e[:3] for e in bench.edits(item["src"], item["gold"])}
            for e in edits:
                single = bench.edits(item["src"], apply(item["src"], [e]))
                hit = any(x[:3] in gold for x in single)
                per_rule[e["rule"]][name + ("_tp" if hit else "_fp")] += 1
        for label, outs in (("правила запятых", rules_out), ("лучшая связка", best_out), ("связка + правила", both_out)):
            c = bench.score(items, outs)
            print("%-9s %-18s запятые TP=%3d FP=%3d FN=%3d | остальное TP=%3d FP=%3d" % (
                name, label, c["comma_tp"], c["comma_fp"], c["comma_fn"], c["other_tp"], c["other_fp"]))
    print()
    for rule, c in per_rule.items():
        print("%-22s %s" % (rule, dict(c)))


if __name__ == "__main__":
    main()
