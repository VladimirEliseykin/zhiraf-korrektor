"""Full pipeline on the benchmarks: SAGE typo/hyphen fixes + edit tagger (commas, word forms).

Usage: python system_eval.py <run_dir> <threshold>
SAGE contributes only dictionary-confirmed typos and joined/hyphenated spellings;
the tagger handles commas and endings. Both work on the same marker-stripped body.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tagger_eval as te  # noqa: E402
import policy  # noqa: E402  (spike policy, imported via tagger_eval's sys.path)

policy.ALLOWED["typo_join"] = {"typo", "join"}


def main():
    run_dir, t = sys.argv[1], float(sys.argv[2])
    tagger = te.EditTagger(run_dir)
    sets = te.bench.load_sets()
    policy.preload_lexicon([x for s in sets.values() for i in s for x in (i["src"], i["raw"], i["gold"])])
    for name in ("dev", "test", "official", "public"):
        items = sets[name]
        outs = []
        for item in items:
            marker, body = te.prepare(item["src"])
            raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
            words_text, _ = policy.apply_policy(body, raw_body, "typo_join")
            preds = tagger.predict(body)
            # tagger labels are per word of body; reuse them on the typo-fixed text when word count matches
            if len(te.words_of(words_text)) == len(te.words_of(body)):
                text = te.apply_predictions(words_text, preds, t, t, t)
            else:
                text = words_text
            outs.append(marker + text)
        c = te.bench.score(items, outs)
        found, total, dfp = te.detection(items, outs)
        print("%-9s запятые TP=%3d FP=%3d FN=%3d | слова TP=%3d FP=%3d FN=%3d | обнаружено %3d/%-3d ложных %3d" % (
            name, c["comma_tp"], c["comma_fp"], c["comma_fn"], c["other_tp"], c["other_fp"], c["other_fn"], found, total, dfp))


if __name__ == "__main__":
    main()
