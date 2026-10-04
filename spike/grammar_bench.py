"""Throwaway spike: detection quality of grammar checkers on real gold, synthetic and clean sets.

Phase 1 (compute): run every checker on every sentence and cache raw findings.
Phase 2 (report): score detection for a range of form-scorer thresholds.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.abspath(__file__)) + "/"
CACHE = BASE + "grammar-cache.json"


def load_sets():
    sets = {"gold-dev": [], "gold-test": []}
    for n in range(1, 5):
        annot = json.load(open(BASE + "gold-annot-%d.json" % n, encoding="utf-8"))
        verify = json.load(open(BASE + "gold-verify-%d.json" % n, encoding="utf-8"))
        for a, v in zip(annot, verify):
            spans, grammar = [], []
            for e in a["errors"]:
                k = a["sentence"].find(e["fragment"])
                if k >= 0:
                    spans.append((k, k + len(e["fragment"])))
                    if e["type"] == "грамматика":
                        grammar.append((k, k + len(e["fragment"])))
            disputed = []
            for m in v.get("missed", []):
                k = a["sentence"].find(m["fragment"])
                if k >= 0:
                    disputed.append((k, k + len(m["fragment"])))
            split = "gold-dev" if a["id"].startswith("dev") else "gold-test"
            sets[split].append({"src": a["sentence"], "spans": spans, "grammar": grammar, "disputed": disputed})
    for name in ("synth-dev", "synth-test"):
        sets[name] = [{"src": x["src"], "spans": [(x["start"], x["start"] + len(x["bad_word"]))],
                       "grammar": [(x["start"], x["start"] + len(x["bad_word"]))], "disputed": []}
                      for x in json.load(open(BASE + name + ".json", encoding="utf-8"))]
    sets["official"] = [{"src": json.loads(line)["src"], "spans": [], "grammar": [], "disputed": []}
                        for line in open(BASE + "official-sentences.jsonl", encoding="utf-8")]
    return sets


def compute(sets):
    from form_scorer import FormScorer
    from grammar_rules import check as adj_prep_check
    from syntax_rules import check as subj_verb_check
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    scorer = FormScorer("/home/general/vm/win7/models/rubert-tiny2")
    done = 0
    for items in sets.values():
        for item in items:
            src = item["src"]
            if src in cache:
                continue
            cache[src] = {
                "adj_prep": [(f["start"], f["end"], f["rule"]) for f in adj_prep_check(src)],
                "subj_verb": [(f["start"], f["end"], f["rule"]) for f in subj_verb_check(src)],
                "forms": [list(x) for x in scorer.score_sentence(src)],
            }
            done += 1
            if done % 200 == 0:
                json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
                print("computed", done, flush=True)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)


def findings(entry, methods, threshold):
    spans = []
    if "adj_prep" in methods:
        spans += [(s, e) for s, e, _ in entry["adj_prep"]]
    if "subj_verb" in methods:
        spans += [(s, e) for s, e, _ in entry["subj_verb"]]
    if "forms" in methods:
        spans += [(s, e) for s, e, _, _, gain in entry["forms"] if gain >= threshold]
    return spans


def overlaps(span, ranges):
    return any(span[0] < r[1] and span[1] > r[0] for r in ranges)


def report(sets):
    cache = json.load(open(CACHE, encoding="utf-8"))
    configs = [("правила: предлог+согласование", ("adj_prep",), None),
               ("правило: подлежащее-сказуемое", ("subj_verb",), None)]
    for t in (3, 4, 5, 6, 8):
        configs.append(("оценщик форм, порог %d" % t, ("forms",), t))
    for t in (4, 5, 6):
        configs.append(("все три, порог %d" % t, ("adj_prep", "subj_verb", "forms"), t))
    print("%-34s | %-22s | %-22s | %-12s" % ("метод", "реальные dev+test", "искусств. dev+test", "официальные"))
    print("%-34s | %-22s | %-22s | %-12s" % ("", "найдено грам./ложных", "найдено / ложных", "ложных/100"))
    for name, methods, t in configs:
        row = []
        for group in (("gold-dev", "gold-test"), ("synth-dev", "synth-test")):
            found = total = fp = 0
            for g in group:
                for item in sets[g]:
                    spans = findings(cache[item["src"]], methods, t)
                    for gr in item["grammar"]:
                        total += 1
                        found += any(overlaps(s, [gr]) for s in spans)
                    fp += sum(1 for s in spans if not overlaps(s, item["spans"]) and not overlaps(s, item["disputed"]))
            row.append("%3d/%-3d  ложных %3d" % (found, total, fp))
        done = [i for i in sets["official"] if i["src"] in cache]  # partial while compute is running
        off = sum(len(findings(cache[i["src"]], methods, t)) for i in done)
        row.append("%5.1f (%d)" % (100.0 * off / max(1, len(done)), len(done)))
        print("%-34s | %-22s | %-22s | %-12s" % (name, row[0], row[1], row[2]))


if __name__ == "__main__":
    data = load_sets()
    if sys.argv[1:] == ["compute"]:
        compute(data)
    else:
        report(data)
