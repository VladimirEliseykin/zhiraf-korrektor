"""Synthetic error generator with per-word labels for the edit tagger.

Words are regex tokens of the sentence. For every word the tagger predicts:
  comma label: KEEP | ADD (a comma must follow the word) | DEL (the comma after it is wrong)
  form label:  KEEP | "case:gent", "number:plur", "case:datv|number:plur", ... (grammemes to restore)
  spell label: KEEP | JOIN (join with the next word) | HYPHEN (join with a hyphen) | SPLIT (split off "не")
               | LOWER | UPPER (first letter of this word); optional, see corrupt_spell()
corrupt() returns the corrupted text and the labels that turn it back into the clean text.
"""
import math
import os
import random
import re
import sys

# word segmentation and inflection come from the engine: labels must align with what the checker splits
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from spellcheck.guards import BIBLIOGRAPHY, LIST_MARKER, protected, quoted_spans  # noqa: E402
from spellcheck.morph import morph  # noqa: E402
from spellcheck.spelling import CAPITAL_LEMMAS, JOINED_TABLE, pair_is_meant_apart  # noqa: E402,F401
from spellcheck.text import WORD, inflect, words_of  # noqa: E402,F401
from error_context import comma_gaps, form_features, prev_group  # noqa: E402

CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")
COMMA_KEEP, COMMA_ADD, COMMA_DEL = "KEEP", "ADD", "DEL"
FORM_KEEP = "KEEP"
SPELL_KEEP, SPELL_JOIN, SPELL_HYPHEN, SPELL_SPLIT, SPELL_LOWER, SPELL_UPPER = \
    "KEEP", "JOIN", "HYPHEN", "SPLIT", "LOWER", "UPPER"
SPELL_LABELS = [SPELL_KEEP, SPELL_JOIN, SPELL_HYPHEN, SPELL_SPLIT, SPELL_LOWER, SPELL_UPPER]
CONJ = {"и", "или", "а", "но", "либо"}
PREPS = {"в", "во", "на", "о", "об", "с", "со", "к", "ко", "по", "из", "от", "до", "для", "при", "за", "под",
         "над", "без", "через", "у", "про", "между", "перед", "согласно", "благодаря", "вследствие", "после"}


def comma_after(text, m):
    return text[m.end():m.end() + 1] == ","


def form_label(original, corrupted_parse_tag, original_tag):
    """Grammemes that differ between the corrupted form and the original one."""
    parts = []
    for cat in ("case", "number", "gender", "person"):
        o, c = getattr(original_tag, cat), getattr(corrupted_parse_tag, cat)
        if o and o != c:
            parts.append("%s:%s" % (cat, o))
    return "|".join(parts) or None


def corrupt_form(word, prev_word, rng):
    """Return (new_word, label) or None. Prefers realistic targets (after prepositions, adjectives, verbs)."""
    if not re.fullmatch(r"[а-яё]+", word) or len(word) < 3:
        return None
    parse = morph.parse(word)[0]
    if parse.score < 0.5:
        return None
    tag = parse.tag
    options = []
    # Round 1 lesson: noun number and verb person are usually the author's free choice
    # ("модель угроз", "рассмотрим"), so corrupting them taught the model false fixes.
    if tag.POS == "NOUN" and tag.case:
        weight = 3 if prev_word in PREPS else 1
        options += [{case} for case in CASES if case != tag.case] * weight
    elif tag.POS in ("ADJF", "PRTF") and tag.case:
        options += [{case} for case in CASES if case != tag.case] * 2
        if tag.number:
            options.append({"plur" if tag.number == "sing" else "sing"})
        if tag.gender and tag.number == "sing":
            options += [{g} for g in ("masc", "femn", "neut") if g != tag.gender]
    elif tag.POS == "VERB" and tag.number and tag.person in (None, "3per"):
        options += [{"plur" if tag.number == "sing" else "sing"}] * 2
        if tag.gender:
            options += [{g} for g in ("masc", "femn", "neut") if g != tag.gender]
    elif tag.POS in ("PRTS", "ADJS") and tag.number:
        # round 4: short forms as predicates ("Определение … описано ранее")
        options += [{"plur" if tag.number == "sing" else "sing"}] * 2
        if tag.gender:
            options += [{g} for g in ("masc", "femn", "neut") if g != tag.gender]
    rng.shuffle(options)
    readings = {p.word for p in morph.parse(word)}
    for grammemes in options:
        new = parse.inflect(grammemes)
        if not new or new.word in readings:
            continue
        # the corrupted string must not be an equally valid reading of the original grammar
        if any(p.tag == tag for p in morph.parse(new.word)):
            continue
        label = form_label(word, new.tag, tag)
        if label:
            return new.word, label
    return None


