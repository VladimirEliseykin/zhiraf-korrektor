"""Evaluate an edit-tagger run on the spike benchmarks (real gold, official clean, public, synthetic).

Usage: python tagger_eval.py <run_dir> [epoch]
Applies predictions above confidence thresholds, with the same protective guards
as the SAGE pipeline (list markers, digits, latin, abbreviations), and scores
comma and word-form edits.
"""
import json
import os
import re
import sys

SPIKE = "/home/general/vm/win7/spike"
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
from corrupt import inflect, words_of  # noqa: E402
from guards import prepare  # noqa: E402
from tagger import EditTagger  # noqa: E402
import grammar_rules  # noqa: E402

PROTECTED = re.compile(r".*[0-9A-Za-z].*")


def protected(word):
    upper = sum(c.isupper() for c in word)
    return bool(PROTECTED.match(word)) or upper >= 2


BIBLIOGRAPHY = re.compile(r"\[(Электронный ресурс|Текст)\]|//|\s/\s[А-ЯЁA-Z]|–\s*С\.\s*\d|—\s*С\.\s*\d|\bURL:|\bISBN\b|–\s*\d+\s*с\.")
QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")


def quoted_spans(text):
    return [m.span() for m in QUOTED.finditer(text)]


GUARDS = {"grammar_veto": True, "capital_mid": True}


def breaks_grammar(text, start, end, new):
    """True when replacing text[start:end] with new creates a preposition-case or agreement
    violation touching that word which the original text did not have ("за утечки" -> "за утечка")."""
    def touching(t, e):
        return sum(1 for f in grammar_rules.check(t) if f["start"] < e and f["end"] > start)
    return touching(text[:start] + new + text[end:], start + len(new)) > touching(text, end)


def apply_predictions(text, preds, t_add, t_del, t_form):
    # bibliographic entries follow GOST 7.1 formatting, not ordinary punctuation and agreement
    if BIBLIOGRAPHY.search(text):
        return text
    quotes = quoted_spans(text)  # titles and names in quotes are never edited
    ms = words_of(text)
    out, last = [], 0
    for i, m in enumerate(ms):
        out.append(text[last:m.start()])
        word = m.group(0)
        p = preds[i] if i < len(preds) else None
        in_quotes = any(a < m.start() < b for a, b in quotes)
        # a capitalised word inside a sentence is a name or a title ("(Врачи)", "Положением")
        capital_mid = GUARDS["capital_mid"] and i > 0 and word[:1].isupper()
        if p and p["form"] != "KEEP" and p["form_p"] >= t_form and not protected(word) and not in_quotes \
                and not capital_mid:
            new = inflect(word, p["form"]) or word
            if new != word and GUARDS["grammar_veto"] and breaks_grammar(text, m.start(), m.end(), new):
                new = word
            word = new
        out.append(word)
        last = m.end()
        if p is None or in_quotes or protected(m.group(0)) and not m.group(0).isalpha():
            continue
        has = text[last:last + 1] == ","
        nxt = text[last:last + 2]
        if not has and p["comma"]["ADD"] >= t_add and nxt[:1] == " " and i < len(ms) - 1:
            out.append(",")
        elif has and p["comma"]["DEL"] >= t_del:
            last += 1
    out.append(text[last:])
    return "".join(out)


def run(tagger, items, cache):
    for item in items:
        if item["src"] not in cache:
            marker, body = prepare(item["src"])
            cache[item["src"]] = (marker, body, tagger.predict(body))
    return cache


def corrected(cache, src, t_add, t_del, t_form):
    marker, body, preds = cache[src]
    return marker + apply_predictions(body, preds, t_add, t_del, t_form)


def detection(items, outs):
    """Location-level score: a system edit counts if it touches a gold edit, whatever replacement it proposes."""
    tp = fp = found = total = 0
    for item, out in zip(items, outs):
        gold = [e for e in bench.edits(item["src"], item["gold"])]
        system = [e for e in bench.edits(item["src"], out)]

        def touches(a, b):
            return a[0] <= b[1] and b[0] <= a[1]
        total += len(gold)
        found += sum(1 for g in gold if any(touches(g, s) for s in system))
        for s in system:
            if any(touches(s, g) for g in gold):
                tp += 1
            else:
                fp += 1
    return found, total, fp


def main():
    run_dir = sys.argv[1]
    epoch = int(sys.argv[2]) if len(sys.argv) > 2 else None
    tagger = EditTagger(run_dir, epoch)
    sets = bench.load_sets()
    synth = {}
    for name in ("synth-dev", "synth-test"):
        synth[name] = [{"src": x["src"], "gold": x["gold"], "disputed": []}
                       for x in json.load(open(os.path.join(SPIKE, name + ".json"), encoding="utf-8"))]
    cache = {}
    for items in list(sets.values()) + list(synth.values()):
        run(tagger, items, cache)
    grid = [(0.5, 0.5, 0.5), (0.7, 0.7, 0.7), (0.8, 0.9, 0.8), (0.9, 0.95, 0.9), (0.95, 0.98, 0.95)]
    print("%-20s %-10s %24s | %24s" % ("пороги add/del/form", "набор", "запятые TP/FP/FN", "формы TP/FP/FN"))
    for t in grid:
        for name, items in (("dev", sets["dev"]), ("test", sets["test"]), ("official", sets["official"]),
                            ("public", sets["public"]), ("synth-dev", synth["synth-dev"]), ("synth-test", synth["synth-test"])):
            outs = [corrected(cache, i["src"], *t) for i in items]
            c = bench.score(items, outs)
            found, total, dfp = detection(items, outs)
            print("%-20s %-10s %8d %6d %6d | %8d %6d %6d | обнаружено %3d/%-3d ложных %3d" % (
                "%.2f/%.2f/%.2f" % t, name, c["comma_tp"], c["comma_fp"], c["comma_fn"],
                c["other_tp"], c["other_fp"], c["other_fn"], found, total, dfp))
        print()


if __name__ == "__main__":
    main()
