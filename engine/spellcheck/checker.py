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
from array import array
import time

from . import grammar_rules, rules, sage
from .stages import STAGE_COST, STAGES, model_folders  # noqa: F401  (re-exported)
from .guards import BIBLIOGRAPHY, prepare, protected, quoted_spans
from .morph import morph
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
# Hybrid: "error" from the agreement (min), "check" from a softer score of the same models, so that places the
# models only half agree on are still highlighted: CHECK_COMBINE "min" | "mean" | "max" | "first" (the main model).
# Check-only places (ADD, not an error), right / false on dev: first >= 0.3 9 / 15, mean >= 0.3 10 / 13 (best on dev
# within the false budget, but over budget end to end), max >= 0.3 11 / 40, min >= 0.2 10 / 7 (the pure agreement band).
# Measured end to end, "mean" >= 0.3 gave highlighted 18% / false check 2.6 per 100 (budget 2.2): not worth it, so
# the shipped setting is the pure agreement band (min >= 0.2: 17% / 2.1); the hybrid stays available for retuning.
CHECK_COMBINE = {}
# Forms: no ensemble beat R5 alone on dev (best 14 / 1 against 13 / 1 and fewer), so forms stay single-model;
# the *_ENS form thresholds only keep the stage consistent if a second forms model is ever added.
# The ensemble thresholds below were measured for exactly ENSEMBLE_SIZE models in the stage. With fewer (a
# missing or half-copied commas-3) the stage uses the single-model thresholds above: the min of two models at
# those is at least as precise as one model alone, and nothing about two models was measured.
# Forms have no measured ensemble (a stage with several form models uses the single-model thresholds).
ENSEMBLE_COMBINE = {"commas": "min", "forms": "min"}
ENSEMBLE_SIZE = {"commas": 3}
SURE_COMMA_ENS, SURE_DEL_ENS, CHECK_COMMA_ENS = 0.7, 0.8, 0.2
SURE_SPELL, CHECK_SPELL = 0.9, 0.3  # spelling head (joined/split words, hyphens, capitals); not yet measured on gold
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
        soft = p["comma"].get("CHECK", prob)  # an ensemble has its own score for the "check" level
        level = "error" if prob >= sure_add else "check" if soft >= check_add else None
        if level:
            out.append({"start": m.end(), "end": m.end(), "level": level, "rule": "MODEL_COMMA", "fix": ",",
                        "message": "Здесь нужна запятая" if level == "error" else "Возможно, здесь нужна запятая",
                        "p": round(prob if level == "error" else soft, 3)})
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


SPELL_MESSAGES = {
    "JOIN": ("Слово пишется слитно", "Возможно, слово пишется слитно"),
    "HYPHEN": ("Нужен дефис", "Возможно, здесь нужен дефис"),
    "SPLIT": ("Частица «не» пишется раздельно", "Возможно, «не» пишется раздельно"),
    "LOWER": ("Слово пишется с маленькой буквы", "Возможно, слово пишется с маленькой буквы"),
    "UPPER": ("Слово пишется с большой буквы", "Возможно, слово пишется с большой буквы"),
}
NOT_COMMON_NOUN = ("Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad")
NAME_LIKE = ("Name", "Surn", "Patr", "Geox")
# common nouns that official language writes with a capital as part of a title ("Российская Федерация"):
# the model must not lower them even when it is unsure about the context
CAPITAL_LEMMAS = {"федерация", "республика", "конституция", "правительство", "президент", "дума", "собрание",
                  "совет", "союз", "государство", "федерация", "кодекс", "палата", "суд"}