INSTRUMENTAL_OPENERS = {"путем", "путём", "посредством", "согласно", "благодаря", "вследствие"}


def spurious_comma_plausible(ms, i, nxt):
    """Places where people really put a wrong comma after word i."""
    if nxt in CONJ and nxt in ("и", "или"):
        return True                      # "ролями, и за лицами"
    if nxt in INSTRUMENTAL_OPENERS:
        return True                      # "в БД, путем открытия"
    if 1 <= i <= 6 and ms[0].group(0).lower() in PREPS | {"при", "после", "для", "в", "во", "на"}:
        return True                      # "При выполнении задания, пользователь ..."
    word = ms[i].group(0).lower()
    p_word, p_next = morph.parse(word)[0], morph.parse(nxt)[0]
    if p_word.tag.POS == "NOUN" and p_next.tag.POS == "VERB":
        return True                      # "Рынок услуг, сформировался"
    return False


PREDICATIVE_VERBS = re.compile(r"^(являет|являют|являл|считает|считают|считал|станов|стал|служит|служат)")
SUBORD_NEXT = {"который", "которая", "которое", "которые", "которого", "которой", "которых", "что", "чтобы",
               "если", "когда", "поскольку", "хотя", "так", "такие", "так как", "где", "куда", "как"}


def form_weight(text, ms, i):
    """Round 4: corrupt word forms more often where people really get endings wrong."""
    w = ms[i].group(0).lower()
    parse = morph.parse(w)[0]
    pos = parse.tag.POS
    weight = 1.0
    before = text[max(0, ms[i].start() - 2):ms[i].start()]
    prev = ms[i - 1].group(0).lower() if i else ""
    prev2 = ms[i - 2].group(0).lower() if i > 1 else ""
    if pos == "PRTF" and "," in before:
        weight *= 3            # participial phrase after its noun: "документации…, связанной"
    if prev in ("и", "или") or (prev2, prev) == ("то", "есть"):
        weight *= 2            # coordinated objects / apposition keep the case
    if pos == "ADJF" and i + 1 < len(ms) and ms[i + 1].group(0).isupper() and len(ms[i + 1].group(0)) > 1:
        weight *= 3            # adjective before an abbreviation: "прикладного ПО"
    if parse.tag.case == "ablt" and any(PREDICATIVE_VERBS.match(ms[j].group(0).lower())
                                        for j in range(max(0, i - 3), min(len(ms), i + 4))):
        weight *= 3            # "Одним из способов является …"
    if pos in ("PRTS", "ADJS"):
        weight *= 2            # "Определение … описано"
    return weight


def comma_drop_weight(text, ms, i):
    """Round 4: the commas people actually forget."""
    weight = 1.0
    nxt = ms[i + 1].group(0).lower() if i + 1 < len(ms) else ""
    first_comma = "," not in text[:ms[i].end()]
    if first_comma and ms[0].group(0).lower() in PREPS | {"исходя", "учитывая", "таким", "кроме", "поскольку", "если", "когда"}:
        weight *= 3            # introductory phrase: "Исходя из анализа данных, …"
    if nxt in SUBORD_NEXT:
        weight *= 3            # before a subordinate clause / "такие как"
    if nxt and morph.parse(nxt)[0].tag.POS in ("PRTF", "GRND"):
        weight *= 3            # before a participial or adverbial phrase
    return weight


def weighted_pick(rng, items):
    total = sum(w for _, w in items)
    r = rng.random() * total
    for x, w in items:
        r -= w
        if r <= 0:
            return x
    return items[-1][0]


