"""Feature profile of comma and word-form errors, real (gold edits) versus synthetic (corrupt.py labels).

Only counts and category names are produced: no sentence text ever leaves this module.
Every feature is computed on the CLEAN side of an edit (the corrected sentence for real edits, the
corpus sentence for synthetic ones), at the word i after which the comma stands or is missing, or at
the word whose form is wrong, so that both sides use the very same function.

Usage (analysis on dev only):
  python error_profile.py real              # profile of the dev gold, counts as json on stdout
  python error_profile.py synth <corpus.jsonl> [n] [recipe]   # recipe: commas | forms | commas-real | forms-real
"""
import collections
import difflib
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corrupt as cr  # noqa: E402
from corrupt import morph, words_of  # noqa: E402
from error_context import (CASE_BASE, PREPOSITIONS, _parse, coarse_pos, comma_features, comma_gaps,  # noqa: E402,F401
                           form_features, len_bucket, pos_of)



# ---- real edits ---------------------------------------------------------------------------------------
TOKEN = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:[-‑][А-Яа-яЁёA-Za-z0-9]+)*|,")


def tokens(text):
    return [t.lower().replace("ё", "е") for t in TOKEN.findall(text)]


def grammemes_changed(src_word, gold_word):
    """Categories in which the gold form differs from the src form, or None when the lemmas differ."""
    a, b = morph.parse(src_word.lower()), morph.parse(gold_word.lower())
    lemmas_a = {p.normal_form for p in a}
    best = None
    for pb in b:
        if pb.normal_form not in lemmas_a:
            continue
        for pa in a:
            if pa.normal_form != pb.normal_form or pa.tag.POS != pb.tag.POS and not {pa.tag.POS, pb.tag.POS} <= {"ADJF", "PRTF"}:
                continue
            diff = {c for c in CASE_BASE if getattr(pa.tag, c) != getattr(pb.tag, c)}
            if diff and (best is None or len(diff) < len(best)):
                best = diff
    return best


def real_edits(src, gold):
    """Classify the edits that turn src into gold.

    Returns [(kind, word index in gold, detail, word index in src)]; for a comma the src index is the word before
    the comma, for a form the word itself."""
    a, b = tokens(src), tokens(gold)
    gold_words = [i for i, t in enumerate(b) if t != ","]        # token index -> word index in gold
    word_of_token = {}
    k = 0
    for ti, t in enumerate(b):
        if t != ",":
            word_of_token[ti] = k
            k += 1
    out = []
    words_before = [0]                                            # src token index -> words before it
    for t in a:
        words_before.append(words_before[-1] + (t != ","))
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        sa, sb = a[i1:i2], b[j1:j2]
        src_idx = words_before[i1] - 1 if set(sa + sb) == {","} else words_before[i1]
        if set(sa + sb) == {","}:
            before = j1 - 1
            while before >= 0 and b[before] == ",":
                before -= 1
            if before < 0 or before not in word_of_token:
                out.append(("other", None, None, None))
                continue
            out.append(("comma_add" if sb else "comma_del", word_of_token[before], None, src_idx))
        elif len(sa) == 1 and len(sb) == 1 and sa[0] != "," and sb[0] != ",":
            changed = grammemes_changed(sa[0], sb[0])
            if changed:
                out.append(("form", word_of_token[j1], changed, src_idx))
            else:
                out.append(("word_other", word_of_token[j1], None, src_idx))
        else:
            out.append(("other", None, None, None))
    return out


def new_counts():
    return collections.defaultdict(collections.Counter)


FEATURES_COMMA = ("ctx", "prev_pos", "next_pos", "len", "first_comma", "where")
FEATURES_FORM = ("pos", "ctx", "dist", "changed", "len")


def add_comma(counts, kind, feats):
    counts[kind + ".n"]["all"] += 1
    for f in FEATURES_COMMA:
        counts[kind + "." + f][feats[f]] += 1


def add_form(counts, feats):
    counts["form.n"]["all"] += 1
    for f in FEATURES_FORM:
        counts["form." + f][feats[f]] += 1


def sentence_stats(counts, text, n_edits):
    n = len(words_of(text))
    counts["sent.len"][len_bucket(n)] += 1
    counts["sent.edits"][str(min(n_edits, 3))] += 1


def clean_text_stats(counts, text, prefix="clean"):
    """Shape of clean text: comma density, share with commas, quotes, digits, Latin."""
    ms = words_of(text)
    n = len(ms)
    if n < 4:
        return
    commas = sum(1 for g in comma_gaps(text, ms) if g[1])
    counts[prefix + ".len"][len_bucket(n)] += 1
    counts[prefix + ".commas_per_sentence"][str(min(commas, 5))] += 1
    counts[prefix + ".commas_per_10_words"]["x"] += commas
    counts[prefix + ".commas_per_10_words"]["words"] += n
    counts[prefix + ".has"]["digits"] += bool(re.search(r"\d", text))
    counts[prefix + ".has"]["latin"] += bool(re.search(r"[A-Za-z]", text))
    counts[prefix + ".has"]["quotes"] += bool(re.search(r"[«»\"“”]", text))
    counts[prefix + ".has"]["brackets"] += bool(re.search(r"[()\[\]]", text))
    counts[prefix + ".has"]["dash"] += bool(re.search(r"[–—]", text))
    counts[prefix + ".has"]["total"] += 1


