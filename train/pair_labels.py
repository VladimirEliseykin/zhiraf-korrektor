"""Real error pairs (src, gold) -> word-aligned labels for the edit tagger.

The tagger models two things: a comma after a word (KEEP/ADD/DEL) and a changed word form (same lemma,
other grammemes). A real pair also holds edits we do not model (spelling, case, periods, dashes, rewrites).
Those are "normalised": the gold version is copied INTO src, so that the only differences left are commas and
modelled word forms. Then the labels are exact: restore(src_norm, comma, form) == gold_norm.

A pair is dropped when it cannot be represented (reasons are counted): too much rewriting, no words, a
sentence that does not fit the model, or labels that do not restore.

    python pair_labels.py in1.jsonl[,in2.jsonl] out.jsonl [--stats stats.json]

Output lines: {"src": normalised src, "gold": normalised gold, "comma": [...], "form": [...]}; labels are aligned
with words_of(src). src == gold (all KEEP) is a clean example.
"""
import argparse
import collections
import difflib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corrupt import (COMMA_ADD, COMMA_DEL, COMMA_KEEP, FORM_KEEP, form_label, morph,  # noqa: E402
                     restore, words_of)
from spellcheck.text import inflect  # noqa: E402

MAX_REGION_WORDS = 4   # an unmodelled rewrite longer than this (words, per region) drops the pair
MAX_REWRITTEN = 6      # ... and so do more rewritten words than this in all
MAX_WORDS = 120        # longer texts do not fit the model's 192 tokens anyway


def fold(word):
    return word.lower().replace("ё", "е")


def form_edit(a, b):
    """Form label that turns word a into word b (same lemma, other grammemes) or None."""
    if not a or not b or fold(a) == fold(b) or a[0].isupper() != b[0].isupper():
        return None
    pas, pbs = morph.parse(a.lower())[:3], morph.parse(b.lower())[:3]
    for pb in pbs:
        for pa in pas:
            if pa.normal_form != pb.normal_form or pa.tag.POS != pb.tag.POS:
                continue
            label = form_label(b, pa.tag, pb.tag)
            if label and fold(inflect(a, label) or "") == fold(b):
                return label
    return None


def _gap(text, ms, i):
    """Text between word i and word i+1 (the end of the text after the last word)."""
    end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
    return text[ms[i].end():end]


def _with_comma(gap, want):
    """gap with a comma right after the word set to want."""
    has = gap.startswith(",")
    if want and not has:
        return "," + gap
    if has and not want:
        return gap[1:]
    return gap