def corrupt(text, rng, p_clean=0.25, max_edits=3, p_single=0.0, p_form=0.45, placement=True,
            realistic=False, error_rate=1.0, form_scale=1.0):
    """Returns (corrupted_text, comma_labels, form_labels) aligned with words_of(corrupted_text).

    p_form is the share of word-form edits; the rest are comma edits, dropped vs spurious 30:25.
    Comma and form errors need different densities (round 5): realistic rarity of form errors
    cut false form edits, while the same rarity of comma errors cut comma recall.
    realistic=True switches to corrupt_realistic() (round 9); every other flag keeps the old recipes bit for bit."""
    if realistic:
        return corrupt_realistic(text, rng, error_rate=error_rate, max_edits=max_edits, form_scale=form_scale)
    p_drop = p_form + (1 - p_form) * 0.30 / 0.55
    ms = words_of(text)
    n = len(ms)
    comma = [COMMA_KEEP] * n
    form = [FORM_KEEP] * n
    if n < 4 or rng.random() < p_clean:
        return text, comma, form
    edits = 1 if (max_edits == 1 or rng.random() < p_single) else rng.randint(1, max_edits)
    pieces = {}           # word index -> replacement word
    drop_comma = set()    # word index whose following comma is removed
    add_comma = set()     # word index after which a spurious comma is inserted
    form_cands = [(i, form_weight(text, ms, i) if placement else 1.0) for i in range(n)]
    # a comma glued to the next word is a decimal one ("27,5"): dropping it merges two words into one
    drop_cands = [(i, comma_drop_weight(text, ms, i) if placement else 1.0) for i in range(n - 1)
                  if comma_after(text, ms[i]) and text[ms[i].end() + 1:ms[i].end() + 2] != ms[i + 1].group(0)[:1]]
    add_cands = []
    for i in range(n - 1):
        w = ms[i].group(0)
        if not comma_after(text, ms[i]) and text[ms[i].end():ms[i].end() + 1] == " " \
                and ms[i + 1].start() == ms[i].end() + 1 and w.lower() not in PREPS and w.lower() not in CONJ \
                and spurious_comma_plausible(ms, i, ms[i + 1].group(0).lower()):
            add_cands.append((i, 1.0))
    attempts = 0
    while edits > 0 and attempts < 12:
        attempts += 1
        kind = rng.random()
        if kind < p_form and form_cands:
            i = weighted_pick(rng, form_cands)
            w = ms[i].group(0)
            res = corrupt_form(w, ms[i - 1].group(0).lower() if i else "", rng)
            if res and i not in pieces:
                new, label = res
                pieces[i] = new if w[0].islower() else new.capitalize()
                form[i] = label
                edits -= 1
        elif kind < p_drop and drop_cands:
            i = weighted_pick(rng, drop_cands)
            if i not in drop_comma:
                drop_comma.add(i)
                comma[i] = COMMA_ADD
                edits -= 1
        elif add_cands:
            i = weighted_pick(rng, add_cands)
            if i not in add_comma:
                add_comma.add(i)
                comma[i] = COMMA_DEL
                edits -= 1
    out, last = [], 0
    for i, m in enumerate(ms):
        out.append(text[last:m.start()])
        out.append(pieces.get(i, m.group(0)))
        last = m.end()
        if i in drop_comma:
            last += 1  # skip the comma that followed this word
        if i in add_comma:
            out.append(",")
    out.append(text[last:])
    return "".join(out), comma, form


