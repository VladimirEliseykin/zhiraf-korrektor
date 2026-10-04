"""Synthetic error generator with per-word labels for the edit tagger.

Words are regex tokens of the sentence. For every word the tagger predicts:
  comma label: KEEP | ADD (a comma must follow the word) | DEL (the comma after it is wrong)
  form label:  KEEP | "case:gent", "number:plur", "case:datv|number:plur", ... (grammemes to restore)
corrupt() returns the corrupted text and the labels that turn it back into the clean text.
"""
import os
import random
import re
import sys

# word segmentation and inflection come from the engine: labels must align with what the checker splits
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from spellcheck.morph import morph  # noqa: E402
from spellcheck.text import WORD, inflect, words_of  # noqa: E402,F401

CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")
COMMA_KEEP, COMMA_ADD, COMMA_DEL = "KEEP", "ADD", "DEL"
FORM_KEEP = "KEEP"
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


def corrupt(text, rng, p_clean=0.25, max_edits=3, p_single=0.0, p_form=0.45, placement=True):
    """Returns (corrupted_text, comma_labels, form_labels) aligned with words_of(corrupted_text).

    p_form is the share of word-form edits; the rest are comma edits, dropped vs spurious 30:25.
    Comma and form errors need different densities (round 5): realistic rarity of form errors
    cut false form edits, while the same rarity of comma errors cut comma recall."""
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
    drop_cands = [(i, comma_drop_weight(text, ms, i) if placement else 1.0) for i in range(n - 1) if comma_after(text, ms[i])]
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


def restore(text, comma, form):
    """Apply labels to text (inverse of corrupt) using pymorphy for word forms."""
    ms = words_of(text)
    out, last = [], 0
    for i, m in enumerate(ms):
        out.append(text[last:m.start()])
        word = m.group(0)
        if form[i] != FORM_KEEP:
            word = inflect(word, form[i]) or word
        out.append(word)
        last = m.end()
        has = text[last:last + 1] == ","
        if comma[i] == COMMA_ADD and not has:
            out.append(",")
        elif comma[i] == COMMA_DEL and has:
            last += 1
    out.append(text[last:])
    return "".join(out)