def derive(src, gold):
    """(src_norm, gold_norm, comma, form) or (None, reason) when the pair cannot be represented."""
    ms, mg = words_of(src), words_of(gold)
    if not ms or not mg:
        return None, "no_words"
    if len(ms) > MAX_WORDS or len(mg) > MAX_WORDS:
        return None, "too_long"
    ws, wg = [m.group(0) for m in ms], [m.group(0) for m in mg]
    sm = difflib.SequenceMatcher(None, [fold(w) for w in ws], [fold(w) for w in wg], autojunk=False)
    anchors = []     # (i, j): word i of src stands for word j of gold
    rewritten = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            anchors += list(zip(range(i1, i2), range(j1, j2)))
        elif tag == "replace" and i2 - i1 == j2 - j1:
            anchors += list(zip(range(i1, i2), range(j1, j2)))
        else:
            rewritten += max(i2 - i1, j2 - j1)
            if max(i2 - i1, j2 - j1) > MAX_REGION_WORDS:
                return None, "rewrite_too_long"
    if rewritten > MAX_REWRITTEN:
        return None, "too_much_rewriting"
    # an anchor pair of different words is a form edit, or a spelling/other edit that gets normalised
    pieces = []      # ("gap", text, src has comma, gold has comma) | ("text", text, None, None) | ("word", (a, b), i, j)
    prev_i, prev_j = -1, -1
    stats = collections.Counter()
    for (i, j) in anchors + [(len(ws), len(wg))]:
        # stretch between the previous anchor and this one
        between_words = (i - prev_i - 1) + (j - prev_j - 1)
        if between_words == 0 and prev_i >= 0 and i < len(ws):
            # plain gap between two anchored words: gold's text, the comma as src has it
            s_has, g_has = _gap(src, ms, prev_i).startswith(","), _gap(gold, mg, prev_j).startswith(",")
            pieces.append(("gap", _with_comma(_gap(gold, mg, prev_j), s_has), s_has, g_has))
        else:
            # a rewritten stretch (or the text edge): copied from gold as it is
            a = mg[prev_j].end() if prev_j >= 0 else 0
            b = mg[j].start() if j < len(wg) else len(gold)
            pieces.append(("text", gold[a:b], None, None))
            if between_words and prev_i >= 0:
                stats["rewritten_stretches"] += 1
        if i < len(ws):
            pieces.append(("word", (ws[i], wg[j]), i, j))
        prev_i, prev_j = i, j
    # assemble src_norm / gold_norm and the labels
    src_parts, gold_parts, comma_lab, form_lab = [], [], [], []
    last_word = None
    for kind, val, x, y in pieces:
        if kind == "word":
            a, b = val
            label = FORM_KEEP
            if a == b:
                text_s = text_g = a
            elif fold(a) == fold(b):
                text_s = text_g = b                  # case / yo edit: normalised
                stats["case_or_yo"] += 1
            else:
                lab = form_edit(a, b)
                if lab:
                    text_s, text_g, label = a, b, lab
                    stats["form"] += 1
                else:
                    text_s = text_g = b              # spelling or another edit: normalised
                    stats["other_word"] += 1
            src_parts.append(text_s)
            gold_parts.append(text_g)
            comma_lab.append(COMMA_KEEP)
            form_lab.append(label)
            last_word = len(comma_lab) - 1
        elif kind == "gap":
            s_has, g_has = x, y
            src_parts.append(val)
            gold_parts.append(_with_comma(val, g_has))
            if s_has != g_has:
                comma_lab[last_word] = COMMA_ADD if g_has else COMMA_DEL
                stats["comma"] += 1
        else:
            src_parts.append(val)
            gold_parts.append(val)
            n = len(words_of(val))   # rewritten words: gold's, no edit left to label
            comma_lab += [COMMA_KEEP] * n
            form_lab += [FORM_KEEP] * n
            if n:
                last_word = len(comma_lab) - 1
    src_norm, gold_norm = "".join(src_parts), "".join(gold_parts)
    if len(words_of(src_norm)) != len(comma_lab):
        return None, "misaligned"
    try:
        ok = restore(src_norm, comma_lab, form_lab) == gold_norm
    except Exception:  # noqa: BLE001 - any failure of the inflection means "not representable"
        ok = False
    if not ok:
        return None, "restore_mismatch"
    return (src_norm, gold_norm, comma_lab, form_lab), stats


def convert(pairs):
    """Yield records for the representable pairs; returns the stats through the second tuple value."""
    kept, dropped, parts = [], collections.Counter(), collections.Counter()
    for p in pairs:
        r = derive(p["src"], p["gold"])
        if r[0] is None:
            dropped[r[1]] += 1
            continue
        src, gold, comma, form = r[0]
        for k, v in r[1].items():
            parts[k] += v
        kept.append({"src": src, "gold": gold, "comma": comma, "form": form})
    clean = sum(1 for r in kept if not any(c != COMMA_KEEP for c in r["comma"]) and not any(f != FORM_KEEP for f in r["form"]))
    stats = {"input": len(kept) + sum(dropped.values()), "kept": len(kept), "dropped": dict(dropped),
             "clean_after_normalisation": clean,
             "with_comma_add": sum(1 for r in kept if COMMA_ADD in r["comma"]),
             "with_comma_del": sum(1 for r in kept if COMMA_DEL in r["comma"]),
             "with_form": sum(1 for r in kept if any(f != FORM_KEEP for f in r["form"])),
             "edits": dict(parts)}
    return kept, stats


def read_pairs(paths):
    for path in paths:
        for line in open(path, encoding="utf-8"):
            if line.strip():
                yield json.loads(line)


def load_records(paths):
    """Records of normalised pair files, as the training examples (text, comma, form, None)."""
    return [(r["src"], r["comma"], r["form"], None) for p in paths for r in
            (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", help="comma separated jsonl files with src and gold")
    ap.add_argument("out")
    ap.add_argument("--stats")
    a = ap.parse_args()
    kept, stats = convert(read_pairs(a.inputs.split(",")))
    with open(a.out, "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    if a.stats:
        json.dump(stats, open(a.stats, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
