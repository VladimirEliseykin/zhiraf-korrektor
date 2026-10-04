"""Split word-level false edits on the dev set between SAGE typo fixes and the tagger's form changes."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import system_eval  # noqa: E402,F401  (registers the typo_join policy)
import tagger_eval as te  # noqa: E402
import policy  # noqa: E402


def main():
    run_dir, t = sys.argv[1], float(sys.argv[2])
    tagger = te.EditTagger(run_dir)
    sets = te.bench.load_sets()
    items = sets["dev"]
    policy.preload_lexicon([x for i in items for x in (i["src"], i["raw"], i["gold"])])
    for item in items:
        marker, body = te.prepare(item["src"])
        raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
        sage_text, _ = policy.apply_policy(body, raw_body, "typo_join")
        tag_text = te.apply_predictions(body, tagger.predict(body), 1.1, 1.1, t)  # forms only
        gold = {e[:3] for e in te.bench.edits(item["src"], item["gold"])}
        for source, out in (("SAGE", marker + sage_text), ("МОДЕЛЬ", marker + tag_text)):
            for e in te.bench.edits(item["src"], out):
                if not te.bench.is_comma(e):
                    verdict = "верно " if e[:3] in gold else "ЛОЖНО"
                    print("%s %-7s [%s] -> [%s] | %s" % (verdict, source, " ".join(e[3]), " ".join(e[2]), item["src"][:110]))


if __name__ == "__main__":
    main()
