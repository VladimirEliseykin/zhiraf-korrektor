"""Throwaway spike: subject-verb agreement using Slovnet syntax + pymorphy3 forms.

Slovnet gives the structure (which noun is the subject of which verb); the
agreement itself is checked on pymorphy parses of the actual words, so a
mis-tagged erroneous form cannot hide the error. Fires only when no pair of
parses agrees.
"""
import pymorphy3
from natasha import Doc, NewsEmbedding, NewsMorphTagger, NewsSyntaxParser, Segmenter

morph = pymorphy3.MorphAnalyzer()
segmenter = Segmenter()
emb = NewsEmbedding()
tagger = NewsMorphTagger(emb)
parser = NewsSyntaxParser(emb)
SKIP_SUBJECTS = {"кто", "что", "который", "это", "все", "всё", "каждый", "один", "ряд", "большинство", "часть", "число"}


def analyse(text):
    doc = Doc(text)
    doc.segment(segmenter)
    doc.tag_morph(tagger)
    doc.parse_syntax(parser)
    return doc


def verb_parses(word):
    return [p for p in morph.parse(word.lower()) if p.tag.POS == "VERB" and p.tag.number]


def subject_parses(word):
    """A subject is always nominative; other readings of the same string must not mask an error."""
    return [p for p in morph.parse(word.lower())
            if p.tag.POS in ("NOUN", "NPRO") and p.tag.number and p.tag.case == "nomn"]


def agree(s, v):
    if s.tag.number != v.tag.number:
        return False
    if v.tag.number == "sing" and v.tag.gender and s.tag.gender and "Ms-f" not in s.tag:
        return s.tag.gender == v.tag.gender
    if v.tag.person and s.tag.POS == "NPRO" and s.tag.person:
        return v.tag.person == s.tag.person
    return True


def check(text):
    findings = []
    doc = analyse(text)
    for sent in doc.sents:
        by_id = {t.id: t for t in sent.tokens}
        children = {}
        for t in sent.tokens:
            children.setdefault(t.head_id, []).append(t)
        for t in sent.tokens:
            if t.rel not in ("nsubj", "nsubj:pass") or t.head_id not in by_id:
                continue
            verb = by_id[t.head_id]
            if t.text.lower() in SKIP_SUBJECTS or not t.text[0].isalpha():
                continue
            # coordinated subjects ("цели и задачи") or numerals make plural agreement legitimate
            if any(c.rel in ("conj", "nummod", "nummod:gov") for c in children.get(t.id, [])):
                continue
            vp, sp = verb_parses(verb.text), subject_parses(t.text)
            if not vp or not sp or any("Fixd" in p.tag or "Abbr" in p.tag for p in sp):
                continue
            if not any(agree(s, v) for s in sp for v in vp):
                findings.append({"start": verb.start, "end": verb.stop, "rule": "SUBJ_VERB",
                                 "message": "«%s … %s»: сказуемое не согласовано с подлежащим" % (t.text, verb.text)})
    return findings