def spell_fix(body, ms, i, label, quotes):
    """(start, end, fix) for a spelling label of word i, or None when the label cannot be applied safely."""
    m = ms[i]
    word = m.group(0)
    if label in ("JOIN", "HYPHEN"):
        if i + 1 >= len(ms) or body[m.end():ms[i + 1].start()] != " ":
            return None
        nxt = ms[i + 1]
        second = nxt.group(0)
        if protected(second) or not second.isalpha() or not second[:1].islower() or any(a < nxt.start() < b for a, b in quotes):
            return None
        return m.start(), nxt.end(), word + ("" if label == "JOIN" else "-") + second
    if label == "SPLIT":
        rest = word[2:]
        if word[:2].lower() != "не" or len(rest) < 3 or not rest.isalpha() or morph.word_is_known(word.lower()):
            return None
        parse = morph.parse(rest.lower())[0]
        if parse.score < 0.5 or parse.tag.POS not in ("VERB", "INFN", "GRND"):
            return None
        return m.start(), m.end(), word[:2] + " " + rest
    if label == "LOWER":
        # only in the middle of a sentence ("... , Служба"), and never for names the dictionary knows
        before = body[max(0, m.start() - 2):m.start()]
        if i == 0 or len(before) < 2 or before[1] != " " or not (before[0].isalpha() or before[0] == ","):
            return None
        if not word[:1].isupper() or not word[1:].islower() or len(word) < 4:
            return None
        parse = morph.parse(word.lower())[0]
        if parse.tag.POS != "NOUN" or any(g in parse.tag for g in NOT_COMMON_NOUN) or parse.normal_form in CAPITAL_LEMMAS:
            return None
        return m.start(), m.end(), word[:1].lower() + word[1:]
    if label == "UPPER":
        if not word[:1].islower() or not word.isalpha() or len(word) < 3:
            return None
        if i > 0 and not any(g in morph.parse(word)[0].tag for g in NAME_LIKE):
            return None  # inside a sentence only names are capitalised on the model's say-so
        return m.start(), m.end(), word[:1].upper() + word[1:]
    return None


def spell_findings(body, preds):
    """Joined/split/hyphenated words and wrong capitals from the spelling head; nothing without the head.

    The fix is built from the label: JOIN/HYPHEN replace the two words by their joined or hyphenated
    form, SPLIT puts a space after "не", LOWER/UPPER change the first letter."""
    if not preds or "spell" not in preds[0] or BIBLIOGRAPHY.search(body):
        return []
    quotes = quoted_spans(body)
    ms = words_of(body)
    out = []
    for i, (m, p) in enumerate(zip(ms, preds)):
        word = m.group(0)
        if any(a < m.start() < b for a, b in quotes) or protected(word):
            continue
        label, prob = max(((k, v) for k, v in p["spell"].items() if k != "KEEP"), key=lambda kv: kv[1])
        if prob < CHECK_SPELL:
            continue
        fix = spell_fix(body, ms, i, label, quotes)
        if fix is None:
            continue
        level = "error" if prob >= SURE_SPELL else "check"
        if label == "UPPER" and i == 0:
            # a list item continues the sentence in lowercase on purpose: only a whole sentence is sure
            if not body.rstrip().endswith((".", "!", "?")):
                continue
            level = "check"
        out.append({"start": fix[0], "end": fix[1], "level": level, "rule": "MODEL_SPELL", "fix": fix[2],
                    "message": SPELL_MESSAGES[label][level != "error"], "p": round(prob, 3)})
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


COMBINERS = {"min": min, "mean": lambda xs: sum(xs) / len(xs)}
CHECK_COMBINERS = {"min": min, "max": max, "first": lambda a: a[0], "mean": COMBINERS["mean"]}
STORED = 5  # numbers kept per word: KEEP, ADD, DEL, form_p, form_keep_p (plus the form label)


def validate_combiners():
    for stage, how in ENSEMBLE_COMBINE.items():
        if how not in COMBINERS:
            raise ValueError("unknown ENSEMBLE_COMBINE[%r] = %r (use min or mean)" % (stage, how))
    for stage, how in CHECK_COMBINE.items():
        if how not in CHECK_COMBINERS:
            raise ValueError("unknown CHECK_COMBINE[%r] = %r (use min, mean, max or first)" % (stage, how))


validate_combiners()


def compact(preds):
    """The predictions of one sentence as (array of STORED doubles per word, form labels): a few dozen bytes a word
    instead of a dict of dicts (an earlier model's predictions for a whole document wait in memory)."""
    numbers = array("d")
    for p in preds:
        c = p["comma"]
        numbers.extend((c["KEEP"], c["ADD"], c["DEL"], p["form_p"], p["form_keep_p"]))
    return numbers, [p["form"] for p in preds]


