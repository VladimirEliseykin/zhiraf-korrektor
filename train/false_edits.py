"""List a run's false edits on all 1000 real gold sentences at given thresholds.

Usage: python false_edits.py <run_dir> <t_comma> <t_form>
Prints each system edit that is not in the gold, with the sentence, so that false alarms can be
re-checked by hand (part of them are real errors the annotators missed).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

bench = ts.te.bench


def main():
    run_dir, t_comma, t_form = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    sets = bench.load_sets()
    items = sets["dev"] + sets["test"]
    cache = ts.predictions(run_dir, sets)
    for label, outs in (("ЗАПЯТАЯ", ts.outputs(cache, items, t_comma, max(t_comma, 0.9), 1.1, with_sage=False)),
                        ("ФОРМА", ts.outputs(cache, items, 1.1, 1.1, t_form, with_sage=False))):
        for item, out in zip(items, outs):
            gold = {e[:3] for e in bench.edits(item["src"], item["gold"])}
            ranges = bench.disputed_ranges(item["src"], item["disputed"])
            for e in bench.edits(item["src"], out):
                if e[:3] in gold or any(e[0] < r[1] and e[1] > r[0] or e[0] == r[0] for r in ranges):
                    continue
                print("%s %s→%s | %s\n    система: %s\n    эталон:  %s\n" % (
                    label, " ".join(e[3]) or "∅", " ".join(e[2]) or "∅", item["doc"][:30], out, item["gold"]))


if __name__ == "__main__":
    main()
