"""Effect of each word-form guard on all 1000 real gold sentences and on clean official text.

Usage: python guard_ablation.py <run_dir>...
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

te = ts.te
VARIANTS = (("без запретов", {"grammar_veto": False, "capital_mid": False}),
            ("+ грамматика", {"grammar_veto": True, "capital_mid": False}),
            ("+ заглавные", {"grammar_veto": False, "capital_mid": True}),
            ("+ оба", {"grammar_veto": True, "capital_mid": True}))


def main():
    sets = te.bench.load_sets()
    real = sets["dev"] + sets["test"]
    n_off = len(sets["official"])
    for run_dir in sys.argv[1:]:
        cache = ts.predictions(run_dir, sets)
        print("\n=== %s: формы верн/ложн (ложных офиц/100) ===" % os.path.basename(run_dir))
        print("%-14s" % "порог" + "".join("%22s" % name for name, _ in VARIANTS))
        for t in (0.5, 0.7, 0.8, 0.9, 0.95):
            row = []
            for _, guards in VARIANTS:
                te.GUARDS.update(guards)
                f = te.bench.score(real, ts.outputs(cache, real, 1.1, 1.1, t, with_sage=False))
                fo = te.bench.score(sets["official"], ts.outputs(cache, sets["official"], 1.1, 1.1, t, with_sage=False))
                row.append("%3d / %3d (%.2f)" % (f["other_tp"], f["other_fp"], 100.0 * fo["other_fp"] / n_off))
            print("%-14.2f" % t + "".join("%22s" % r for r in row))


if __name__ == "__main__":
    main()
