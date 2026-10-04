"""Score the product engine (spellcheck.checker) on the real gold and on clean official text.

Usage: python engine_eval.py <models_dir> <out_findings.json> [threads]
Prints the report twice: without the "spell" stage (baseline) and with it (the findings file has the latter).
This is the number that matters: the exact code path the program runs. Documents are checked whole
(context = all their sentences), gold sentences are scored by fixed / highlighted / missed errors.
"""
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage  # noqa: E402
from spellcheck import checker  # noqa: E402  (path added by coverage -> tagger_eval -> rules)

bench = coverage.bench
SPIKE = os.path.dirname(bench.__file__)
MARK = "█"


def documents():
    by_doc = collections.defaultdict(list)
    for name in ("doc-results-guarded.jsonl", "official-sentences.jsonl"):
        for line in open(os.path.join(SPIKE, name), encoding="utf-8"):
            r = json.loads(line)
            by_doc[r["doc"]].append(r["src"])
    official_doc = {json.loads(l)["src"]: json.loads(l)["doc"]
                    for l in open(os.path.join(SPIKE, "official-results.jsonl"), encoding="utf-8")}
    return by_doc, official_doc


def edits_of(item, findings, level):
    result = []
    for f in findings:
        if f["level"] != level:
            continue
        g = dict(f, fix=f["fix"] if f.get("fix") is not None else MARK)  # "" deletes (a wrong comma)
        result += list(bench.edits(item["src"], checker.apply(item["src"], [g], levels=(level,))))
    return result


def check_both(engine, sentences, context):
    """(merged findings, merged findings without the spell stage) for each sentence, one model pass for both."""
    found = [[] for _ in sentences]
    base = [[] for _ in sentences]
    for stage, i, items in engine.stream(sentences, context):
        found[i].extend(items)
        if stage != "spell":
            base[i].extend(items)
    return [checker.merge(f) for f in found], [checker.merge(f) for f in base]


def main():
    models_dir, out_path = sys.argv[1], sys.argv[2]
    threads = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    print("engine:", checker.__file__, flush=True)
    sets = bench.load_sets()
    by_doc, official_doc = documents()
    engine = checker.Checker(models_dir, threads)
    without = {}  # the same run without the "spell" stage: the baseline for what the spelling head adds
    results = {}
    started = time.perf_counter()
    for set_name in ("real", "official"):
        items = sets["dev"] + sets["test"] if set_name == "real" else sets["official"]
        groups = collections.defaultdict(list)
        for item in items:
            groups[item.get("doc") or official_doc[item["src"]]].append(item)
        for doc, group in groups.items():
            found, base = check_both(engine, [i["src"] for i in group], by_doc.get(doc))
            for item, f, b in zip(group, found, base):
                results[item["src"]] = f
                without[item["src"]] = b
        print("%s checked in %.0f s" % (set_name, time.perf_counter() - started), flush=True)
    json.dump(results, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    for label, res in (("WITHOUT the spell stage (baseline)", without), ("WITH the spell stage", results)):
        print("\n########## %s ##########" % label)
        report(res, sets)
    for stage, s in engine.stats.items():
        print("stage %s: %s" % (stage, s))


def report(results, sets):
    for set_name, items in (("реальные %d" % (len(sets["dev"]) + len(sets["test"])), sets["dev"] + sets["test"]),
                            ("офиц. чистые %d" % len(sets["official"]), sets["official"])):
        fixed = flagged = total = sure_false = check_false = 0
        by_kind = collections.defaultdict(lambda: [0, 0, 0])
        per_rule = collections.defaultdict(collections.Counter)
        for item in items:
            f = results[item["src"]]
            sure, check = edits_of(item, f, "error"), edits_of(item, f, "check")
            gold = list(bench.edits(item["src"], item["gold"]))
            total += len(gold)
            for g in gold:
                row = by_kind[coverage.kind(g)]
                row[2] += 1
                if any(s[:3] == g[:3] for s in sure):
                    fixed += 1
                    row[0] += 1
                elif any(coverage.touches(g, s) for s in sure + check):
                    flagged += 1
                    row[1] += 1
            ranges = bench.disputed_ranges(item["src"], item["disputed"])
            for finding in f:
                es = edits_of(item, [finding], finding["level"])
                for e in es:
                    if any(e[:3] == g[:3] for g in gold):
                        verdict = "exact"
                    elif any(coverage.touches(e, g) for g in gold):
                        verdict = "place"
                    elif any(e[0] < r[1] and e[1] > r[0] or e[0] == r[0] for r in ranges):
                        verdict = "disputed"
                    else:
                        verdict = "false"
                        if finding["level"] == "error":
                            sure_false += 1
                        else:
                            check_false += 1
                    per_rule[(finding["rule"], finding["level"])][verdict] += 1
        n = len(items)
        print("\n=== %s ===" % set_name)
        if total:
            print("исправлено %.0f%%, подсвечено %.0f%%, не найдено %.0f%%" % (
                100.0 * fixed / total, 100.0 * flagged / total, 100.0 * (total - fixed - flagged) / total))
        print("ложных на 100 предложений: «ошибка» %.1f, «проверьте» %.1f" % (100.0 * sure_false / n, 100.0 * check_false / n))
        print("правило / уровень: точно, место, ложно")
        for (rule, level), c in sorted(per_rule.items(), key=lambda x: -sum(x[1].values())):
            print("  %-22s %-6s %4d %4d %4d" % (rule, level, c["exact"], c["place"], c["false"]))
        if total:
            print("по типам: исправлено / подсвечено / всего")
            for k, (fx, fl, tot) in sorted(by_kind.items(), key=lambda x: -x[1][2]):
                print("  %-20s %3d / %3d / %3d" % (k, fx, fl, tot))


if __name__ == "__main__":
    main()
