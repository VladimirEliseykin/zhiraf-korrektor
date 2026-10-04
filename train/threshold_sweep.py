"""Pick separate thresholds for comma-add, comma-delete and word-form actions.

Usage: python threshold_sweep.py <run_dir>
Predictions are computed once and cached next to the run. Thresholds are chosen on
dev under a false-alarm budget on clean official text, then reported on test.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_eval  # noqa: E402,F401  (registers the typo_join policy)
import tagger_eval as te  # noqa: E402
import policy  # noqa: E402

ADD = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99)
DEL = (0.7, 0.9, 0.95, 0.98, 0.995, 1.1)
FORM = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 1.1)
OFFICIAL_BUDGET = 1.0  # max false alarms per 100 clean official sentences


def predictions(run_dir, sets):
    path = os.path.join(run_dir, "bench-preds.json")
    cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    missing = [i for name in ("dev", "test", "official", "public") for i in sets[name] if i["src"] not in cache]
    if not missing:
        return cache
    # the gold set grows over time: predict only the sentences the cache does not have yet
    tagger = te.EditTagger(run_dir)
    policy.preload_lexicon([x for i in missing for x in (i["src"], i["raw"], i["gold"])])
    if True:
        for item in missing:
            marker, body = te.prepare(item["src"])
            raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
            words_text, _ = policy.apply_policy(body, raw_body, "typo_join")
            cache[item["src"]] = (marker, body, words_text, tagger.predict(body))
    json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return cache


def outputs(cache, items, t_add, t_del, t_form, with_sage=True):
    outs = []
    for item in items:
        marker, body, words_text, preds = cache[item["src"]]
        base = words_text if with_sage and len(te.words_of(words_text)) == len(te.words_of(body)) else body
        outs.append(marker + te.apply_predictions(base, preds, t_add, t_del, t_form))
    return outs


def f05(tp, fp, fn):
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    return 0 if p + r == 0 else 1.25 * p * r / (0.25 * p + r)


def main():
    run_dir = sys.argv[1]
    sets = te.bench.load_sets()
    cache = predictions(run_dir, sets)
    n_off = len(sets["official"])

    best_c = None
    for a in ADD:
        for d in DEL:
            dev = te.bench.score(sets["dev"], outputs(cache, sets["dev"], a, d, 1.1, with_sage=False))
            off = te.bench.score(sets["official"], outputs(cache, sets["official"], a, d, 1.1, with_sage=False))
            alarms = 100.0 * off["comma_fp"] / n_off
            score = f05(dev["comma_tp"], dev["comma_fp"], dev["comma_fn"])
            if alarms <= OFFICIAL_BUDGET / 2 and (best_c is None or score > best_c[0]):
                best_c = (score, a, d)
    best_f = None
    for f in FORM:
        dev = te.bench.score(sets["dev"], outputs(cache, sets["dev"], 1.1, 1.1, f, with_sage=False))
        off = te.bench.score(sets["official"], outputs(cache, sets["official"], 1.1, 1.1, f, with_sage=False))
        alarms = 100.0 * off["other_fp"] / n_off
        score = f05(dev["other_tp"], dev["other_fp"], dev["other_fn"])
        if alarms <= OFFICIAL_BUDGET / 2 and (best_f is None or score > best_f[0]):
            best_f = (score, f)
    a, d = best_c[1], best_c[2]
    f = best_f[1] if best_f else 1.1
    print("выбранные пороги: добавить запятую %.3f, убрать запятую %.3f, форма %.3f" % (a, d, f))
    for name in ("dev", "test", "official", "public"):
        items = sets[name]
        outs = outputs(cache, items, a, d, f)
        c = te.bench.score(items, outs)
        found, total, dfp = te.detection(items, outs)
        print("%-9s запятые TP=%3d FP=%3d FN=%3d | слова TP=%3d FP=%3d FN=%3d | обнаружено %3d/%-3d ложных %3d" % (
            name, c["comma_tp"], c["comma_fp"], c["comma_fn"], c["other_tp"], c["other_fp"], c["other_fn"], found, total, dfp))


if __name__ == "__main__":
    main()
