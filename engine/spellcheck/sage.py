"""SAGE (ai-forever sage-fredt5-distilled-95m, MIT) through onnxruntime, and the policy that keeps
only its trustworthy edits.

SAGE rewrites the whole sentence; on real documents most of its rewrites are harmful. Only two
kinds survive (measured): a word missing from the dictionary replaced by a known one ("typo"),
and joined/hyphenated spelling of the same letters ("join").
"""
import difflib
import os
import re

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .guards import TOKEN, allowed, quoted_spans
from .morph import morph
from .ortutil import session_options

DECODER_START_ID = 0
EOS_ID = 2
WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")


def postprocess(src, out):
    out = out.strip()
    if src and src[-1] in ".:;!?" and (not out or out[-1] not in ".:;!?"):
        out += src[-1]
    if "№" in src:
        out = re.sub(r"\bN(?=\s?\d)", "№", out)
    return out


class Sage:
    def __init__(self, model_dir, threads=2):
        options = session_options(ort, threads)
        providers = ["CPUExecutionProvider"]
        self.encoder = ort.InferenceSession(os.path.join(model_dir, "encoder_model.onnx"), options, providers=providers)
        self.decoder = ort.InferenceSession(os.path.join(model_dir, "decoder_model_merged.onnx"), options,
                                            providers=providers)
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.past_names = [i.name for i in self.decoder.get_inputs() if i.name.startswith("past_key_values.")]
        self.output_names = [o.name for o in self.decoder.get_outputs()]
        self.num_heads = 6
        self.head_dim = 64

    def correct(self, text):
        # the model was trained with the <LM> prefix the tokenizer adds; without it output degenerates
        ids = self.tokenizer.encode(text).ids
        input_ids = np.array([ids], dtype=np.int64)
        attention_mask = np.ones_like(input_ids)
        encoder_hidden = self.encoder.run(None, {"input_ids": input_ids, "attention_mask": attention_mask})[0]
        empty = np.zeros((1, self.num_heads, 0, self.head_dim), dtype=np.float32)
        past = {name: empty for name in self.past_names}
        encoder_past = {}
        next_token = DECODER_START_ID
        generated = []
        for step in range(int(len(ids) * 1.5) + 10):
            feeds = {"input_ids": np.array([[next_token]], dtype=np.int64), "encoder_attention_mask": attention_mask,
                     "encoder_hidden_states": encoder_hidden, "use_cache_branch": np.array([step > 0])}
            feeds.update(past)
            outputs = dict(zip(self.output_names, self.decoder.run(None, feeds)))
            next_token = int(np.argmax(outputs["logits"][0, -1]))
            if next_token == EOS_ID:
                break
            generated.append(next_token)
            for name in self.past_names:
                present = name.replace("past_key_values.", "present.")
                if ".encoder." in name:
                    if step == 0:
                        encoder_past[name] = outputs[present]
                    past[name] = encoder_past[name]
                else:
                    past[name] = outputs[present]
        return postprocess(text, self.tokenizer.decode(generated, skip_special_tokens=True))


def typo_like(x, y):
    """A slip of the keys: one letter edit, and the first letter kept (or only a dropped one
    restored). Another first letter or a stripped prefix ("асимметрично" -> "симметрично") is another word."""
    x, y = x.lower(), y.lower()
    if x[:1] != y[:1] and x != y[1:]:
        return False
    previous = list(range(len(y) + 1))
    for i, cx in enumerate(x, 1):
        row = [i]
        for j, cy in enumerate(y, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (cx != cy)))
        previous = row
    return previous[-1] <= 1


def same_lemma(x, y):
    lx = {p.normal_form for p in morph.parse(x.lower())[:3]}
    ly = {p.normal_form for p in morph.parse(y.lower())[:3]}
    return bool(lx & ly)


def edit_class(before, after, lexicon):
    b, a = before.strip(), after.strip()
    if (b, a) == ("", ","):
        return "comma"
    if (b, a) == (",", ""):
        return "comma_del"
    if WORD.findall(b) and WORD.findall(a):
        # joined/hyphenated spelling changes only spaces and hyphens BETWEEN letters, never case or edges:
        # "Угроза" -> "- угроза" after a code is not a spelling fix
        inner = b[:1].isalnum() and b[-1:].isalnum() and a[:1].isalnum() and a[-1:].isalnum()
        if inner and re.sub(r"[\s-]", "", b) == re.sub(r"[\s-]", "", a) and b != a:
            return "join"
        if any(not lexicon.known(w) for w in WORD.findall(b)) and all(lexicon.known(w) for w in WORD.findall(a)) \
                and len(WORD.findall(b)) == len(WORD.findall(a)) \
                and all(typo_like(x, y) for x, y in zip(WORD.findall(b), WORD.findall(a)) if x != y):
            return "typo"
        wb, wa = WORD.findall(b), WORD.findall(a)
        if len(wb) == len(wa) == 1 and wb[0] == b and wa[0] == a and b[0].isupper() == a[0].isupper() \
                and b.lower() != a.lower() and lexicon.known(a) and same_lemma(b, a):
            return "ending"
    return "other"


MESSAGES = {"typo": "Опечатка", "join": "Слитное, раздельное или дефисное написание",
            "comma": "Здесь нужна запятая", "comma_del": "Лишняя запятая", "ending": "Неверное окончание"}
