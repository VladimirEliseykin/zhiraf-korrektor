"""Score each rule of rules.py, SAGE typo/join fixes and the tagger, alone and combined.

Usage: python rules_eval.py <comma_run> <form_run>
Per rule: exact fixes, right places, false marks (real gold and clean official text).
Combined: share of real errors fixed / highlighted / missed, with false marks per 100 sentences.
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage  # noqa: E402
import rules  # noqa: E402

ts = coverage.ts
bench = coverage.bench
policy = ts.policy
MARK = "█"
DEBUG = set(os.environ.get("RULE_DEBUG", "").split(","))


SPIKE = os.path.dirname(bench.__file__)
VOCAB = "/home/general/vm/win7/corpus/vocab.tsv"


def doc_contexts(lexicon):
    """DocContext per document, built from all its sentences (as the program sees a whole file)."""
    by_doc = collections.defaultdict(list)
    for name in ("doc-results-guarded.jsonl", "official-sentences.jsonl"):
        for line in open(os.path.join(SPIKE, name), encoding="utf-8"):
            r = json.loads(line)
            by_doc[r["doc"]].append(r["src"])
    official_doc = {json.loads(l)["src"]: json.loads(l)["doc"] for l in open(os.path.join(SPIKE, "official-results.jsonl"),
                                                                          encoding="utf-8")}
    return {doc: rules.DocContext(sents, lexicon) for doc, sents in by_doc.items()}, official_doc


def single(item, body, marker, f):
    fixed = body[:f["start"]] + (f["fix"] if f["fix"] else MARK) + body[f["end"]:]
    return list(bench.edits(item["src"], marker + fixed))


def classify(item, system):
    gold = list(bench.edits(item["src"], item["gold"]))
    ranges = bench.disputed_ranges(item["src"], item["disputed"])
    result = []
    for s in system:
        if any(s[:3] == g[:3] for g in gold):
            result.append("exact")
        elif any(coverage.touches(s, g) for g in gold):
            result.append("place")
        elif any(s[0] < r[1] and s[1] > r[0] or s[0] == r[0] for r in ranges):
            result.append("disputed")
        else:
            result.append("false")
    return result


def main():
    sets = bench.load_sets()
    real = sets["dev"] + sets["test"]
    texts = [x for s in sets.values() for i in s for x in (i["src"], i["raw"], i["gold"])]
    texts += [json.loads(l)["src"] for l in open(os.path.join(os.path.dirname(bench.__file__),
                                                             "doc-results-guarded.jsonl"), encoding="utf-8")]
    texts += [json.loads(l)["src"] for l in open(os.path.join(SPIKE, "official-sentences.jsonl"), encoding="utf-8")]
    policy.preload_lexicon(texts)
    lexicon = rules.Lexicon(policy._unknown, VOCAB)
    contexts, official_doc = doc_contexts(lexicon)
    cache_c = ts.predictions(sys.argv[1], sets)
    cache_f = ts.predictions(sys.argv[2], sets)

    per_rule = collections.defaultdict(collections.Counter)
    components = {}  # (set, src) -> {"sure": [...edits], "check": [...edits]}
    for set_name, items in (("real", real), ("official", sets["official"])):
        for item in items:
            marker, body = ts.te.prepare(item["src"])
            doc = item.get("doc") or official_doc.get(item["src"])
            found = rules.check(body, lexicon, contexts.get(doc))
            sure, check = [], []
            for f in found:
                edits = single(item, body, marker, f)
                for verdict in classify(item, edits):
                    per_rule[(f["rule"], f["level"])][set_name + ":" + verdict] += 1
                    if verdict == "false" and f["rule"] in DEBUG:
                        print("ЛОЖНО %s [%s] %s | %s" % (f["rule"], set_name, body[f["start"]:f["end"]], body[:140]))
                if f["level"] == "error":
                    sure.extend(edits)
                elif f["level"] == "check":
                    check.extend(edits)  # "strict" rules are off by default
            # SAGE dictionary-confirmed typo / join fixes
            sage = list(bench.edits(item["src"], marker + cache_c[item["src"]][2]))
            for verdict in classify(item, sage):
                per_rule[("SAGE_TYPO_JOIN", "error")][set_name + ":" + verdict] += 1
            components[(set_name, item["src"])] = {"rules_sure": sure, "rules_check": check, "sage": sage}

    print("правило                     уровень   | реальные 3100: точно  место  ложно | офиц. 1563: ложно")
    for (rule, level), c in sorted(per_rule.items(), key=lambda x: -(x[1]["real:exact"] + x[1]["real:place"])):
        print("%-27s %-9s |              %4d  %5d  %5d |            %5d" % (
            rule, level, c["real:exact"], c["real:place"], c["real:false"], c["official:false"]))

    def combined(items, set_name, use):
        fixed = flagged = total = sure_false = check_false = 0
        by_kind = collections.defaultdict(lambda: [0, 0, 0])
        for item in items:
            comp = components[(set_name, item["src"])]
            sure = list(bench.edits(item["src"], coverage.output(cache_c, cache_f, item, *coverage.SURE)))
            check = list(bench.edits(item["src"], coverage.output(cache_c, cache_f, item, 0.3, 0.3)))
            if "rules" in use:
                sure += comp["rules_sure"]
                check += comp["rules_check"]
            if "sage" in use:
                sure += comp["sage"]
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
            v_sure = classify(item, sure)
            v_check = classify(item, [c for c in check if not any(c[:3] == s[:3] for s in sure)])
            sure_false += v_sure.count("false")
            check_false += v_check.count("false")
        return fixed, flagged, total, sure_false, check_false, by_kind

    print("\nсостав                       | исправлено подсвечено не найдено | ложных/100: «ошибка» «проверьте» | офиц./100: «ошибка» «проверьте»")
    for label, use in (("модель", ()), ("модель + SAGE", ("sage",)), ("модель + SAGE + правила", ("sage", "rules"))):
        fx, fl, tot, sf, cf, by_kind = combined(real, "real", use)
        _, _, _, osf, ocf, _ = combined(sets["official"], "official", use)
        n, no = len(real), len(sets["official"])
        print("%-28s |   %4.0f%%    %4.0f%%     %4.0f%%   |        %5.1f     %5.1f    |        %5.1f     %5.1f" % (
            label, 100.0 * fx / tot, 100.0 * fl / tot, 100.0 * (tot - fx - fl) / tot,
            100.0 * sf / n, 100.0 * cf / n, 100.0 * osf / no, 100.0 * ocf / no))
    print("\nпо типам (модель + SAGE + правила): исправлено / подсвечено / всего")
    for k, (fx, fl, tot) in sorted(by_kind.items(), key=lambda x: -x[1][2]):
        print("  %-20s %3d / %3d / %3d   не найдено %3.0f%%" % (k, fx, fl, tot, 100.0 * (tot - fx - fl) / tot))


if __name__ == "__main__":
    main()