def gap_rates(counts, text, prefix):
    """Base rates over ALL gaps of a clean sentence: how many gaps have / lack a comma, per ctx."""
    ms = words_of(text)
    if len(ms) < 4:
        return
    for i, has, feats in comma_gaps(text, ms):
        counts[prefix + (".gap_comma" if has else ".gap_nocomma")][feats["ctx"]] += 1


def real_profile(items):
    """items: dev sets with src/gold. Returns counts."""
    counts = new_counts()
    for it in items:
        gold = it["gold"]
        ms = words_of(gold)
        edits = real_edits(it["src"], gold)
        counts["real.kinds"]["sentences"] += 1
        sentence_stats(counts, it["src"], len(edits))
        gaps = {i: (has, f) for i, has, f in comma_gaps(gold, ms)}
        gap_rates(counts, gold, "real")
        clean_text_stats(counts, gold, "real_clean")
        for kind, idx, detail, _ in edits:
            counts["real.kinds"][kind] += 1
            if kind in ("comma_add", "comma_del") and idx in gaps:
                add_comma(counts, kind, gaps[idx][1])
            elif kind in ("comma_add", "comma_del"):
                counts["real.kinds"]["comma_unplaced"] += 1
            elif kind == "form" and idx is not None:
                add_form(counts, form_features(gold, ms, idx, detail))
    return counts


# ---- synthetic edits ----------------------------------------------------------------------------------
RECIPES = {
    "commas": dict(p_clean=0.25, max_edits=3, p_single=0.0, p_form=0.45, placement=False),
    "forms": dict(p_clean=0.7, max_edits=2, p_single=0.8, p_form=0.45, placement=True),
    "commas-real": dict(realistic=True, error_rate=10.0, max_edits=4),
    "forms-real": dict(realistic=True, error_rate=3.0, max_edits=4),
}


def synth_profile(sentences, recipe, seed=0, generator=None):
    """Run the generator over clean sentences and profile its labels with the same features."""
    gen = generator or cr.corrupt
    kwargs = dict(RECIPES[recipe] if isinstance(recipe, str) else recipe)
    rng = random.Random(seed)
    counts = new_counts()
    for s in sentences:
        c, comma, form = gen(s, rng, **kwargs)
        ms = words_of(c)
        n_edits = sum(1 for x in comma if x != "KEEP") + sum(1 for x in form if x != "KEEP")
        clean_ms = words_of(s)
        counts["synth.kinds"]["sentences"] += 1
        sentence_stats(counts, s, n_edits)
        if len(clean_ms) != len(ms):
            continue
        gaps = {i: (has, f) for i, has, f in comma_gaps(s, clean_ms)}
        if len(counts["synth.kinds"]) and counts["synth.kinds"]["sentences"] <= 4000:
            gap_rates(counts, s, "synth")
            clean_text_stats(counts, s, "synth_clean")
        for i, (cl, fl) in enumerate(zip(comma, form)):
            if cl == "ADD" and i in gaps:
                add_comma(counts, "comma_add", gaps[i][1])
                counts["synth.kinds"]["comma_add"] += 1
            elif cl == "DEL" and i in gaps:
                add_comma(counts, "comma_del", gaps[i][1])
                counts["synth.kinds"]["comma_del"] += 1
            if fl != "KEEP":
                changed = {kv.split(":")[0] for kv in fl.split("|")}
                add_form(counts, form_features(s, clean_ms, i, changed))
                counts["synth.kinds"]["form"] += 1
    return counts


# ---- distances ----------------------------------------------------------------------------------------
def share(counter):
    total = sum(counter.values())
    return {k: v / total for k, v in counter.items()} if total else {}


def tv(p, q):
    """Total variation distance between two count dicts (shares)."""
    p, q = share(p), share(q)
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in set(p) | set(q))


def distance(real, synth, kind, skip=()):
    """Mean total variation over the features of an edit kind; returns (mean, per-feature)."""
    feats = FEATURES_FORM if kind == "form" else FEATURES_COMMA
    per = {f: tv(real[kind + "." + f], synth[kind + "." + f]) for f in feats if real.get(kind + "." + f) and f not in skip}
    return sum(per.values()) / max(1, len(per)), per


def noise_floor(synth, kind, n, skip=(), reps=300, seed=0):
    """Mean total variation between n samples drawn from the synthetic profile and the profile itself:
    what a generator that matches the truth exactly would still show against a real sample of n edits."""
    rng = random.Random(seed)
    feats = [f for f in (FEATURES_FORM if kind == "form" else FEATURES_COMMA) if f not in skip]
    total = 0.0
    for f in feats:
        c = synth[kind + "." + f]
        keys, weights = list(c), list(c.values())
        for _ in range(reps):
            sample = collections.Counter(rng.choices(keys, weights, k=n))
            total += tv(sample, c)
    return total / (len(feats) * reps)