# ---- realistic errors (round 9) -------------------------------------------------------------------------
# How the weights below were measured (counts only, no sentences; reproduce with train/fit_realistic.py):
#  1. On the DEV gold (1550 real sentences, 24.7k words) every gold edit of the kinds "missing comma" (37),
#     "spurious comma" (28) and "wrong word form" (44) is put into contexts by train/error_context.py: ctx = the class
#     of the comma gap / word, where = position in the sentence, first_comma = no comma before it in the sentence,
#     prev = part of speech before the gap. *_COUNTS holds (events, places): how many gold edits fell on a value
#     and how many places with that value the dev sentences have (gaps with a comma for missing commas, gaps
#     without one for spurious commas, words that can take a wrong form for forms). The test split was never read.
#  2. A Poisson log-linear model rate(place) = BASE_RATE * product of the weights of the place's feature values is
#     fitted to these events by penalised maximum likelihood (fit_loglinear), so correlated features (a closing comma
#     sits late in the sentence) do not count twice. The counts are tiny, so a ridge penalty pulls every weight
#     towards 1 (for the spurious comma between a subject and its verb, a textbook error that dev happens not to
#     show, towards PRIOR_FACTOR = 2); the penalty (RIDGE in fit_realistic.py) was chosen by 5-fold cross-
#     validation over whole documents on the held-out Poisson log-likelihood: +0.14 / +0.43 nats per event over the
#     uniform rate for missing / spurious commas, where the round-4 heuristics of corrupt() score -0.21 / -0.18
#     (worse than uniform: that is why the uniform recipe won). For word forms the fitted contexts alone gain only
#     +0.02, the round-4 heuristics +0.11 and both together +0.12, so forms keep the heuristics (form_weight) and the
#     fitted context table only corrects them. BASE_RATE is the probability of an error per place in real documents.
#  3. The generator makes an error at every place independently with probability error_rate * rate(place), error_rate
#     = 1 being the real density; training uses a much denser one. So the number of errors of a sentence follows
#     its length and its error-prone places, as in real text (0.013 / 0.038 / 0.127 / 0.127 / 0.111 errors per sentence
#     for <8 / 8-15 / 16-25 / 26-40 / >40 words in dev), and the mix of the three kinds is the real one.
MISSING_COUNTS = {
    "ctx": {"other": (6, 449), "participle_phrase": (11, 304), "subord": (4, 292), "homogeneous": (1, 185), "closing_phrase": (8, 130), "advers": (0, 95), "closing_lead": (0, 71), "phrase_marker": (1, 70), "after_conj_or_intro": (1, 36), "and_or": (4, 29), "subject_verb": (1, 27), "verb_object": (0, 3)},
    "where": {"middle": (8, 563), "tail": (6, 422), "head(4-7)": (11, 405), "start(<=3)": (12, 301)},
    "first_comma": {"later": (18, 849), "first": (19, 842)},
    "prev": {"NOUN": (31, 1283), "ADJ": (2, 146), "rest": (3, 133), "VERB": (0, 71), "CONJ": (1, 58)},
}
SPURIOUS_COUNTS = {
    "ctx": {"other": (7, 8597), "closing_lead": (6, 1636), "closing_phrase": (3, 1571), "homogeneous": (0, 1179), "and_or": (6, 893), "verb_object": (0, 860), "subject_verb": (0, 519), "participle_phrase": (2, 507), "after_conj_or_intro": (3, 347), "subord": (1, 129), "phrase_marker": (0, 27), "advers": (0, 10)},
    "where": {"start(<=3)": (9, 4626), "tail": (3, 4405), "head(4-7)": (9, 3859), "middle": (7, 3385)},
    "first_comma": {"first": (22, 8957), "later": (6, 7318)},
    "prev": {"NOUN": (20, 7805), "ADJ": (1, 3909), "rest": (3, 2666), "VERB": (1, 1486), "CONJ": (3, 409)},
}
FORM_COUNTS = {"adj_noun_agreement": (5, 3920), "noun_noun_chain": (8, 3647), "noun_after_adj": (3, 2776), "after_preposition": (7, 2320), "predicate": (7, 1727), "other": (4, 1496), "verb_object": (1, 614), "participle_after_noun": (6, 545), "after_numeral": (2, 105), "adj_no_head_right": (1, 61)}
P_MAX = 0.6           # no place is certain to carry an error, however dense the recipe
PRIOR_FACTOR = {"SPURIOUS": {"ctx": {"subject_verb": 2.0}}}   # prior weight (not a count) of a value
FORM_HEURISTIC_MEAN = 1.1138
BASE_RATE = {"missing": 0.01775, "spurious": 0.00099, "form": 0.00237}
MISSING_WEIGHT = {
    "ctx": {"and_or": 3.52, "closing_phrase": 2.58, "participle_phrase": 1.63, "subject_verb": 1.3, "after_conj_or_intro": 1.21, "verb_object": 1.12, "phrase_marker": 1.01, "subord": 0.835, "other": 0.771, "closing_lead": 0.662, "advers": 0.662, "homogeneous": 0.629},
    "where": {"start(<=3)": 2.28, "head(4-7)": 1.35, "tail": 0.7, "middle": 0.677},
    "first_comma": {"later": 1.17, "first": 0.855},
    "prev": {"NOUN": 1.1, "rest": 0.933, "ADJ": 0.737, "CONJ": 0.702, "VERB": 0.5},
}
SPURIOUS_WEIGHT = {
    "ctx": {"and_or": 3.67, "after_conj_or_intro": 3.35, "subord": 2.37, "closing_phrase": 2.04, "participle_phrase": 1.87, "closing_lead": 1.85, "advers": 1.36, "phrase_marker": 1.32, "subject_verb": 0.939, "verb_object": 0.799, "other": 0.694, "homogeneous": 0.517},
    "where": {"middle": 1.44, "head(4-7)": 1.2, "start(<=3)": 0.932, "tail": 0.694},
    "first_comma": {"first": 1.6, "later": 0.561},
    "prev": {"CONJ": 2.41, "NOUN": 1.66, "rest": 0.956, "VERB": 0.672, "ADJ": 0.396},
}
FORM_WEIGHT = {"participle_after_noun": 1.66, "after_numeral": 1.4, "predicate": 1.28, "adj_no_head_right": 1.25, "after_preposition": 1.16, "noun_noun_chain": 1.07, "other": 1.07, "verb_object": 1.07, "noun_after_adj": 0.857, "adj_noun_agreement": 0.762}

# the wrong case that stood in the text, over the 33 real case errors (counts + 1): people write the unmarked
# nominative or genitive far more often than a dative or an instrumental
WRONG_CASE = {"nomn": 11, "gent": 15, "accs": 3, "datv": 3, "ablt": 3, "loct": 4}
# share of the non-case grammemes among the form errors of a part of speech (real: 15 of 44 are not case errors;
# the noun after a numeral takes number errors, participles and verbs gender and number)
FORM_KIND_WEIGHTS = {
    "NOUN": {"case": 0.93, "number": 0.07}, "NOUN:after_numeral": {"case": 0.2, "number": 0.8},
    "NOUN:noun_after_adj": {"case": 0.75, "number": 0.25},
    "ADJF": {"case": 0.6, "gender": 0.2, "number": 0.2}, "PRTF": {"case": 0.6, "gender": 0.2, "number": 0.2},
    "VERB": {"number": 0.45, "gender": 0.55}, "PRTS": {"number": 0.45, "gender": 0.55},
    "ADJS": {"number": 0.45, "gender": 0.55},
}


