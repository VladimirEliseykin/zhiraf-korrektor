"""Two-level coverage: how much of the real errors a reader gets either fixed ("ошибка") or at least
highlighted ("проверьте"), and how many false marks of each level they have to dismiss.

Usage: python coverage.py <comma_run> <form_run>
Level "ошибка": the exact edit at high thresholds. Level "проверьте": any edit at low thresholds,
counted by location only, because the reader looks at the highlighted place and decides.
False marks are per 100 sentences, on the real gold and on clean official text.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

bench = ts.te.bench
# (comma threshold, form threshold) for the sure level and a ladder of check levels
SURE = (0.9, 0.9)
CHECK = ((0.7, 0.7), (0.5, 0.5), (0.3, 0.3), (0.15, 0.15))


def merged(cache_c, cache_f, src):
    """Comma probabilities from one run, word forms from another."""
    marker, body, words_text, pc = cache_c[src]
    _, _, _, pf = cache_f[src]
    preds = [{"comma": c["comma"], "form": f["form"], "form_p": f["form_p"], "form_keep_p": f["form_keep_p"]}
             for c, f in zip(pc, pf)]
    return marker, body, preds


def output(cache_c, cache_f, item, tc, tf):
    marker, body, preds = merged(cache_c, cache_f, item["src"])
    return marker + ts.te.apply_predictions(body, preds, tc, max(tc, 0.9) if tc >= 0.9 else 1.1, tf)


def touches(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def kind(edit):
    """Rough type of a gold edit, to see which kinds of errors stay unfound."""
    _, _, after, before = edit
    if bench.is_comma(edit):
        return "запятая"
    a, b = " ".join(before), " ".join(after)
    if a.lower() == b.lower():
        return "регистр"
    if a.replace(" ", "").replace("-", "") == b.replace(" ", "").replace("-", ""):
        return "слитно/дефис"
    if not any(ch.isalpha() for ch in a + b):
        return "другая пунктуация"
    if len(before) == len(after) == 1 and ts.te.grammar_rules.morph.parse(a)[0].normal_form == \
            ts.te.grammar_rules.morph.parse(b)[0].normal_form:
        return "окончание"
    if len(before) == len(after) == 1:
        return "орфография/слово"
    return "несколько слов"


BY_KIND = {}


def evaluate(items, cache_c, cache_f, check):
    fixed = flagged = total = sure_false = check_false = 0
    for item in items:
        gold = list(bench.edits(item["src"], item["gold"]))
        ranges = bench.disputed_ranges(item["src"], item["disputed"])
        sure = list(bench.edits(item["src"], output(cache_c, cache_f, item, *SURE)))
        low = list(bench.edits(item["src"], output(cache_c, cache_f, item, *check)))
        gold_keys = {g[:3] for g in gold}
        total += len(gold)
        for g in gold:
            row = BY_KIND.setdefault(kind(g), [0, 0, 0])
            row[2] += 1
            if any(s[:3] == g[:3] for s in sure):
                fixed += 1
                row[0] += 1
            elif any(touches(g, s) for s in sure + low):
                flagged += 1
                row[1] += 1

        def disputed(e):
            return any(e[0] < r[1] and e[1] > r[0] or e[0] == r[0] for r in ranges)
        sure_false += sum(1 for s in sure if s[:3] not in gold_keys and not disputed(s))
        check_false += sum(1 for s in low if not any(touches(s, g) for g in gold) and not disputed(s)
                           and not any(s[:3] == x[:3] for x in sure))
    return fixed, flagged, total, sure_false, check_false


def main():
    sets = bench.load_sets()
    real = sets["dev"] + sets["test"]
    tech = [i for i in real if bench.is_tech(i["doc"])]
    cache_c = ts.predictions(sys.argv[1], sets)
    cache_f = ts.predictions(sys.argv[2], sets)
    print("«ошибка»: запятые ≥%.2f, формы ≥%.2f; «проверьте» — пороги ниже, засчитывается место" % SURE)
    for label, items in (("все %d реальных" % len(real), real), ("служебно-технические %d" % len(tech), tech)):
        print("\n=== %s ===" % label)
        print("проверьте от | исправлено  подсвечено  не найдено | ложных на 100 предл.: «ошибка» «проверьте» | офиц. чистые: «ошибка» «проверьте»")
        for check in CHECK:
            fx, fl, tot, sf, cf = evaluate(items, cache_c, cache_f, check)
            _, _, _, osf, ocf = evaluate(sets["official"], cache_c, cache_f, check)
            n, no = len(items), len(sets["official"])
            print("  %.2f/%.2f  | %4.0f%%       %4.0f%%       %4.0f%%     | %10.1f %10.1f          | %10.1f %10.1f" % (
                check[0], check[1], 100.0 * fx / tot, 100.0 * fl / tot, 100.0 * (tot - fx - fl) / tot,
                100.0 * sf / n, 100.0 * cf / n, 100.0 * osf / no, 100.0 * ocf / no))
    BY_KIND.clear()
    evaluate(real, cache_c, cache_f, (0.3, 0.3))
    print("\nпо типам ошибок (все реальные, «проверьте» от 0.30): исправлено / подсвечено / всего")
    for k, (fx, fl, tot) in sorted(BY_KIND.items(), key=lambda x: -x[1][2]):
        print("  %-20s %3d / %3d / %3d   не найдено %3.0f%%" % (k, fx, fl, tot, 100.0 * (tot - fx - fl) / tot))


if __name__ == "__main__":
    main()
