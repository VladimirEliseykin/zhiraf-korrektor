"""False alarms and hits of the spelling head, per label and threshold, through the checker's own guards.

Usage: python spell_eval.py <run_dir>... [--device cpu] [--threads 4] [--limit N]

Runs the tagger of a run dir over (1) the clean official sentences and (2) the real gold sentences
(dev + test, as pr_curve.py) once, then asks checker.spell_findings for findings at each threshold, so
the guards (title nouns, "не", ambiguous pairs, dictionary checks) are part of what is measured.
For every spelling label and threshold it prints
  official: findings per 100 clean sentences (every one is a false alarm, the text is clean);
  gold:     findings whose fix reproduces a gold edit of spelling type (joined/split/hyphen/case), and the rest.
The threshold is the lowest probability of the label for a finding (LOWER included: the built-in 0.97 is lifted).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch  # noqa: E402
# corrupt first: it puts THIS checkout's engine on the path, before spike/guards.py (inside tagger_eval) can
# import the engine of the main checkout; the guards under test are those of this tree
from corrupt import SPELL_LABELS  # noqa: E402
import tagger_eval as te  # noqa: E402
from spellcheck.checker import apply, spell_findings  # noqa: E402

THRESHOLDS = (0.3, 0.5, 0.7, 0.9, 0.97)
OFFICIAL = os.path.join(te.SPIKE, "official-sentences.jsonl")
LABELS = [label for label in SPELL_LABELS if label != "KEEP"]


def spelling_edit(edit):
    """True for a gold edit of spelling type: the same letters re-split, re-hyphenated or re-cased."""
    after, before = edit[2], edit[3]

    def letters(tokens):
        return "".join(tokens).replace("-", "").lower()

    if not before or not after or letters(before) != letters(after):
        return False
    return len(before) != len(after) or before != after


def finding_hits_spelling(item, marker, body, finding, gold_spelling):
    """True when applying the finding turns the source into text with one of the gold spelling edits."""
    out = marker + apply(body, [finding], levels=("error", "check"))
    return any(e[:3] in gold_spelling for e in te.bench.edits(item["src"], out))


def predict_all(tagger, items):
    result = []
    for item in items:
        marker, body = te.prepare(item["src"])
        result.append((item, marker, body, tagger.predict(body)))
    return result


def report(run_dir, official, real, gold_spelling):
    n_off = len(official)
    print("\n=== %s: %d clean official sentences, %d real gold sentences, %d gold spelling edits ===" % (
        os.path.basename(os.path.normpath(run_dir)), n_off, len(real), sum(len(v) for v in gold_spelling.values())))
    print("label   thr  | official findings/100 | gold: hit a spelling edit / other")
    for label in LABELS:
        for t in THRESHOLDS:
            n = sum(1 for _, _, body, preds in official
                    for f in spell_findings(body, preds, check=t, sure_lower=t) if f["label"] == label)
            hit = other = 0
            for item, marker, body, preds in real:
                for f in spell_findings(body, preds, check=t, sure_lower=t):
                    if f["label"] != label:
                        continue
                    if finding_hits_spelling(item, marker, body, f, gold_spelling[item["src"]]):
                        hit += 1
                    else:
                        other += 1
            print("%-7s %.2f | %8.2f              | %4d / %4d" % (label, t, 100.0 * n / max(1, n_off), hit, other))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = torch default)")
    ap.add_argument("--limit", type=int, default=0, help="use only the first N sentences of each set (smoke runs)")
    args = ap.parse_args()
    if args.threads:
        torch.set_num_threads(args.threads)
    sets = te.bench.load_sets()
    real = sets["dev"] + sets["test"]
    official = [{"src": r["src"]} for r in te.bench.load_jsonl(OFFICIAL)]
    if args.limit:
        real, official = real[:args.limit], official[:args.limit]
    gold_spelling = {i["src"]: {e[:3] for e in te.bench.edits(i["src"], i["gold"]) if spelling_edit(e)} for i in real}
    for run_dir in args.run_dirs:
        tagger = te.EditTagger(run_dir, dev=args.device)
        if not getattr(tagger, "model", None) or tagger.model.spell_head is None:
            sys.exit("%s has no spelling head" % run_dir)
        report(run_dir, predict_all(tagger, official), predict_all(tagger, real), gold_spelling)
        del tagger


if __name__ == "__main__":
    main()
