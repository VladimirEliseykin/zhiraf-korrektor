"""Context classifiers shared by the error generator (corrupt.py) and the error profiler (error_profile.py).

A comma gap (after word i) and a word with a possible form error are each put into one coarse context
("ctx"), the unit in which real and synthetic errors are compared and in which the realistic generator
weights its choices. Pure functions of the sentence: no randomness, no corpus statistics.
"""
import functools
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from spellcheck.morph import morph  # noqa: E402

PREPS = {"в", "во", "на", "о", "об", "с", "со", "к", "ко", "по", "из", "от", "до", "для", "при", "за", "под",
         "над", "без", "через", "у", "про", "между", "перед", "согласно", "благодаря", "вследствие", "после"}

SUBORD = {"который", "которая", "которое", "которые", "которого", "которой", "которых", "которому", "которым",
          "которой", "котором", "которую", "что", "чтобы", "если", "когда", "поскольку", "хотя", "пока", "где",
          "куда", "откуда", "как", "будто", "словно", "чем", "прежде", "после", "потому", "ибо", "ли", "либо",
          "кто", "чего", "чему", "чем", "почему", "зачем", "сколько", "какой", "какая", "какие", "каких", "каким",
          "каков", "причем", "причём", "тогда", "так", "пусть", "едва", "лишь", "несмотря", "независимо"}
ADVERS = {"а", "но", "однако", "зато", "да", "же"}
INTRO = {"однако", "например", "конечно", "впрочем", "кстати", "следовательно", "итак", "значит", "наконец", "наверное",
         "очевидно", "возможно", "вероятно", "безусловно", "действительно", "разумеется", "видимо", "пожалуй",
         "во-первых", "во-вторых", "в-третьих", "вообще", "таким", "кроме", "иными", "другими", "словом", "прежде",
         "в", "по", "к", "на", "с", "согласно", "исходя", "учитывая", "основываясь", "помимо", "несмотря"}
INTRO_PURE = {"однако", "например", "конечно", "впрочем", "кстати", "следовательно", "итак", "значит", "наконец",
              "очевидно", "возможно", "вероятно", "безусловно", "действительно", "разумеется", "видимо", "пожалуй",
              "во-первых", "во-вторых", "в-третьих", "вообще", "словом", "таким", "кроме"}
LEAD_PHRASE = {"в", "во", "на", "по", "при", "после", "для", "с", "со", "к", "ко", "из", "от", "до", "за", "под",
               "над", "без", "через", "согласно", "исходя", "учитывая", "кроме", "помимо", "несмотря", "таким",
               "поскольку", "если", "когда", "хотя", "так", "пока", "чтобы", "благодаря", "вследствие", "ввиду",
               "в", "у", "о", "об", "между", "перед", "как", "будучи"}
PREPOSITIONS = PREPS | {"возле", "около", "вокруг", "среди", "внутри", "вне", "кроме", "помимо", "посредством",
                           "путем", "путём", "относительно", "касательно", "вместо", "ради", "из-за", "из-под",
                           "насчет", "навстречу", "вдоль", "поперёк", "против", "сквозь", "ввиду", "в", "с"}
LEN_BUCKETS = ((8, "<8"), (16, "8-15"), (26, "16-25"), (41, "26-40"), (10 ** 9, ">40"))


def len_bucket(n):
    for hi, name in LEN_BUCKETS:
        if n < hi:
            return name


@functools.lru_cache(maxsize=100000)
def _parse(word):
    return morph.parse(word)[0]


def pos_of(word):
    p = _parse(word.lower())
    return p.tag.POS or "OTHER", p


def coarse_pos(word):
    if not word:
        return "NONE"
    if re.fullmatch(r"[0-9]+(?:[-‑][0-9A-Za-zА-Яа-я]+)*", word):
        return "NUM"
    if not re.search(r"[А-Яа-яЁё]", word):
        return "LATIN" if re.search(r"[A-Za-z]", word) else "OTHER"
    pos = pos_of(word)[0]
    return {"NOUN": "NOUN", "ADJF": "ADJ", "PRTF": "PRTF", "ADJS": "ADJ", "PRTS": "VERB", "VERB": "VERB",
            "INFN": "INFN", "GRND": "GRND", "ADVB": "ADVB", "PREP": "PREP", "CONJ": "CONJ", "NPRO": "PRON",
            "NUMR": "NUM", "PRCL": "PART", "COMP": "ADVB", "PRED": "ADVB", "INTJ": "OTHER"}.get(pos, "OTHER")


