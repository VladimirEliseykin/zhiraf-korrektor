"""Throwaway spike: syntax-based comma rules (Slovnet structure + pymorphy forms).

Each rule returns edits {"op": "add"|"remove", "pos": char offset, "rule", "message"}:
"add" inserts a comma at pos, "remove" deletes the comma at pos.
"""
import pymorphy3

from syntax_rules import analyse

morph = pymorphy3.MorphAnalyzer()

SUBORDINATORS = {"если", "когда", "чтобы", "хотя", "поскольку", "пока", "будто", "словно", "ибо", "дабы", "несмотря"}
RELATIVE = {"который", "которая", "которое", "которые", "которого", "которой", "которому", "которым",
            "котором", "которую", "которых", "которыми", "чей", "чья", "чьё", "чьи"}
PREPOSITIONS = {"в", "во", "на", "о", "об", "с", "со", "к", "ко", "по", "из", "от", "до", "для", "при", "за",
                "под", "над", "без", "через", "у", "про", "между", "перед", "согласно", "благодаря"}
NO_COMMA_BEFORE = {",", "(", "—", "–", "-", ":", ";", "«", "\"", "и", "а", "но", "или", "либо", "да"}


def tokens_of(doc):
    toks = []
    for sent in doc.sents:
        toks.extend(sent.tokens)
    return toks


def has_comma_between(text, a, b):
    return "," in text[a:b]


def check(text):
    doc = analyse(text)
    toks = tokens_of(doc)
    edits = []
    by_id = {t.id: t for t in toks}
    children = {}
    for t in toks:
        children.setdefault(t.head_id, []).append(t)

    for i, t in enumerate(toks):
        low = t.text.lower()
        prev = toks[i - 1] if i > 0 else None
        prev2 = toks[i - 2] if i > 1 else None

        # R1: comma before subordinating conjunctions and relative pronouns
        if prev is not None and (low in SUBORDINATORS or low in RELATIVE):
            # the clause starts at the conjunction, or at the preposition in "в котором"
            k = i - 1 if (low in RELATIVE and prev.text.lower() in PREPOSITIONS) else i
            before = toks[k - 1] if k > 0 else None
            if before is not None and before.text.lower() not in NO_COMMA_BEFORE \
                    and not has_comma_between(text, before.stop, toks[k].start):
                edits.append({"op": "add", "pos": before.stop, "rule": "COMMA_BEFORE_SUBORD",
                              "message": "Перед «%s» нужна запятая" % toks[k].text})

        # R2: "такие как" introducing examples after a noun needs a comma before "такие"
        if low == "такие" and i + 1 < len(toks) and toks[i + 1].text.lower() == "как" and prev is not None \
                and prev.text not in NO_COMMA_BEFORE and prev.pos in ("NOUN", "PROPN", "ADJ"):
            if not has_comma_between(text, prev.stop, t.start):
                edits.append({"op": "add", "pos": prev.stop, "rule": "COMMA_TAKIE_KAK",
                              "message": "Перед «такие как» нужна запятая"})
        # R2b: no colon right after "такие как"
        if low == "как" and prev is not None and prev.text.lower() == "такие" and i + 1 < len(toks) and toks[i + 1].text == ":":
            edits.append({"op": "remove", "pos": toks[i + 1].start, "rule": "NO_COLON_TAKIE_KAK",
                          "message": "После «такие как» двоеточие не ставится"})

        # R3: participial / adjectival phrase AFTER its noun opens with a comma
        if t.rel in ("acl", "amod") and t.head_id in by_id:
            head = by_id[t.head_id]
            is_part = any(p.tag.POS in ("PRTF",) for p in morph.parse(low))
            if is_part and t.start > head.stop and children.get(t.id) and prev is not None \
                    and prev.pos in ("NOUN", "PROPN") and all(c.start > t.start for c in children[t.id]):
                if not has_comma_between(text, head.stop, t.start):
                    edits.append({"op": "add", "pos": head.stop, "rule": "COMMA_PARTICIPLE",
                                  "message": "Причастный оборот после определяемого слова выделяется запятой"})

        # R4: single comma between the subject group and its predicate
        if t.text == "," and prev is not None and i + 1 < len(toks):
            nxt = toks[i + 1]
            subj = [c for c in children.get(nxt.id, []) if c.rel in ("nsubj", "nsubj:pass")]
            if subj and nxt.pos == "VERB" and nxt.start > t.start:
                s = subj[0]
                span_ids = _subtree(s, children)
                span = [by_id[x] for x in span_ids if x in by_id and by_id[x].pos != "PUNCT"]
                end = max(x.stop for x in span)
                start = min(x.start for x in span)
                if end <= t.start and "," not in text[start:t.start] and abs(t.start - end) <= 1:
                    edits.append({"op": "remove", "pos": t.start, "rule": "NO_COMMA_SUBJ_PRED",
                                  "message": "Запятая между подлежащим и сказуемым не ставится"})
    return edits


def _subtree(token, children):
    ids, stack = [], [token]
    while stack:
        x = stack.pop()
        ids.append(x.id)
        stack.extend(children.get(x.id, []))
    return ids


def apply(text, edits):
    out = text
    for e in sorted(edits, key=lambda e: -e["pos"]):
        if e["op"] == "add":
            out = out[:e["pos"]] + "," + out[e["pos"]:]
        elif out[e["pos"]:e["pos"] + 1] in (",", ":"):
            out = out[:e["pos"]] + out[e["pos"] + 1:]
    return out
