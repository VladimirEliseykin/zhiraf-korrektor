"""Does running the tagger again on its own corrected output find more errors?

Usage: python multipass.py <comma_run> <form_run> <t_comma> <t_form> [passes]
Pass 1 = the usual single run. Each next pass re-predicts on the text corrected so far and applies
the same thresholds (GECToR-style iterative refinement). Scores after every pass.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import threshold_sweep as ts  # noqa: E402

te = ts.te
bench = te.bench


def merged(pc, pf):
    return [{"comma": c["comma"], "form": f["form"], "form_p": f["form_p"], "form_keep_p": f["form_keep_p"]}
            for c, f in zip(pc, pf)]


def main():
    run_c, run_f, tc, tf = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    passes = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    sets = bench.load_sets()
    real = sets["dev"] + sets["test"]
    cache_c, cache_f = ts.predictions(run_c, sets), ts.predictions(run_f, sets)
    tag_c, tag_f = te.EditTagger(run_c), te.EditTagger(run_f)
    for label, items in (("реальные %d" % len(real), real), ("офиц. чистые %d" % len(sets["official"]), sets["official"])):
        bodies = {}
        for item in items:
            marker, body, _, pc = cache_c[item["src"]]
            bodies[item["src"]] = (marker, te.apply_predictions(body, merged(pc, cache_f[item["src"]][3]), tc, 1.1, tf))
        for n in range(1, passes + 1):
            if n > 1:
                for item in items:
                    marker, body = bodies[item["src"]]
                    preds = merged(tag_c.predict(body), tag_f.predict(body))
                    bodies[item["src"]] = (marker, te.apply_predictions(body, preds, tc, 1.1, tf))
            outs = [bodies[i["src"]][0] + bodies[i["src"]][1] for i in items]
            c = bench.score(items, outs)
            print("%-18s проход %d | запятые верн %3d ложн %3d | формы верн %3d ложн %3d" % (
                label, n, c["comma_tp"], c["comma_fp"], c["other_tp"], c["other_fp"]), flush=True)


if __name__ == "__main__":
    main()