PHRASE_MARKERS = {("в", "отличие"), ("в", "частности"), ("в", "том"), ("в", "связи"), ("по", "сравнению"), ("а", "также"),
                  ("как", "и"), ("так", "и"), ("то", "есть"), ("а", "именно"), ("такие", "как"), ("такой", "как"),
                  ("включая", ""), ("кроме", "того"), ("за", "исключением"), ("в", "случае"), ("в", "качестве")}
SUBORD_STRICT = SUBORD - {"так", "же", "ли", "либо", "после", "прежде", "тогда", "пусть", "лишь", "едва", "чем", "как"}
SUBORD_CONJ = {"если", "когда", "поскольку", "хотя", "пока", "чтобы", "потому", "ибо", "будто", "словно", "пусть", "едва",
               "лишь", "так", "как", "несмотря", "независимо", "после", "прежде", "причем", "причём"}


def _case(word):
    return pos_of(word)[1].tag.case


def prev_group(pos):
    """Coarse class of the word before a gap, the one used for the realistic weights."""
    return pos if pos in ("NOUN", "ADJ", "VERB") else "CONJ" if pos == "CONJ" else "rest"


def comma_features(text, ms, i, has_comma_before, earlier_commas=()):
    """Features of the gap after word i (a comma there is missing / spurious / present).

    earlier_commas: indices j of the gaps before i that hold a comma in the clean text."""
    n = len(ms)
    low = [m.group(0).lower() for m in ms]
    w = low[i]
    nxt = low[i + 1] if i + 1 < n else ""
    nxt2 = low[i + 2] if i + 2 < n else ""
    first = low[0]
    prev_pos, next_pos = coarse_pos(w), coarse_pos(nxt)
    next2_pos = coarse_pos(nxt2)
    # an opener earlier in the sentence (participle/gerund/subordinate clause started after a comma or at the start)
    opener = None
    for j in range(i, max(-1, i - 14), -1):
        if (j == 0 or (j - 1) in earlier_commas) and (low[j] in SUBORD_STRICT or coarse_pos(low[j]) in ("PRTF", "GRND")
                                                     or j + 1 < n and coarse_pos(low[j]) == "PREP" and low[j + 1] in SUBORD_STRICT):
            opener = j
            break
        if j < i and j in earlier_commas:
            break                        # an intermediate comma: that phrase is another one
    if nxt in SUBORD_STRICT or (coarse_pos(nxt) == "PREP" and nxt2 in SUBORD_STRICT) or nxt == "как" and next2_pos != "NUM":
        ctx = "subord"
    elif nxt in ("а", "но", "однако", "зато"):
        ctx = "advers"
    elif nxt in ("и", "или", "да", "либо"):
        ctx = "and_or"
    elif (nxt, nxt2) in PHRASE_MARKERS or (nxt, "") in PHRASE_MARKERS or nxt in INTRO_PURE and nxt not in ("таким", "кроме"):
        ctx = "phrase_marker"
    elif next_pos in ("PRTF", "GRND") or prev_pos == "NOUN" and next_pos == "ADJ" and next2_pos != "NOUN":
        ctx = "participle_phrase"
    elif w in SUBORD_CONJ or w in INTRO_PURE or (i and (low[i - 1], w) in PHRASE_MARKERS):
        ctx = "after_conj_or_intro"
    elif opener is not None and next_pos in ("VERB", "PRON", "NOUN", "ADVB", "ADJ", "INFN", "NUM") and i - opener >= 2:
        ctx = "closing_phrase"
    elif not has_comma_before and 1 <= i <= 14 and first in LEAD_PHRASE and next_pos in ("VERB", "NOUN", "PRON", "ADJ", "INFN", "ADVB", "NUM"):
        ctx = "closing_lead"
    elif prev_pos == next_pos and prev_pos in ("NOUN", "ADJ", "VERB", "ADVB", "INFN", "NUM", "LATIN") \
            and (prev_pos != "NOUN" or _case(w) == _case(nxt)):
        ctx = "homogeneous"
    elif prev_pos == "NOUN" and next_pos == "VERB":
        ctx = "subject_verb"
    elif prev_pos == "VERB" and next_pos in ("NOUN", "ADJ", "PRON", "PREP"):
        ctx = "verb_object"
    else:
        ctx = "other"
    rel = (i + 1) / n
    return {"ctx": ctx, "prev_pos": prev_pos, "next_pos": next_pos, "len": len_bucket(n),
            "first_comma": "first" if not has_comma_before else "later",
            "where": "start(<=3)" if i <= 3 else ("head(4-7)" if i <= 7 else "tail" if rel > 0.66 else "middle")}