def to_plain(counts):
    return {k: dict(v) for k, v in counts.items()}


def load_dev():
    import tagger_eval as te
    return te.bench.load_sets()


def report(real, synth, title, skip=("len",)):
    """Markdown tables: distance per kind, then the largest feature divergences."""
    lines = ["#### %s" % title, "", "| kind | real n | synthetic n | TV (all features) | TV (without %s) | noise floor |" % "/".join(skip),
             "|---|---|---|---|---|---|"]
    detail = []
    for kind in ("comma_add", "comma_del", "form"):
        if kind + ".n" not in synth or kind + ".n" not in real:
            continue
        n = real[kind + ".n"]["all"]
        full, _ = distance(real, synth, kind)
        main, per = distance(real, synth, kind, skip)
        lines.append("| %s | %d | %d | %.3f | %.3f | %.3f |" % (kind, n, synth[kind + ".n"]["all"], full, main,
                                                              noise_floor(synth, kind, n, skip)))
        feats = FEATURES_FORM if kind == "form" else FEATURES_COMMA
        rows = []
        for f in feats:
            p, q = share(real[kind + "." + f]), share(synth[kind + "." + f])
            rows += [(abs(p.get(k, 0) - q.get(k, 0)), f, k, p.get(k, 0), q.get(k, 0)) for k in set(p) | set(q)]
        rows.sort(reverse=True)
        detail.append("\n%s, largest divergences (real share vs synthetic share):\n" % kind)
        detail += ["- %s = %s: %.2f vs %.2f" % (f, k, a, b) for _, f, k, a, b in rows[:8]]
    return "\n".join(lines + detail)


def cross_validate(recipes, sentences, ridge=None):
    """2-fold by document: fit the realistic tables on one half of dev, profile real edits of the other half and
    compare with the old recipes and with the realistic generator fitted on the first half."""
    import fit_realistic
    saved = (cr.BASE_RATE, cr.MISSING_WEIGHT, cr.SPURIOUS_WEIGHT, cr.FORM_WEIGHT)
    items = load_dev()["dev"]
    docs = sorted({it.get("doc", "") for it in items})
    half = {d: i % 2 for i, d in enumerate(docs)}
    out = collections.defaultdict(list)
    for fold in (0, 1):
        train = [it for it in items if half[it.get("doc", "")] != fold]
        test = [it for it in items if half[it.get("doc", "")] == fold]
        base, missing, spurious, forms, _ = fit_realistic.fit_weights(train, ridge)
        real = real_profile(test)
        for name in recipes:
            cr.install_weights(base, missing, spurious, forms)
            syn = synth_profile(sentences, name)
            for kind in ("comma_add", "comma_del", "form"):
                out[(name, kind)].append(distance(real, syn, kind, ("len",))[0])
    cr.install_weights(*saved)
    return {k: sum(v) / len(v) for k, v in out.items()}


def main():
    mode = sys.argv[1]
    if mode == "real":
        sets = load_dev()
        counts = real_profile(sets["dev"])
        official = new_counts()
        for it in sets["official"]:
            clean_text_stats(official, it["src"], "official_clean")
            gap_rates(official, it["src"], "official")
        counts.update(official)
        print(json.dumps(to_plain(counts), ensure_ascii=False))
    elif mode == "synth":
        path, n, recipe = sys.argv[2], int(sys.argv[3]), sys.argv[4]
        match = share(json.load(open(sys.argv[5]))["sent.len"]) if len(sys.argv) > 5 else None
        sents = load_sentences(path, n, match)
        print(json.dumps(to_plain(synth_profile(sents, recipe)), ensure_ascii=False))
    elif mode == "compare":
        real = json.load(open(sys.argv[2]))
        for path in sys.argv[3:]:
            print(report(real, json.load(open(path)), os.path.basename(path)))
            print()
    elif mode == "cv":
        path, n = sys.argv[2], int(sys.argv[3])
        sentences = load_sentences(path, n)
        for ridge in [float(x) for x in sys.argv[4].split(",")]:
            result = cross_validate(sys.argv[5:], sentences, ridge)
            for (name, kind), v in sorted(result.items()):
                print("ridge %-5g %-14s %-10s held-out TV %.3f" % (ridge, name, kind, v), flush=True)


def load_sentences(path, n, match=None):
    """n random corpus sentences; match = {length bucket: share} resamples them to that length distribution
    (the real documents are shorter than the corpus, which by itself moves the profile of the errors)."""
    rng = random.Random(1)
    sents = [json.loads(line)["src"] for line in open(path, encoding="utf-8")]
    rng.shuffle(sents)
    if not match:
        return sents[:n]
    pools = collections.defaultdict(list)
    for s in sents:
        pools[len_bucket(len(words_of(s)))].append(s)
    out = []
    for bucket, p in match.items():
        out += pools[bucket][:int(round(n * p))]
    rng.shuffle(out)
    return out


if __name__ == "__main__":
    main()
