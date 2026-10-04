"""Show what the tagger gets wrong on the real gold set: false edits and missed gold errors."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tagger_eval as te  # noqa: E402


def main():
    run_dir, t = sys.argv[1], float(sys.argv[2])
    tagger = te.EditTagger(run_dir)
    sets = te.bench.load_sets()
    split = sys.argv[3] if len(sys.argv) > 3 else "dev"
    items = sets[split]  # analyse on dev only; test stays untouched for the final measurement
    cache = te.run(tagger, items, {})
    for item in items:
        out = te.corrected(cache, item["src"], t, t, t)
        gold = {e[:3]: e for e in te.bench.edits(item["src"], item["gold"])}
        system = {e[:3]: e for e in te.bench.edits(item["src"], out)}
        for k, e in system.items():
            if k not in gold:
                print("ЛОЖНО   [%s] -> [%s]   | %s" % (" ".join(e[3]), " ".join(e[2]), item["src"][:150]))
        for k, e in gold.items():
            if k not in system:
                print("ПРОПУСК [%s] -> [%s]   | %s" % (" ".join(e[3]), " ".join(e[2]), item["src"][:150]))


if __name__ == "__main__":
    main()
