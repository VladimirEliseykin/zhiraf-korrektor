"""Check a whole document: SAGE typo/join fixes, comma tagger, word-form tagger, rules.

Models are loaded one at a time and released before the next one (quality first on a 4 GB machine:
two full-precision taggers plus SAGE do not fit side by side, int8 copies lose 8-18% of the finds).
A tagger stage may have several models (folders commas, commas-2, ...): the first one predicts every
sentence and is released, then the next, and the last one combines everything and yields the findings.

Every finding: {"start", "end", "level", "rule", "fix", "message"} in chars of the original sentence.
level "error" — sure, shown as an error with its fix; "check" — the reader should look at the place.
"""
import gc
import os
import time

from . import grammar_rules, rules, sage
from .stages import STAGE_COST, STAGES, model_folders  # noqa: F401  (re-exported)
from .guards import BIBLIOGRAPHY, prepare, protected, quoted_spans
from .tagger import EditTagger
from .text import inflect, words_of

# measured on the 3100-sentence gold of real documents (see train/rules_eval.py, train/coverage.py)
SURE_COMMA, SURE_FORM, SURE_DEL = 0.9, 0.9, 0.9
CHECK_COMMA, CHECK_FORM = 0.3, 0.3
# Several models in one stage (engine/models/commas-2, commas-3): the taggers differ a lot from run to run, an
# edit that independently trained models all predict is far more often right.
# COMBINE: "min" = agreement (every model must be above the threshold), "mean" = average probability.
# Commas: R3 (commas) + R6 (commas-2) + R7 (commas-3), "min", chosen on dev by train/ensemble_eval.py.
# Right / false comma edits at "error" on the real gold (dev | test), clean official false alarms in brackets:
#   R3 alone, ADD 0.9 DEL 0.9:      22 / 3 | 21 / 3  (1)
#   the ensemble, ADD 0.7 DEL 0.8:  27 / 2 | 26 / 4  (1)
# "Check" band, ADD only, right / false (official): R3 alone at 0.3: 29 / 17 | 30 / 23 (8); the ensemble at
# 0.3: 28 / 6 | 28 / 16 (3), at 0.2 (chosen on dev: R3's recall with half the false marks): 30 / 9 | 29 / 24 (3).
# Forms: no ensemble beat R5 alone on dev (best 14 / 1 against 13 / 1 and fewer), so forms stay single-model;
# the *_ENS form thresholds only keep the stage consistent if a second forms model is ever added.
ENSEMBLE_COMBINE = {"commas": "min", "forms": "min"}
SURE_COMMA_ENS, SURE_DEL_ENS, CHECK_COMMA_ENS = 0.7, 0.8, 0.2
SURE_FORM_ENS, CHECK_FORM_ENS = 0.9, 0.3
LEVEL_RANK = {"error": 2, "check": 1}
SOURCE_RANK = {"SAGE": 3, "RULE": 2, "MODEL": 1}


def visible_level(level, strict):
    """'strict' findings (a rule that also hits legitimate capitals) are shown as 'check' only in strict mode."""
    if level == "strict":
        return "check" if strict else None
    return level


def breaks_grammar(text, start, end, new):
    """True when the new word creates a preposition-case or agreement violation that was not there."""
    def touching(t, e):
        return sum(1 for f in grammar_rules.check(t) if f["start"] < e and f["end"] > start)
    return touching(text[:start] + new + text[end:], start + len(new)) > touching(text, end)


def comma_findings(body, preds, sure_add=SURE_COMMA, sure_del=SURE_DEL, check_add=CHECK_COMMA):
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
            if p["comma"]["DEL"] >= sure_del:
                out.append({"start": m.end(), "end": m.end() + 1, "level": "error", "rule": "MODEL_COMMA_DEL",
                            "fix": "", "message": "Лишняя запятая", "p": round(p["comma"]["DEL"], 3)})
            continue
        if i == len(ms) - 1 or body[m.end():m.end() + 1] != " ":
            continue  # the last word, or another sign is already there
        prob = p["comma"]["ADD"]
        level = "error" if prob >= sure_add else "check" if prob >= check_add else None
        if level:
            out.append({"start": m.end(), "end": m.end(), "level": level, "rule": "MODEL_COMMA", "fix": ",",
                        "message": "Здесь нужна запятая" if level == "error" else "Возможно, здесь нужна запятая",
                        "p": round(prob, 3)})
    return out


def form_findings(body, preds, sure=SURE_FORM, check=CHECK_FORM):
    if BIBLIOGRAPHY.search(body):
        return []
    quotes = quoted_spans(body)
    out = []
    for i, (m, p) in enumerate(zip(words_of(body), preds)):
        word = m.group(0)
        if p["form"] == "KEEP" or p["form_p"] < check or protected(word):
            continue
        if any(a < m.start() < b for a, b in quotes) or (i > 0 and word[:1].isupper()):
            continue  # titles in quotes; a capital inside a sentence is a name or a title
        new = inflect(word, p["form"])
        if not new or new == word or breaks_grammar(body, m.start(), m.end(), new):
            continue
        level = "error" if p["form_p"] >= sure else "check"
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


def combine_predictions(parts, how):
    """One prediction list from the lists of several models (a word past a model's token limit is dropped).

    Comma probabilities are combined per label; a word form counts only when every model chose the same
    label, its probability is then the combined form_p (otherwise the word is KEEP).
    """
    pick = min if how == "min" else (lambda xs: sum(xs) / len(xs))
    out = []
    for words in zip(*parts):
        comma = {k: pick([w["comma"][k] for w in words]) for k in words[0]["comma"]}
        same = all(w["form"] == words[0]["form"] for w in words)
        out.append({"comma": comma, "form": words[0]["form"] if same else "KEEP",
                    "form_p": pick([w["form_p"] for w in words]) if same else 0.0,
                    "form_keep_p": pick([w["form_keep_p"] for w in words])})
    return out