def install_weights(base=None, missing=None, spurious=None, forms=None):
    """Replace the rates (the cross-validation uses this); None keeps a table."""
    global BASE_RATE, MISSING_WEIGHT, SPURIOUS_WEIGHT, FORM_WEIGHT
    BASE_RATE = BASE_RATE if base is None else base
    MISSING_WEIGHT = MISSING_WEIGHT if missing is None else missing
    SPURIOUS_WEIGHT = SPURIOUS_WEIGHT if spurious is None else spurious
    FORM_WEIGHT = FORM_WEIGHT if forms is None else forms


def comma_weight(weights, feats):
    w = 1.0
    for name, rates in weights.items():
        value = prev_group(feats["prev_pos"]) if name == "prev" else feats[name]
        w *= rates.get(value, 1.0)
    return w


def comma_candidates(text, ms):
    """(missing, spurious): places where a comma can be dropped / wrongly added, each (word index, features)."""
    drop, add = [], []
    for i, has, feats in comma_gaps(text, ms):
        gap = text[ms[i].end():ms[i + 1].start()]
        # a comma glued to the next word is a decimal one ("27,5"): dropping it merges two words into one
        if has and gap.startswith(", "):
            drop.append((i, feats))
        elif not has and gap == " " and ms[i].group(0).lower() not in PREPS and ms[i].group(0).lower() not in CONJ:
            add.append((i, feats))
    return drop, add


def form_candidates(text, ms):
    """Words that can take a wrong form: (word index, context, round-4 heuristic weight of the place)."""
    out = []
    for i, m in enumerate(ms):
        w = m.group(0)
        if re.fullmatch(r"[А-Яа-яЁё]+", w) and len(w) >= 3 and morph.parse(w.lower())[0].tag.POS in FORM_KIND_WEIGHTS:
            out.append((i, form_features(text, ms, i, set())["ctx"], form_weight(text, ms, i)))
    return out


def poisson(rng, mean):
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def weighted_order(rng, items):
    """Items in random order, heavier ones earlier (Efraimidis-Spirakis weighted sampling without replacement)."""
    keyed = [(rng.random() ** (1.0 / w) if w > 0 else 0.0, x) for x, w in items]
    keyed.sort(key=lambda kx: -kx[0])
    return [x for _, x in keyed]


def corrupt_form_realistic(word, ctx, rng):
    """Like corrupt_form(), with the wrong case and the kind of grammeme drawn as people really get them wrong."""
    if not re.fullmatch(r"[а-яё]+", word) or len(word) < 3:
        return None
    parse = morph.parse(word)[0]
    if parse.score < 0.5:
        return None
    tag = parse.tag
    pos = tag.POS or ""
    kinds = FORM_KIND_WEIGHTS.get(pos + ":" + ctx) or FORM_KIND_WEIGHTS.get(pos)
    if not kinds:
        return None
    options = []
    if "case" in kinds and tag.case and pos in ("NOUN", "ADJF", "PRTF"):
        total = sum(WRONG_CASE[c] for c in CASES if c != tag.case)
        options += [({c}, kinds["case"] * WRONG_CASE[c] / total) for c in CASES if c != tag.case]
    if "number" in kinds and tag.number:
        options.append(({"plur" if tag.number == "sing" else "sing"}, kinds["number"]))
    if "gender" in kinds and tag.gender and (tag.number == "sing" or pos in ("VERB", "PRTS", "ADJS")):
        others = [g for g in ("masc", "femn", "neut") if g != tag.gender]
        options += [({g}, kinds["gender"] / len(others)) for g in others]
    readings = {p.word for p in morph.parse(word)}
    for grammemes in weighted_order(rng, options):
        new = parse.inflect(grammemes)
        if not new or new.word in readings:
            continue
        if any(p.tag == tag for p in morph.parse(new.word)):
            continue
        label = form_label(word, new.tag, tag)
        # the label must bring the original word back through the same inflection restore() uses
        if label and inflect(new.word, label) == word:
            return new.word, label
    return None


