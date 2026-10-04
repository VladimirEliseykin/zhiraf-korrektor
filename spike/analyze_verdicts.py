"""Throwaway spike: aggregate reviewer verdicts by edit kind."""
import collections
import json
import sys

sys.path.insert(0, "/home/general/vm/win7/spike")
from diff_docs import kind  # noqa: E402

base = "/home/general/vm/win7/spike/"
by_kind = collections.defaultdict(collections.Counter)
comma = collections.defaultdict(collections.Counter)
total = collections.Counter()
for n in range(1, 5):
    for v in json.load(open(base + "verdicts-changed-%d.json" % n, encoding="utf-8")):
        before, after = v.get("было", ""), v.get("стало", "")
        k = kind(before, after)
        by_kind[k][v["verdict"]] += 1
        total[v["verdict"]] += 1
        if k == "запятая":
            comma["добавить" if not before else "убрать"][v["verdict"]] += 1

print("ВСЕГО", dict(total))
print("%-26s %5s %5s %5s  %s" % ("тип", "fix", "harm", "neutr", "точность fix/(fix+harm)"))
for k, c in sorted(by_kind.items(), key=lambda x: -sum(x[1].values())):
    precision = c["fix"] / max(1, c["fix"] + c["harm"])
    print("%-26s %5d %5d %5d  %.0f%%" % (k, c["fix"], c["harm"], c["neutral"], 100 * precision))
for k, c in comma.items():
    precision = c["fix"] / max(1, c["fix"] + c["harm"])
    print("  запятая: %-10s %5d %5d %5d  %.0f%%" % (k, c["fix"], c["harm"], c["neutral"], 100 * precision))

missed = collections.Counter()
for n in (1, 2):
    for v in json.load(open(base + "verdicts-unchanged-%d.json" % n, encoding="utf-8")):
        for e in v["errors"]:
            missed[e["type"]] += 1
print("ПРОПУЩЕНО в 150 нетронутых:", sum(missed.values()), dict(missed))
