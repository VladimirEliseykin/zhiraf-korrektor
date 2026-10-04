"""Check a whole document: SAGE typo/join fixes, comma tagger, word-form tagger, rules.

Models are loaded one at a time and released before the next one (quality first on a 4 GB machine:
two full-precision taggers plus SAGE do not fit side by side, int8 copies lose 8-18% of the finds).

Every finding: {"start", "end", "level", "rule", "fix", "message"} in chars of the original sentence.
level "error" — sure, shown as an error with its fix; "check" — the reader should look at the place.
"""
import gc
import os
import time

from . import grammar_rules, rules, sage
from .guards import BIBLIOGRAPHY, prepare, protected, quoted_spans
from .tagger import EditTagger
from .text import inflect, words_of

# measured on the 3100-sentence gold of real documents (see train/rules_eval.py, train/coverage.py)
SURE_COMMA, SURE_FORM, SURE_DEL = 0.9, 0.9, 0.9
CHECK_COMMA, CHECK_FORM = 0.3, 0.3
LEVEL_RANK = {"error": 2, "check": 1}
SOURCE_RANK = {"SAGE": 3, "RULE": 2, "MODEL": 1}


def breaks_grammar(text, start, end, new):
    """True when the new word creates a preposition-case or agreement violation that was not there."""
    def touching(t, e):
        return sum(1 for f in grammar_rules.check(t) if f["start"] < e and f["end"] > start)
    return touching(text[:start] + new + text[end:], start + len(new)) > touching(text, end)


def comma_findings(body, preds):
    if BIBLIOGRAPHY.search(body):
        return []
    quotes = quoted_spans(body)
    ms = words_of(body)
    out = []
    for i, (m, p) in enumerate(zip(ms, preds)):
        word = m.group(0)
        if any(a < m.start() < b for a, b in quotes) or protected(word) and not word.isalpha():
            continue
        if body[m.end():m.end() + 1] == ",":
            # removing a comma only when the tagger is sure: unsure removals strip the closing commas
            # of long participial phrases (measured on clean official text)
            if p["comma"]["DEL"] >= SURE_DEL:
                out.append({"start": m.end(), "end": m.end() + 1, "level": "error", "rule": "MODEL_COMMA_DEL",
                            "fix": "", "message": "Лишняя запятая", "p": round(p["comma"]["DEL"], 3)})
            continue
        if i == len(ms) - 1 or body[m.end():m.end() + 1] != " ":
            continue  # the last word, or another sign is already there
        prob = p["comma"]["ADD"]
        level = "error" if prob >= SURE_COMMA else "check" if prob >= CHECK_COMMA else None
        if level:
            out.append({"start": m.end(), "end": m.end(), "level": level, "rule": "MODEL_COMMA", "fix": ",",
                        "message": "Здесь нужна запятая" if level == "error" else "Возможно, здесь нужна запятая",
                        "p": round(prob, 3)})
    return out


def form_findings(body, preds):
    if BIBLIOGRAPHY.search(body):
        return []
    quotes = quoted_spans(body)
    out = []
    for i, (m, p) in enumerate(zip(words_of(body), preds)):
        word = m.group(0)
        if p["form"] == "KEEP" or p["form_p"] < CHECK_FORM or protected(word):
            continue
        if any(a < m.start() < b for a, b in quotes) or (i > 0 and word[:1].isupper()):
            continue  # titles in quotes; a capital inside a sentence is a name or a title
        new = inflect(word, p["form"])
        if not new or new == word or breaks_grammar(body, m.start(), m.end(), new):
            continue
        level = "error" if p["form_p"] >= SURE_FORM else "check"
        out.append({"start": m.start(), "end": m.end(), "level": level, "rule": "MODEL_FORM", "fix": new,
                    "message": "Неверное окончание" if level == "error" else "Проверьте окончание",
                    "p": round(p["form_p"], 3)})
    return out


def overlaps(a, b):
    if a["start"] == a["end"] or b["start"] == b["end"]:  # insertions
        p, other = (a, b) if a["start"] == a["end"] else (b, a)
        if other["start"] == other["end"]:
            return p["start"] == other["start"]
        return other["start"] < p["start"] < other["end"]
    return a["start"] < b["end"] and b["start"] < a["end"]


def merge(found):
    """Keep one finding per place: the surer level wins, then SAGE > rules > models."""
    def rank(f):
        return LEVEL_RANK.get(f["level"], 0), SOURCE_RANK.get(f["rule"].split("_")[0], SOURCE_RANK["RULE"])
    kept = []
    for f in sorted(found, key=rank, reverse=True):
        if f["level"] in LEVEL_RANK and not any(overlaps(f, k) for k in kept):
            kept.append(f)
    return sorted(kept, key=lambda f: (f["start"], f["end"]))


class Checker:
    def __init__(self, models_dir, threads=2, process=None):
        self.models_dir = models_dir
        self.threads = threads
        self.lexicon = rules.Lexicon(None, os.path.join(models_dir, "vocab.tsv"))
        self.process = process  # psutil.Process for memory statistics, optional
        self.stats = {}

    def _stage(self, name, started):
        rss = self.process.memory_info().rss // 2 ** 20 if self.process else None
        self.stats[name] = {"seconds": round(time.perf_counter() - started, 1), "rss_mb": rss}

    def check_document(self, sentences, context=None, stages=("sage", "commas", "forms", "rules")):
        """Findings for each sentence. context: all sentences of the document (defaults to sentences)."""
        prepared = [prepare(s) for s in sentences]
        found = [[] for _ in sentences]

        def add(i, items):
            shift = len(prepared[i][0])
            for f in items:
                f = dict(f)
                f["start"] += shift
                f["end"] += shift
                found[i].append(f)

        if "sage" in stages:
            t = time.perf_counter()
            model = sage.Sage(os.path.join(self.models_dir, "sage"), self.threads)
            for i, (_, body) in enumerate(prepared):
                add(i, sage.findings(body, model.correct(body), self.lexicon))
            del model
            gc.collect()
            self._stage("sage", t)
        for stage, folder, to_findings in (("commas", "commas", comma_findings), ("forms", "forms", form_findings)):
            if stage not in stages:
                continue
            t = time.perf_counter()
            model = EditTagger(os.path.join(self.models_dir, folder), self.threads)
            for i, (_, body) in enumerate(prepared):
                add(i, to_findings(body, model.predict(body)))
            del model
            gc.collect()
            self._stage(stage, t)
        if "rules" in stages:
            t = time.perf_counter()
            ctx = rules.DocContext(context if context is not None else sentences, self.lexicon)
            for i, (_, body) in enumerate(prepared):
                add(i, [dict(f, rule="RULE_" + f["rule"]) for f in rules.check(body, self.lexicon, ctx)])
            self._stage("rules", t)
        return [merge(f) for f in found]


def apply(text, findings, levels=("error",)):
    """Text with the fixes of the given levels applied."""
    out, last = [], 0
    for f in sorted(findings, key=lambda f: (f["start"], f["end"])):
        if f["level"] not in levels or f.get("fix") is None or f["start"] < last:  # "" = delete
            continue
        out.append(text[last:f["start"]])
        out.append(f["fix"])
        last = f["end"]
    out.append(text[last:])
    return "".join(out)