def comma_gaps(text, ms):
    """Every gap between two consecutive words of the clean text: (i, has_comma, features)."""
    out = []
    seen = False
    commas = set()
    for i in range(len(ms) - 1):
        gap = text[ms[i].end():ms[i + 1].start()]
        if gap.strip(" ,") or text[ms[i].end():ms[i].end() + 1] == "," and ms[i + 1].start() == ms[i].end() + 1:
            seen = seen or "," in gap
            if "," in gap:
                commas.add(i)
            continue                                # dash, bracket, quote or decimal comma between the words
        has = "," in gap
        out.append((i, has, comma_features(text, ms, i, seen, commas)))
        seen = seen or has
        if has:
            commas.add(i)
    return out


# ---- word forms ----------------------------------------------------------------------------------------
CASE_BASE = ("case", "number", "gender", "person", "tense")


def form_features(text, ms, i, changed):
    """Features of a word with a wrong form, computed on the clean text. changed: set of grammeme categories."""
    n = len(ms)
    w = ms[i].group(0).lower()
    parse = pos_of(w)[1]
    pos = parse.tag.POS or "OTHER"
    prev = ms[i - 1].group(0).lower() if i else ""
    prev2 = ms[i - 2].group(0).lower() if i > 1 else ""
    ctx = "other"
    dist = 0
    if pos in ("NOUN", "NPRO"):
        j = i - 1
        # walk left over adjectives to the preposition: "в основном документе"
        while j >= 0 and coarse_pos(ms[j].group(0)) in ("ADJ", "PRTF", "NUM") and i - j <= 5:
            j -= 1
        if j >= 0 and ms[j].group(0).lower() in PREPOSITIONS:
            ctx, dist = "after_preposition", i - j
        elif prev and coarse_pos(prev) == "NUM":
            ctx, dist = "after_numeral", 1
        elif prev and coarse_pos(prev) in ("ADJ", "PRTF"):
            ctx, dist = "noun_after_adj", 1
        elif i and coarse_pos(ms[i - 1].group(0)) == "NOUN":
            ctx, dist = "noun_noun_chain", 1
        elif i and coarse_pos(prev) == "VERB" or i > 1 and coarse_pos(prev2) == "VERB":
            ctx, dist = "verb_object", 1 if coarse_pos(prev) == "VERB" else 2
        else:
            ctx = "other"
    elif pos in ("ADJF", "PRTF", "ADJS", "PRTS") and pos in ("ADJF", "PRTF"):
        k = None
        for j in range(i + 1, min(n, i + 7)):
            if coarse_pos(ms[j].group(0)) == "NOUN":
                k = j
                break
            if coarse_pos(ms[j].group(0)) not in ("ADJ", "PRTF", "NUM", "CONJ", "ADVB"):
                break
        if k is not None:
            ctx, dist = "adj_noun_agreement", k - i
        else:
            ctx = "adj_no_head_right"
            for j in range(i - 1, max(-1, i - 8), -1):
                if coarse_pos(ms[j].group(0)) == "NOUN":
                    ctx, dist = "participle_after_noun", i - j
                    break
    elif pos in ("VERB", "PRTS", "ADJS"):
        ctx = "predicate"
        for j in range(i - 1, max(-1, i - 9), -1):
            if coarse_pos(ms[j].group(0)) == "NOUN" or coarse_pos(ms[j].group(0)) == "PRON":
                dist = i - j
                break
    return {"pos": pos if pos in ("NOUN", "ADJF", "PRTF", "VERB", "ADJS", "PRTS", "NPRO", "INFN") else "OTHER",
            "ctx": ctx, "dist": "0" if dist == 0 else "1" if dist == 1 else "2" if dist == 2 else "3-4" if dist <= 4 else "5+",
            "changed": "+".join(c for c in CASE_BASE if c in changed) or "none", "len": len_bucket(n)}