def corrupt_realistic(text, rng, error_rate=10.0, max_edits=4, form_scale=1.0):
    """Errors as real people make them (see the tables above).

    Every place where a comma can be dropped, a spurious comma added or a word form spoilt gets an error
    independently, with probability error_rate * its measured rate (error_rate 1 = real documents, about 0.13 errors
    per sentence of 16+ words; training uses a denser one on purpose; form_scale boosts the forms against the
    commas). The wrong case and the grammeme kind follow the real counts. At most max_edits errors are kept
    (a random subset). Returns the same (text, comma, form) as corrupt()."""
    ms = words_of(text)
    n = len(ms)
    comma = [COMMA_KEEP] * n
    form = [FORM_KEEP] * n
    if n < 4:
        return text, comma, form
    drop, add = comma_candidates(text, ms)
    picks = []
    for kind, cands, table, base in (("drop", drop, MISSING_WEIGHT, BASE_RATE["missing"]),
                                     ("add", add, SPURIOUS_WEIGHT, BASE_RATE["spurious"])):
        for i, feats in cands:
            if rng.random() < min(P_MAX, error_rate * base * comma_weight(table, feats)):
                picks.append((kind, i, None))
    for i, ctx, heuristic in form_candidates(text, ms):
        # round-4 heuristics (participle after its noun, coordinated objects, ...) held out better than the fitted
        # contexts alone, so the fitted context table corrects them instead of replacing them
        rate = BASE_RATE["form"] * FORM_WEIGHT.get(ctx, 1.0) * (0.9 * heuristic / FORM_HEURISTIC_MEAN + 0.1)
        if rng.random() < min(P_MAX, error_rate * form_scale * rate):
            picks.append(("form", i, ctx))
    if len(picks) > max_edits:
        rng.shuffle(picks)
        picks = picks[:max_edits]
    pieces, drop_comma, add_comma = {}, set(), set()
    for kind, i, ctx in picks:
        if kind == "drop":
            drop_comma.add(i)
            comma[i] = COMMA_ADD
        elif kind == "add":
            add_comma.add(i)
            comma[i] = COMMA_DEL
        else:
            w = ms[i].group(0)
            res = corrupt_form_realistic(w.lower(), ctx, rng)
            if res:
                new, label = res
                pieces[i] = new if w[0].islower() else new.capitalize()
                form[i] = label
    out, last = [], 0
    for i, m in enumerate(ms):
        out.append(text[last:m.start()])
        out.append(pieces.get(i, m.group(0)))
        last = m.end()
        if i in drop_comma:
            last += 1  # skip the comma that followed this word
        if i in add_comma:
            out.append(",")
    out.append(text[last:])
    return "".join(out), comma, form


def restore(text, comma, form, spell=None):
    """Apply labels to text (inverse of corrupt) using pymorphy for word forms.

    spell (optional, from corrupt_spell) is aligned with the words of text like the other labels;
    JOIN/HYPHEN remove the single space after the word, SPLIT puts a space after "не"."""
    ms = words_of(text)
    out, last = [], 0
    separator = None
    for i, m in enumerate(ms):
        out.append(text[last:m.start()] if separator is None else separator)
        separator = None
        word = m.group(0)
        if form[i] != FORM_KEEP:
            word = inflect(word, form[i]) or word
        label = spell[i] if spell else SPELL_KEEP
        if label == SPELL_LOWER:
            word = word[:1].lower() + word[1:]
        elif label == SPELL_UPPER:
            word = word[:1].upper() + word[1:]
        elif label == SPELL_SPLIT:
            word = word[:2] + " " + word[2:]
        out.append(word)
        last = m.end()
        has = text[last:last + 1] == ","
        if comma[i] == COMMA_ADD and not has:
            out.append(",")
        elif comma[i] == COMMA_DEL and has:
            last += 1
        if label in (SPELL_JOIN, SPELL_HYPHEN) and i + 1 < len(ms) and text[last:ms[i + 1].start()] == " ":
            separator = "" if label == SPELL_JOIN else "-"
            last = ms[i + 1].start()
    out.append(text[last:])
    return "".join(out)


# ---- spelling corruptions (round 8): split/joined words, hyphens, wrong capitals ----------------------
# Every edit needs context to be judged ("по этому вопросу" is right, "по этому" for "поэтому" is not),
# so the labels are only generated from clean text and the word stays untouched wherever it is ambiguous.

# prefixes people really split off in documents; "не" dominates ("не закрытых", "не выполнение")
SPLIT_PREFIXES = (("не", 5), ("сверх", 1), ("меж", 1), ("само", 1), ("анти", 1), ("контр", 1), ("микро", 1),
                  ("макро", 1), ("мульти", 1), ("обще", 1), ("много", 1), ("вне", 1), ("внутри", 1),
                  ("средне", 1), ("высоко", 1), ("псевдо", 1), ("квази", 1))
