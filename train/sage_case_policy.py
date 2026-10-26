"""Guarded letter-case rule: SAGE's case edits (and the spelling head's LOWER / UPPER) on top of the shipped engine findings.

    python sage_case_policy.py EVAL_DIR [--findings work/sage-ft/findings-b3.json]

SAGE case candidates (sage_case_eval.case_edits) pass the guards of checker.spell_fix (LOWER: mid-sentence common noun,
not a name, not in capital_lemmas.txt; UPPER: sentence start or a name) plus extra ones (not quoted, no latin / digits, no
title-like neighbour, ...). Variants differ in the guards, in the level and in the confirmer (the spell head's LOWER /
UPPER probability from runs/base-cased-spell/bench-preds.json). Scored like engine_eval: fixed / highlighted of the gold
and false marks per 100 sentences, official separately.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sage_case_eval as CE  # noqa: E402
import sage_policy_eval as P  # noqa: E402
from sage_policy_eval import bench, checker, score  # noqa: E402
from spellcheck import sage  # noqa: E402
from spellcheck.guards import QUOTES, prepare, protected, quoted_spans  # noqa: E402
from spellcheck.morph import morph  # noqa: E402
from spellcheck.text import words_of  # noqa: E402

ROOT = P.ROOT


def title_like(body, ms, i):
    """A capitalised neighbour (previous or next word, not at a sentence start): "Алые Паруса", "Индивидуального Предпринимателя"."""
    for j in (i - 1, i + 1):
        if 0 < j < len(ms) and ms[j].group(0)[:1].isupper() and not (j == 0):
            gap = body[min(ms[i].end(), ms[j].end()):max(ms[i].start(), ms[j].start())]
            if gap.strip() == "":
                return True
    return False


def candidates(src, out_text, spell):
    marker, body = prepare(src)
    out = sage.postprocess(body, out_text)
    ms = words_of(body)
    quotes = quoted_spans(body)
    res = []
    ent = spell.get(src)
    for s, e, x, y, kind in CE.case_edits(body, out):
        if kind not in ("start-up", "mid-down", "mid-up"):
            continue
        i = next((k for k, m in enumerate(ms) if m.start() == s), None)
        if i is None:
            continue
        word = ms[i].group(0)
        label = "LOWER" if kind == "mid-down" else "UPPER"
        p = ent[3][i]["spell"][label] if ent and ent[1] == body and i < len(ent[3]) and "spell" in ent[3][i] else None
        res.append(dict(start=s + len(marker), end=e + len(marker), fix=y, kind=kind, i=i, word=word, body=body, ms=ms,
                        quotes=quotes, p=p, marker=marker))
    return res


NOT_NAME = ("Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad")
FUNCTION_POS = {"ADJF", "ADJS", "PRTF", "PRTS", "VERB", "INFN", "ADVB", "PRED", "NPRO", "GRND"}


def after_comma_word(body, ms, i, word):
    """A capitalised adjective / participle / verb right after a comma ("..., Любая деятельность"): never a title or a name."""
    before = body[max(0, ms[i].start() - 2):ms[i].start()]
    if before != ", " or len(word) < 4 or not word[1:].islower():
        return False
    parse = morph.parse(word.lower())[0]
    return parse.tag.POS in FUNCTION_POS and not any(g in parse.tag for g in NOT_NAME)


def accepted(c, opt):
    body, ms, i, word = c["body"], c["ms"], c["i"], c["word"]
    if any(a < ms[i].start() < b for a, b in c["quotes"]) and opt.get("quote_guard", True):
        return False
    if protected(word):
        return False
    if c["kind"] == "mid-down":
        if opt.get("after_comma_only"):
            return after_comma_word(body, ms, i, word)
        if checker.spell_fix(body, ms, i, "LOWER", c["quotes"]) is None and not (opt.get("after_comma") and after_comma_word(body, ms, i, word)):
            return False
        if opt.get("title_guard") and title_like(body, ms, i):
            return False
    elif c["kind"] == "mid-up":
        if not opt.get("mid_up") or checker.spell_fix(body, ms, i, "UPPER", c["quotes"]) is None:
            return False
    else:  # start-up
        if not opt.get("start_up") or not body.rstrip().endswith((".", "!", "?")):
            return False
    th = opt.get("confirm")
    if th is not None and (c["p"] is None or c["p"] < th):
        return False
    return True


VARIANTS = [
    ("shipped (b3)", None),
    ("after-comma non-noun only, error", dict(level="error", after_comma_only=True)),
    ("after-comma non-noun only, check", dict(level="check", after_comma_only=True)),
    ("guarded + after-comma non-noun, error", dict(level="error", after_comma=True)),
    ("mid-down guarded, check", dict(level="check")),
    ("mid-down guarded, error", dict(level="error")),
    ("mid-down guarded + title guard, check", dict(level="check", title_guard=True)),
    ("mid-down guarded + title guard, error", dict(level="error", title_guard=True)),
    ("+ start-up (sentence ends .!?), check", dict(level="check", start_up=True)),
    ("+ mid-up names, check", dict(level="check", mid_up=True)),
    ("mid-down confirmed by spell LOWER >= 0.01, error", dict(level="error", confirm=0.01)),
    ("mid-down confirmed by spell LOWER >= 0.1, error", dict(level="error", confirm=0.1)),
    ("mid-down confirmed by spell LOWER >= 0.3, error", dict(level="error", confirm=0.3)),
    ("mid-down confirmed by spell LOWER >= 0.01, check", dict(level="check", confirm=0.01)),
    ("mid-down confirmed >= 0.01 error, others check", dict(level="check", confirm_error=0.01)),
]


def case_counts(items, res):
    """(case gold edits fixed at error, highlighted at check, all) and the false marks of rule SAGE_CASE."""
    import coverage
    import engine_eval as ee
    fixed = flagged = total = fa = 0
    for it in items:
        sure, check = ee.edits_of(it, res[it["src"]], "error"), ee.edits_of(it, res[it["src"]], "check")
        gold = list(bench.edits(it["src"], it["gold"]))
        for g in gold:
            if coverage.kind(g) != "регистр":
                continue
            total += 1
            if any(x[:3] == g[:3] for x in sure):
                fixed += 1
            elif any(coverage.touches(g, x) for x in sure + check):
                flagged += 1
    return fixed, flagged, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir")
    ap.add_argument("--findings", default="/home/general/vm/win7-profiles/work/sage-ft/findings-b3.json")
    ap.add_argument("--sets", nargs="+", default=["dev", "test", "official"])
    a = ap.parse_args()
    sets = bench.load_sets()
    eng = json.load(open(a.findings, encoding="utf-8"))
    spell = json.load(open(os.path.join(ROOT, "runs/base-cased-spell/bench-preds.json"), encoding="utf-8"))
    cands = {}
    for name in a.sets:
        outs = {json.loads(l)["src"]: json.loads(l)["out"] for l in open(os.path.join(a.eval_dir, "out-%s.jsonl" % name), encoding="utf-8")}
        for item in sets[name]:
            cands[item["src"]] = candidates(item["src"], outs[item["src"]], spell)
    print("%-52s | %s" % ("variant", "  ".join("%-34s" % s for s in a.sets)))
    for label, opt in VARIANTS:
        cells = []
        for name in a.sets:
            items = sets[name]
            res = {}
            for it in items:
                src = it["src"]
                found = list(eng[src])
                if opt:
                    for c in cands[src]:
                        if not accepted(c, opt):
                            continue
                        level = "error" if opt.get("confirm_error") is not None and c["p"] is not None and c["p"] >= opt["confirm_error"] else opt["level"]
                        found.append({"start": c["start"], "end": c["end"], "level": level, "rule": "SAGE_CASE", "fix": c["fix"], "message": "Регистр"})
                res[src] = checker.merge(found)
            r, n = score(items, res), len(items)
            if name == "official":
                cells.append("false err %.2f chk %.2f" % (100.0 * r["false_error"] / n, 100.0 * r["false_check"] / n))
            else:
                cells.append("fix %2.0f%% flg %2.0f%% fe %.2f fc %.2f case fixed %d flagged %d" % (
                    100.0 * r["fixed"] / r["gold"], 100.0 * r["flagged"] / r["gold"], 100.0 * r["false_error"] / n,
                    100.0 * r["false_check"] / n, *case_counts(items, res)[:2]))
        print("%-52s | %s" % (label, "  ".join("%-34s" % c for c in cells)), flush=True)


if __name__ == "__main__":
    main()