def combine_predictions(parts, how, check_how=None):
    """One prediction list from the compact lists of several models (see compact(); a word past a model's token
    limit is dropped).

    Comma probabilities are combined per label; a word form counts only when every model chose the same
    label, its probability is then the combined form_p (otherwise the word is KEEP).
    check_how: the comma "CHECK" score for the "check" level, combined differently from the sure one.
    """
    pick = COMBINERS[how]
    out = []
    for i in range(min(len(forms) for _, forms in parts)):
        rows = [numbers[i * STORED:(i + 1) * STORED] for numbers, _ in parts]
        labels = [forms[i] for _, forms in parts]
        comma = {"KEEP": pick([r[0] for r in rows]), "ADD": pick([r[1] for r in rows]), "DEL": pick([r[2] for r in rows])}
        if check_how is not None:
            comma["CHECK"] = CHECK_COMBINERS[check_how]([r[1] for r in rows])
        same = all(label == labels[0] for label in labels)
        out.append({"comma": comma, "form": labels[0] if same else "KEEP",
                    "form_p": pick([r[3] for r in rows]) if same else 0.0,
                    "form_keep_p": pick([r[4] for r in rows])})
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
        """Compact predictions (see compact()) of every model but the last: one list per model, [None] * first +
        one entry per sentence from first on. Each model is released before the next is loaded, also when a
        prediction fails or should_stop ends the pass (then None)."""
        parts = []
        for make in makers[:-1]:
            model = make()
            try:
                found = [None] * first
                for i in range(first, len(prepared)):
                    if should_stop is not None and should_stop():
                        return None
                    found.append(compact(model.predict(prepared[i][1])))
                    if on_step is not None:
                        on_step(stage)
            finally:
                model = None  # release this model before the next one is loaded (or before leaving)
                gc.collect()
            parts.append(found)
        return parts

    def _stage_function(self, stage, sentences, context, prepared=None, first=0, should_stop=None, on_step=None):
        """check(index, body) -> findings; loads the stage model(s). None when should_stop ended an earlier pass."""
        if stage == "rules":
            ctx = rules.DocContext(context if context is not None else sentences, self.lexicon)
            return lambda i, body: [dict(f, rule="RULE_" + f["rule"]) for f in rules.check(body, self.lexicon, ctx)]
        made = self.factories[stage]
        makers = list(made) if isinstance(made, (list, tuple)) else [made]
        if len(makers) > 1:
            validate_combiners()
        parts = self._earlier_passes(stage, makers, prepared, first, should_stop, on_step) if len(makers) > 1 else []
        if parts is None:
            return None
        if len(makers) > 1 and should_stop is not None and should_stop():
            return None  # stopped right after the last silent step: do not load the last model for nothing
        model = makers[-1]()
        if stage == "sage":
            return lambda i, body: sage.findings(body, model.correct(body), self.lexicon)
        how = ENSEMBLE_COMBINE.get(stage, "min")
        measured = len(makers) == ENSEMBLE_SIZE.get(stage)  # thresholds exist only for the measured model count
        check_how = CHECK_COMBINE.get(stage) if measured else None
        if stage == "commas":
            ens = dict(sure_add=SURE_COMMA_ENS, sure_del=SURE_DEL_ENS, check_add=CHECK_COMMA_ENS) if measured else {}
            to_findings = lambda body, p: comma_findings(body, p, **ens)  # noqa: E731
        else:
            to_findings = form_findings

        def check(i, body):
            preds = model.predict(body)
            # the spelling head rides on whichever model has it (the last one of the stage); for the others this
            # adds nothing, and the ensemble combination below keeps comma/form probabilities only
            spelled = spell_findings(body, preds)
            if parts:
                preds = combine_predictions([part[i] for part in parts] + [compact(preds)], how, check_how)
                for part in parts:
                    part[i] = None  # a sentence is combined once: free its earlier predictions
            return to_findings(body, preds) + spelled
        return check

    def stream(self, sentences, context=None, stages=STAGES, should_stop=None, start=None, on_step=None):
        """Yield (stage, sentence index, findings) for every sentence and stage as soon as it is checked.

        Stages run one after another and load their model only for their own pass, so at most one
        model is in memory. Positions are chars of the original sentence (list marker included).
        start=(stage, index) resumes: earlier stages are skipped entirely (no model is loaded for them)
        and, in that stage, the sentences before index. self.stopped tells whether should_stop ended it.
        A stage with several models first makes silent passes with all but the last model; on_step(stage)
        is called after each sentence of such a pass (progress), the findings come in the last pass only.
        To resume such a stage use the index after the last YIELDED findings, never the progress step count
        (which also counts the silent passes).
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