NE_POS = {"ADJF", "PRTF", "ADVB", "NOUN"}
NE_STOP = {"некоторый", "некий", "несколько", "нечто", "некто", "нельзя", "небо", "неделя", "невеста"}
HYPHEN_PARTICLES = {"то", "либо", "нибудь", "таки", "кое"}
HYPHEN_PREFIXES = {"по", "во", "в", "из", "кое"}
GEO_MARKERS = {"город", "городе", "города", "г", "области", "республике", "республики", "районе", "краю"}
NAME_GRAMMEMES = ("Name", "Surn", "Patr")
NOT_COMMON = ("Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad")
# Per-kind rates: a sentence that has a place for the kind gets the error with probability p_spell * rate.
# Places for LOWER are in nearly every sentence, places for JOIN/SPLIT in about one in fifteen, so the
# rates are what balances the label counts (see the report for the measured shares).
SPELL_RATES = {"join": 4.0, "hyphen": 3.0, "split": 4.0, "lower": 0.5, "upper": 0.4}
CYRILLIC_WORD = re.compile(r"[А-Яа-яЁё]+")


def prefix_split(word):
    """Length of the prefix to cut off a compound ("незакрытых" -> 2) and its weight, or None.

    Only genuine compounds count: the lemma of the whole word must be prefix + the lemma of the rest,
    so "небо", "неделя", "самолёт", "постановление" are never split."""
    lw = word.lower()
    for prefix, weight in SPLIT_PREFIXES:
        rest = lw[len(prefix):]
        if not lw.startswith(prefix) or len(rest) < (4 if prefix == "не" else 5) or not morph.word_is_known(rest):
            continue
        whole, part = morph.parse(lw)[0], morph.parse(rest)[0]
        if whole.normal_form != prefix + part.normal_form:
            continue
        if prefix == "не" and (whole.tag.POS not in NE_POS or whole.normal_form in NE_STOP):
            continue
        if prefix == "не" and whole.tag.POS in ("ADJF", "PRTF"):
            weight /= 2  # "не закрытых" is often right apart ("не закрытых договоров"): half the weight
        return len(prefix), weight
    return None


def spell_candidates(c, ms, comma, form):
    """Places where a spelling error can be made in c: kind -> [(word index, weight, payload)]."""
    cands = {"join": [], "hyphen": [], "split": [], "lower": [], "upper": []}
    if BIBLIOGRAPHY.search(c):
        return cands
    quotes = quoted_spans(c)
    marker = len(LIST_MARKER.match(c).group(0)) if LIST_MARKER.match(c) else 0
    first = next((i for i, m in enumerate(ms) if m.start() >= marker), None)

    def plain(i):
        m = ms[i]
        return form[i] == FORM_KEEP and not protected(m.group(0)) and not any(a < m.start() < b for a, b in quotes)

    def gap(i):
        return c[ms[i].end():ms[i + 1].start()] if i + 1 < len(ms) else None

    for i, m in enumerate(ms):
        w = m.group(0)
        if not plain(i) or m.start() < marker:
            continue
        if "-" in w and w.count("-") == 1:
            a, b = w.split("-")
            # "заво-да" at a line break is not a compound: its joined form is a word. The second part must be a
            # word (or the first a prefix/particle: "по-русски", "кое-что") so that only real compounds are used
            if CYRILLIC_WORD.fullmatch(a) and CYRILLIC_WORD.fullmatch(b) and not morph.word_is_known((a + b).lower()) \
                    and (morph.word_is_known(b.lower()) or a.lower() in HYPHEN_PREFIXES or b.lower() in HYPHEN_PARTICLES):
                weight = 2.0 if b.lower() in HYPHEN_PARTICLES or a.lower() in HYPHEN_PREFIXES else 1.0
                cands["hyphen"].append((i, weight, len(a)))
            continue
        if not CYRILLIC_WORD.fullmatch(w):
            continue
        low = w.lower()
        if low in JOINED_TABLE:
            cut = JOINED_TABLE[low]
            nxt = ms[i + 1].group(0).lower() if i + 1 < len(ms) and gap(i) == " " else ""
            # "так же как", "то же самое", "что бы ни" are the right spelling: the split would teach a false alarm
            if not (pair_is_meant_apart(low[:cut], low[cut:], nxt) or low == "чтобы" and nxt == "ни"):
                cands["join"].append((i, 2.0, cut))
        elif len(w) >= 6:
            cut = prefix_split(w)
            if cut:
                cands["join"].append((i, float(cut[1]), cut[0]))
        if low == "не" and gap(i) == " " and plain(i + 1) and comma[i] == COMMA_KEEP:
            nxt = ms[i + 1].group(0)
            parse = morph.parse(nxt.lower())[0] if CYRILLIC_WORD.fullmatch(nxt) and len(nxt) >= 3 else None
            if parse and parse.score >= 0.5 and parse.tag.POS in ("VERB", "INFN", "GRND") \
                    and not morph.word_is_known(low + nxt.lower()):
                cands["split"].append((i, 1.0, None))
        if len(w) < 3 or not w.isalpha() or i == 0 and first != 0:
            continue
        parse = morph.parse(low)[0]
        if parse.score < 0.4:
            continue
        if w[0].islower() and i > 0 and len(w) >= 4 and parse.score >= 0.5 and parse.tag.POS == "NOUN" \
                and not any(g in parse.tag for g in NOT_COMMON) and gap(i - 1) == " " and ms[i - 1].group(0)[:1].isalpha() \
                and parse.normal_form not in CAPITAL_LEMMAS:
            # title words ("Министерство", "Закон") are capitalised in official text: no LOWER place for them
            cands["lower"].append((i, 1.0, None))
        elif w[0].isupper() and w[1:].islower():
            if i == first:
                cands["upper"].append((i, 1.0, None))
            elif any(g in parse.tag for g in NAME_GRAMMEMES):
                near = [j for j in (i - 1, i + 1) if 0 <= j < len(ms) and ms[j].group(0)[:1].isupper()
                        and any(g in morph.parse(ms[j].group(0).lower())[0].tag for g in NAME_GRAMMEMES)
                        and gap(min(i, j)) == " "]
                if near:
                    cands["upper"].append((i, 2.0, None))
            elif "Geox" in parse.tag and i > 0 and ms[i - 1].group(0).lower() in GEO_MARKERS and gap(i - 1) == " ":
                cands["upper"].append((i, 2.0, None))
    return cands


