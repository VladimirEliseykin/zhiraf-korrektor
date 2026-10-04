"""Two-model agreement: an edit is applied only when both runs predict it above the threshold.

Usage: python ensemble_curve.py <run_a> <run_b>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95)


def agreed(pa, pb):
    """Per-word predictions keeping only actions both models support (min probability)."""
    out = []
    for a, b in zip(pa, pb):
        comma = {k: min(a["comma"][k], b["comma"][k]) for k in a["comma"]}
        same_form = a["form"] == b["form"]
        out.append({"comma": comma, "form": a["form"] if same_form else "KEEP",
                    "form_p": min(a["form_p"], b["form_p"]) if same_form else 0.0, "form_keep_p": 0.0})
    return out


def main():
    sets = ts.te.bench.load_sets()
    ca = ts.predictions(sys.argv[1], sets)
    cb = ts.predictions(sys.argv[2], sets)
    cache = {}
    for src, (marker, body, words_text, pa) in ca.items():
        cache[src] = (marker, body, words_text, agreed(pa, cb[src][3]))
    real = sets["dev"] + sets["test"]
    n_off = len(sets["official"])
    print("порог | запятые: верн/ложн/пропущ  точн полн | ложных офиц/100 || формы: верн/ложн  точн | ложных офиц/100")
    for t in THRESHOLDS:
        c = ts.te.bench.score(real, ts.outputs(cache, real, t, max(t, 0.9), 1.1, with_sage=False))
        co = ts.te.bench.score(sets["official"], ts.outputs(cache, sets["official"], t, max(t, 0.9), 1.1, with_sage=False))
        f = ts.te.bench.score(real, ts.outputs(cache, real, 1.1, 1.1, t, with_sage=False))
        fo = ts.te.bench.score(sets["official"], ts.outputs(cache, sets["official"], 1.1, 1.1, t, with_sage=False))
        cp = c["comma_tp"] / max(1, c["comma_tp"] + c["comma_fp"])
        cr = c["comma_tp"] / max(1, c["comma_tp"] + c["comma_fn"])
        fp_ = f["other_tp"] / max(1, f["other_tp"] + f["other_fp"])
        print("%.2f  | %3d / %3d / %3d   %3.0f%% %3.0f%% | %5.2f            || %3d / %3d  %3.0f%% | %5.2f" % (
            t, c["comma_tp"], c["comma_fp"], c["comma_fn"], 100 * cp, 100 * cr, 100.0 * co["comma_fp"] / n_off,
            f["other_tp"], f["other_fp"], 100 * fp_, 100.0 * fo["other_fp"] / n_off))


if __name__ == "__main__":
    main()
