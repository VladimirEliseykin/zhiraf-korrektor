"""Throwaway spike: evaluate LanguageTool rules (per rule) and LT + SAGE pipeline."""
import collections
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
import policy  # noqa: E402

BASE = bench.BASE
LT_URL = "http://localhost:8081/v2/check"


def lt_check(text):
    data = urllib.parse.urlencode({"language": "ru-RU", "text": text}).encode()
    reply = json.load(urllib.request.urlopen(LT_URL, data=data, timeout=60))
    return [{"offset": m["offset"], "length": m["length"], "rule": m["rule"]["id"],
             "category": m["rule"]["category"]["id"], "message": m["message"],
             "replacement": m["replacements"][0]["value"] if m["replacements"] else None}
            for m in reply["matches"]]


def apply_matches(text, matches):
    out, last = [], 0
    for m in sorted(matches, key=lambda m: m["offset"]):
        if m["replacement"] is None or m["offset"] < last:
            continue
        out.append(text[last:m["offset"]])
        out.append(m["replacement"])
        last = m["offset"] + m["length"]
    out.append(text[last:])
    return "".join(out)


def per_rule(items, results):
    stats = collections.defaultdict(collections.Counter)
    for item in items:
        gold = {e[:3] for e in bench.edits(item["src"], item["gold"])}
        for m in results[item["src"]]:
            if m["replacement"] is None:
                stats[m["rule"]]["no_fix"] += 1
                continue
            system = bench.edits(item["src"], apply_matches(item["src"], [m]))
            if not system:
                continue
            hit = any(e[:3] in gold for e in system)
            stats[m["rule"]]["tp" if hit else "fp"] += 1
    return stats


def main():
    sets = bench.load_sets()
    cache_path = BASE + "lt-6.6.json"
    results = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    for name in ("dev", "test", "official", "public"):
        for item in sets[name]:
            if item["src"] not in results:
                results[item["src"]] = lt_check(item["src"])
    json.dump(results, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)

    for name in ("dev", "official", "test", "public"):
        stats = per_rule(sets[name], results)
        print("\n=== %s: срабатывания по правилам (tp/fp) ===" % name)
        for rule, c in sorted(stats.items(), key=lambda x: -(x[1]["tp"] + x[1]["fp"])):
            print("  %-45s tp=%3d fp=%3d" % (rule, c["tp"], c["fp"]))


if __name__ == "__main__":
    main()