# Edits kept on their own, as "error" (dictionary-checked slips of the keys, joined/hyphenated spelling).
LEVELS = {"typo": "error", "join": "error"}
# Edits of the fine-tuned model that are NOT kept on their own (SAGE-only commas / endings are 25-50% right) but
# VOTE: an earlier stage's mark with exactly this edit becomes an "error". class -> (rule, level of the mark):
#  - ending: a "check" MODEL_FORM finding;
#  - comma_del: a hidden "candidate" MODEL_COMMA_DEL (comma ensemble min DEL in [VOTE_DEL, sure) of checker.py): the
#    taggers alone are not sure enough to show it, with SAGE removing the same comma it is an error;
#  - added commas do not vote: confirmed check commas were 2 right / 3 false (and a false error on clean official).
# See sage-ft-report.md and sage-comma-band-report.md.
VOTES = {"ending": ("MODEL_FORM", "check"), "comma_del": ("MODEL_COMMA_DEL", "candidate")}


def trimmed(cls, start, end, before, after):
    """(start, end, fix) of the edit: a comma edit shrinks to the comma (an insertion or a one-char deletion, like the
    comma tagger's), an ending edit to its word without the spaces around it."""
    if cls in ("comma", "comma_del"):
        p = 0
        while p < min(len(before), len(after)) and before[p] == after[p]:
            p += 1
        q = 0
        while q < min(len(before), len(after)) - p and before[-1 - q] == after[-1 - q]:
            q += 1
        return start + p, end - q, after[p:len(after) - q]
    lead = len(before) - len(before.lstrip())
    return start + lead, end - (len(before) - len(before.rstrip()) ), after.strip()


# A capitalised adjective / participle / verb right after a comma is no title and no name ("..., Любая деятельность"):
# SAGE lowering it is kept as an error. Every other case edit of SAGE is dropped: nouns (titles, defined terms such as
# "Требования"), sentence starts and capitals of names were 3 right / 8 false on dev+test, see sage-case-report.md.
LOWERABLE_POS = {"ADJF", "ADJS", "PRTF", "PRTS", "VERB", "INFN", "ADVB", "PRED", "NPRO", "GRND"}
NOT_A_COMMON_WORD = ("Name", "Surn", "Patr", "Geox", "Orgn", "Abbr", "Trad")


def lowered_after_comma(src, start, end, before, after, quotes):
    """True for SAGE's edit "Слово" -> "слово" (first letter only) of a word that follows ", " outside quotes."""
    if len(before) < 4 or before[:1].isupper() is False or after != before[:1].lower() + before[1:] or not before[1:].islower():
        return False
    if src[max(0, start - 2):start] != ", " or any(a < start < b for a, b in quotes) or not before.isalpha():
        return False
    parse = morph.parse(before.lower())[0]
    return parse.tag.POS in LOWERABLE_POS and not any(g in parse.tag for g in NOT_A_COMMON_WORD)


def findings(src, out, lexicon, levels=None, seen=()):
    """Findings for the SAGE edits the policy keeps, as char spans of src.

    seen: the findings of the earlier stages for this sentence (same coordinates); levels: override of LEVELS
    (evaluation: every class at one level, no voting)."""
    explicit = levels is not None
    levels = levels if explicit else LEVELS
    a, b = TOKEN.findall(src), TOKEN.findall(out)
    starts, pos = [], 0
    for t in a:
        starts.append(pos)
        pos += len(t)
    starts.append(pos)
    first_lower = src.lstrip()[:1].islower()
    last_word = max((i for i, t in enumerate(a) if t.strip()), default=0)
    result = []
    quotes = quoted_spans(src)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        before, after = a[i1:i2], b[j1:j2]
        if op == "replace" and len(before) == len(after) == 1 and not explicit and \
                lowered_after_comma(src, starts[i1], starts[i2], before[0], after[0], quotes):
            result.append({"start": starts[i1], "end": starts[i2], "level": "error", "rule": "SAGE_CASE_LOWER",
                           "fix": after[0], "message": "Слово пишется с маленькой буквы"})
            continue
        if not allowed(before, after, i1 == 0, i2 > last_word, first_lower):
            continue
        cls = edit_class("".join(before), "".join(after), lexicon)
        level = levels.get(cls)
        if cls in MESSAGES and level is None and not explicit and cls in VOTES:
            start, end, fix = trimmed(cls, starts[i1], starts[i2], "".join(before), "".join(after))
            rule, mark = VOTES[cls]
            if any(f["level"] == mark and f["rule"] == rule and f["start"] == start and f["end"] == end
                   and f.get("fix") == fix for f in seen):
                result.append({"start": start, "end": end, "level": "error", "rule": "SAGE_" + cls.upper(), "fix": fix,
                               "message": MESSAGES[cls]})
        elif level:
            start, end, fix = starts[i1], starts[i2], "".join(after)
            if cls in ("comma", "comma_del", "ending"):
                start, end, fix = trimmed(cls, start, end, "".join(before), fix)
            result.append({"start": start, "end": end, "level": level, "rule": "SAGE_" + cls.upper(),
                           "fix": fix, "message": MESSAGES[cls]})
    return result
