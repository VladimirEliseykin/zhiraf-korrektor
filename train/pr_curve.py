"""Precision/recall of comma and word-form actions over all 1000 real gold sentences, per threshold.

Usage: python pr_curve.py <run_dir>...
Uses the prediction cache of threshold_sweep.py; also shows false alarms on clean official text.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.98)


def main():
    sets = ts.te.bench.load_sets()
    everything = sets["dev"] + sets["test"]
    tech = [i for i in everything if ts.te.bench.is_tech(i["doc"])]
    n_off = len(sets["official"])
    for run_dir in sys.argv[1:]:
        cache = ts.predictions(run_dir, sets)
        for label, real in (("все %d реальных" % len(everything), everything), ("служебно-технические (%d)" % len(tech), tech)):
            report(run_dir, label, cache, real, sets, n_off)


def report(run_dir, label, cache, real, sets, n_off):
    if True:
        print("\n=== %s — %s ===" % (os.path.basename(run_dir), label))
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
