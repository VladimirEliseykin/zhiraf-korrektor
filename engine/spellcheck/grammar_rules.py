"""Throwaway spike: two conservative grammar rules on top of pymorphy3.

1. Preposition government: the word right after a preposition must be able
   to stand in one of the cases the preposition governs.
2. Adjacent adjective/participle + noun agreement: there must be at least one
   pair of parses agreeing in case and number (and gender in the singular).
A rule fires only when NO combination of parses is grammatical, so homonymy
can only silence it, never trigger it.
"""
import re

from .morph import morph

WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*|\S")

PREP_CASES = {
    "по": {"datv", "accs", "loct"}, "с": {"gent", "ablt", "accs"}, "со": {"gent", "ablt", "accs"},
    "в": {"accs", "loct", "loc2"}, "во": {"accs", "loct", "loc2"}, "на": {"accs", "loct", "loc2"},
    "о": {"loct", "accs"}, "об": {"loct", "accs"}, "обо": {"loct", "accs"}, "к": {"datv"}, "ко": {"datv"},
    "от": {"gent"}, "из": {"gent"}, "до": {"gent"}, "у": {"gent"}, "без": {"gent"}, "для": {"gent"},
    "около": {"gent"}, "после": {"gent"}, "вокруг": {"gent"}, "среди": {"gent"}, "кроме": {"gent"},
    "вместо": {"gent"}, "из-за": {"gent"}, "из-под": {"gent"}, "против": {"gent"}, "ради": {"gent"},
    "согласно": {"datv"}, "благодаря": {"datv"}, "вопреки": {"datv"}, "навстречу": {"datv"},
    "над": {"ablt"}, "перед": {"ablt"}, "между": {"ablt", "gent"}, "за": {"ablt", "accs"},
    "под": {"ablt", "accs"}, "при": {"loct"}, "через": {"accs"}, "про": {"accs"}, "сквозь": {"accs"},
}
DECLINABLE = {"NOUN", "ADJF", "PRTF", "NPRO", "NUMR"}
# adjectives that govern a noun in another case instead of agreeing with it
GOVERNING_ADJ = {"равнозначный", "подведомственный", "подотчётный", "подотчетный", "подконтрольный",
                 "подчинённый", "подчиненный", "подобный", "аналогичный", "равный", "соответствующий",
                 "способный", "достойный", "полный", "свободный", "необходимый", "нужный", "присущий",
                 "свойственный", "правомерный", "благодарный", "верный", "чуждый", "близкий",
                 "адекватный", "созвучный", "желательный", "безразличный", "взаимосвязанный",
                 "взаимодополняющий"}
# second locative/genitive/accusative ("в веку", "чаю") are the same case for agreement purposes
CASE_ALIASES = {"loc2": "loct", "gen2": "gent", "acc2": "accs"}


def case_of(p):
    return CASE_ALIASES.get(p.tag.case, p.tag.case)


def parses(word):
    return [p for p in morph.parse(word.lower()) if p.score > 0.0]


def declinable_only(ps):
    """True when every parse is a declinable form with a known case (no adverbs, verbs...)."""
    return bool(ps) and all(p.tag.POS in DECLINABLE and p.tag.case for p in ps)


def check(text):
    """Return a list of findings: {"start", "end", "rule", "message"} (char offsets)."""
    tokens = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(text)]
    findings = []
    for i in range(len(tokens) - 1):
        w1, s1, _ = tokens[i]
        w2, s2, e2 = tokens[i + 1]
        if not re.fullmatch(r"[А-Яа-яЁё-]+", w2) or w2.isupper() and len(w2) > 1:
            continue  # punctuation, latin, abbreviations
        p2 = parses(w2)
        if not declinable_only(p2) or any("Fixd" in p.tag or "Abbr" in p.tag for p in p2):
            continue
        prep = w1.lower()
        if prep in PREP_CASES:
            cases = {case_of(p) for p in p2}
            if not cases & PREP_CASES[prep]:
                findings.append({"start": s1, "end": e2, "rule": "PREP_CASE",
                                 "message": "После «%s» слово «%s» стоит в неподходящем падеже" % (w1, w2)})
            continue
        p1 = parses(w1)
        # participles govern objects ("осуществляющее обработку"), "который" opens a clause
        if not p1 or not all(p.tag.POS == "ADJF" for p in p1) or any(p.normal_form == "который" for p in p1):
            continue
        nouns = [p for p in p2 if p.tag.POS == "NOUN"]
        if not nouns or len(nouns) != len(p2) or any(p.normal_form == "друг" for p in nouns):
            continue  # also skips the idiom "друг друга"
        if all(case_of(p) == "ablt" for p in p1) and all(case_of(n) in ("nomn", "accs") for n in nouns):
            continue  # predicative: "сделать возможным формирование"
        if any(p.normal_form in GOVERNING_ADJ for p in p1):
            continue  # "равнозначным документу"
        prev = tokens[i - 1][0] if i > 0 else ""
        if any("Anum" in p.tag for p in p1) and prev and any(p.tag.POS == "NOUN" for p in parses(prev)):
            continue  # postpositive ordinal: "абзац восьмой подпункта"
        before = [t[0].lower() for t in tokens[max(0, i - 4):i]]
        after = tokens[i + 2][0].lower() if i + 2 < len(tokens) else ""
        coordinated = any(t in ("и", "или", ",") for t in before)
        nouns_coordinated = after in ("и", "или", ",")

        def agree(a, n):
            if case_of(a) != case_of(n):
                return False
            if a.tag.number == "sing" and n.tag.number == "plur" and coordinated:
                return True  # "на федеральном и региональном уровнях"
            if a.tag.number == "plur" and n.tag.number == "sing" and nouns_coordinated:
                return True  # "такие контроль и надзор"
            if a.tag.number != n.tag.number:
                return False
            # common-gender nouns ("коллега") carry the separate Ms-f grammeme and agree with either gender
            return n.tag.number == "plur" or n.tag.gender is None or "Ms-f" in n.tag or a.tag.gender == n.tag.gender

        if not any(agree(a, n) for a in p1 for n in nouns):
            findings.append({"start": s1, "end": e2, "rule": "ADJ_NOUN",
                             "message": "«%s %s»: слова не согласованы" % (w1, w2)})
    return findings