def corrupt_spell(text, rng, p_spell=0.0, rates=None, max_spell=2, **kwargs):
    """Like corrupt(), plus spelling errors; returns (corrupted, comma, form, spell).

    kwargs go to corrupt() unchanged, which runs first and consumes the random numbers exactly as
    before; the spelling pass then works on its output. p_spell scales SPELL_RATES (or rates): each kind
    that has a place in the sentence is applied with probability p_spell * rate, at most max_spell edits.
    With p_spell == 0 the result is corrupt()'s plus all-KEEP spell labels and rng is not touched afterwards.

    Alignment: all label lists are aligned with words_of(corrupted). A split word (JOIN/HYPHEN) becomes two
    words and its label sits on the first one; its comma label moves to the second one, where the comma
    follows. SPLIT merges "не" with the verb into one word labelled SPLIT; its comma label comes from the
    verb. Words that already carry a form error are never touched, so labels never interact."""
    c, comma, form = corrupt(text, rng, **kwargs)
    spell = [SPELL_KEEP] * len(comma)
    if p_spell <= 0:
        return c, comma, form, spell
    ms = words_of(c)
    cands = spell_candidates(c, ms, comma, form)
    rates = rates or SPELL_RATES
    kinds = [k for k in ("join", "hyphen", "split", "lower", "upper") if cands[k] and rng.random() < p_spell * rates.get(k, 0.0)]
    rng.shuffle(kinds)
    plan = {}  # word index -> (kind, payload)
    used = set()
    for kind in kinds[:max_spell]:
        choices = [(x, x[1]) for x in cands[kind] if x[0] not in used and (kind != "split" or x[0] + 1 not in used)]
        if not choices:
            continue
        i, _, payload = weighted_pick(rng, choices)
        plan[i] = (kind, payload)
        used.add(i)
        if kind == "split":
            used.add(i + 1)
    if not plan:
        return c, comma, form, spell
    out, new_comma, new_form, new_spell = [], [], [], []
    last, skip = 0, False
    for i, m in enumerate(ms):
        if skip:
            skip = False
            continue
        out.append(c[last:m.start()])
        w = m.group(0)
        last = m.end()
        kind, payload = plan.get(i, (None, None))
        if kind in ("join", "hyphen"):
            out.append(w[:payload] + " " + w[payload + (kind == "hyphen"):])
            new_spell += [SPELL_JOIN if kind == "join" else SPELL_HYPHEN, SPELL_KEEP]
            new_comma += [COMMA_KEEP, comma[i]]
            new_form += [FORM_KEEP, form[i]]
        elif kind == "split":
            nxt = ms[i + 1]
            out.append(w + nxt.group(0))
            last = nxt.end()
            new_spell.append(SPELL_SPLIT)
            new_comma.append(comma[i + 1])
            new_form.append(form[i + 1])
            skip = True
        else:
            if kind == "lower":      # a common noun written with a capital: the label says "make it lower"
                w = w[:1].upper() + w[1:]
            elif kind == "upper":
                w = w[:1].lower() + w[1:]
            out.append(w)
            new_spell.append(SPELL_LOWER if kind == "lower" else SPELL_UPPER if kind == "upper" else SPELL_KEEP)
            new_comma.append(comma[i])
            new_form.append(form[i])
    out.append(c[last:])
    result = "".join(out)
    if len(words_of(result)) != len(new_spell):
        return c, comma, form, spell  # never ship misaligned labels
    return result, new_comma, new_form, new_spell