class Checker:
    def __init__(self, models_dir, threads=2, process=None, factories=None, strict=False):
        self.models_dir = models_dir
        self.threads = threads
        self.strict = strict
        self.lexicon = rules.Lexicon(None, os.path.join(models_dir, "vocab.tsv"))
        self.process = process  # psutil.Process for memory statistics, optional
        self.stats = {}
        self.stopped = False
        # a stage maps to one factory or a list of them (several models, the first is the main one)
        self.factories = factories or {
            "sage": lambda: sage.Sage(os.path.join(models_dir, "sage"), threads),
            "commas": [self._tagger_factory(f) for f in model_folders(models_dir, "commas")],
            "forms": [self._tagger_factory(f) for f in model_folders(models_dir, "forms")],
        }

    def _tagger_factory(self, folder):
        return lambda: EditTagger(folder, self.threads)

    def passes(self, stage):
        """How many model passes a stage makes over the sentences (1 for rules, SAGE and single-model stages)."""
        made = self.factories.get(stage, ())
        return len(made) if isinstance(made, (list, tuple)) and made else 1

    def _stage(self, name, started):
        rss = self.process.memory_info().rss // 2 ** 20 if self.process else None
        self.stats[name] = {"seconds": round(time.perf_counter() - started, 1), "rss_mb": rss}

    def _earlier_passes(self, stage, makers, prepared, first, should_stop, on_step):
        """Predictions of every model but the last, for sentences first..end: [None] * first + per-sentence lists
        per model. Each model is released before the next is loaded. None when should_stop ended the pass."""
        parts = []
        for make in makers[:-1]:
            model = make()
            found = [None] * first
            for i in range(first, len(prepared)):
                if should_stop is not None and should_stop():
                    return None
                found.append(model.predict(prepared[i][1]))
                if on_step is not None:
                    on_step(stage)
            parts.append(found)
            model = None  # release this model before the next one is loaded
            gc.collect()
        return parts

    def _stage_function(self, stage, sentences, context, prepared=None, first=0, should_stop=None, on_step=None):
        """check(index, body) -> findings; loads the stage model(s). None when should_stop ended an earlier pass."""
        if stage == "rules":
            ctx = rules.DocContext(context if context is not None else sentences, self.lexicon)
            return lambda i, body: [dict(f, rule="RULE_" + f["rule"]) for f in rules.check(body, self.lexicon, ctx)]
        made = self.factories[stage]
        makers = list(made) if isinstance(made, (list, tuple)) else [made]
        parts = self._earlier_passes(stage, makers, prepared, first, should_stop, on_step) if len(makers) > 1 else []
        if parts is None:
            return None
        model = makers[-1]()
        if stage == "sage":
            return lambda i, body: sage.findings(body, model.correct(body), self.lexicon)
        how = ENSEMBLE_COMBINE[stage]
        if stage == "commas":
            ens = dict(sure_add=SURE_COMMA_ENS, sure_del=SURE_DEL_ENS, check_add=CHECK_COMMA_ENS) if parts else {}
            to_findings = lambda body, p: comma_findings(body, p, **ens)  # noqa: E731
        else:
            ens = dict(sure=SURE_FORM_ENS, check=CHECK_FORM_ENS) if parts else {}
            to_findings = lambda body, p: form_findings(body, p, **ens)  # noqa: E731

        def check(i, body):
            preds = model.predict(body)
            if parts:
                preds = combine_predictions([part[i] for part in parts] + [preds], how)
                for part in parts:
                    part[i] = None  # a sentence is combined once: free its earlier predictions
            return to_findings(body, preds)
        return check

    def stream(self, sentences, context=None, stages=STAGES, should_stop=None, start=None, on_step=None):
        """Yield (stage, sentence index, findings) for every sentence and stage as soon as it is checked.

        Stages run one after another and load their model only for their own pass, so at most one
        model is in memory. Positions are chars of the original sentence (list marker included).
        start=(stage, index) resumes: earlier stages are skipped entirely (no model is loaded for them)
        and, in that stage, the sentences before index. self.stopped tells whether should_stop ended it.
        A stage with several models first makes silent passes with all but the last model; on_step(stage)
        is called after each sentence of such a pass (progress), the findings come in the last pass.
        """
        self.stopped = False
        prepared = [prepare(s) for s in sentences]
        skipping = start is not None
        for stage in stages:
            first = 0
            if skipping:
                if start is not None and stage != start[0]:
                    continue
                skipping, first = False, max(0, start[1])
            if first >= len(prepared):
                continue  # nothing to check here: do not load a model for it
            started = time.perf_counter()
            check = self._stage_function(stage, sentences, context, prepared, first, should_stop, on_step)
            if check is None:
                self.stopped = True
                return
            for i in range(first, len(prepared)):
                if should_stop is not None and should_stop():
                    self.stopped = True
                    return
                marker, body = prepared[i]
                found = []
                for f in check(i, body):
                    level = visible_level(f["level"], self.strict)
                    if level is not None:
                        found.append(dict(f, level=level, start=f["start"] + len(marker), end=f["end"] + len(marker)))
                yield stage, i, found
            check = None  # release the model before the next one is loaded
            gc.collect()
            self._stage(stage, started)

    def check_document(self, sentences, context=None, stages=STAGES):
        """Merged findings for each sentence (evaluation, batch runs)."""
        found = [[] for _ in sentences]
        for _, i, items in self.stream(sentences, context, stages):
            found[i].extend(items)
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
