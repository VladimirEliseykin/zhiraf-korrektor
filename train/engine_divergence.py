"""Where the shipped engine finds, misses and falsely flags, by error context (counts only, no text).

Usage: python engine_divergence.py <engine-findings.json>
The findings file is the output of engine_eval.py (sentence -> findings). Only DEV gold and the clean OFFICIAL
set are read; the test split is never touched. For every gold edit of type missing comma / spurious comma /
word form the finding at its place is looked up: "error" (sure fix), "check" (highlight) or missed. Findings that
match no gold edit are false; they are counted per context of the place they stand on, on dev (where the
sentence's own gold edits are excluded) and on official (every finding there is false)."""
import collections
import json
import sys

import error_profile as ep


def analyse(findings, sets):
    out = collections.defaultdict(collections.Counter)
    for name, items, has_gold in (("dev", sets["dev"], True), ("official", sets["official"], False)):
        for it in items:
            src = it["src"]
            ms = ep.words_of(src)
            gaps = {i: (h, f) for i, h, f in ep.comma_gaps(src, ms)}
            finds = [f for f in findings.get(src, []) if f["rule"] in ("MODEL_COMMA", "MODEL_COMMA_DEL", "MODEL_FORM")]
            used = set()
            for kind, gi, detail, si in (ep.real_edits(src, it["gold"]) if has_gold else []):
                if kind not in ("comma_add", "comma_del", "form") or si is None or not 0 <= si < len(ms):
                    continue
                rule = {"comma_add": "MODEL_COMMA", "comma_del": "MODEL_COMMA_DEL", "form": "MODEL_FORM"}[kind]
                at = ms[si].start() if kind == "form" else ms[si].end()
                hit = next(((k, f) for k, f in enumerate(finds) if f["rule"] == rule and f["start"] == at), None)
                gms = ep.words_of(it["gold"])
                if kind == "form":
                    key = ep.form_features(it["gold"], gms, gi, detail)["ctx"]
                else:
                    g2 = {i: f for i, h, f in ep.comma_gaps(it["gold"], gms)}
                    if gi not in g2:
                        continue
                    key = g2[gi]["ctx"]
                if hit:
                    used.add(hit[0])
                    out["%s.%s.%s" % (name, kind, key)][hit[1]["level"]] += 1
                else:
                    out["%s.%s.%s" % (name, kind, key)]["missed"] += 1
            for k, f in enumerate(finds):
                if k in used:
                    continue
                if f["rule"] == "MODEL_FORM":
                    idx = next((i for i, m in enumerate(ms) if m.start() == f["start"]), None)
                    if idx is None:
                        continue
                    changed = ep.grammemes_changed(ms[idx].group(0), f["fix"]) or set()
                    feats = ep.form_features(src, ms, idx, changed)
                    for feat in ("ctx", "changed", "pos"):
                        out["%s.false.form.%s" % (name, feat)]["%s/%s" % (feats[feat], f["level"])] += 1
                else:
                    idx = next((i for i, m in enumerate(ms) if m.end() == f["start"]), None)
                    if idx is None or idx not in gaps:
                        continue
                    kind = "add" if f["rule"] == "MODEL_COMMA" else "del"
                    for feat in ("ctx", "prev_pos", "next_pos"):
                        out["%s.false.comma_%s.%s" % (name, kind, feat)]["%s/%s" % (gaps[idx][1][feat], f["level"])] += 1
    return out


def main():
    findings = json.load(open(sys.argv[1], encoding="utf-8"))
    out = analyse(findings, ep.load_dev())
    for key in sorted(out):
        print(key, dict(out[key]))


if __name__ == "__main__":
    main()
