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

from .guards import TOKEN, allowed

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
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
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


def edit_class(before, after, lexicon):
    b, a = before.strip(), after.strip()
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
    return "other"


MESSAGES = {"typo": "Опечатка", "join": "Слитное, раздельное или дефисное написание"}


def findings(src, out, lexicon):
    """Findings for the SAGE edits the policy keeps, as char spans of src."""
    a, b = TOKEN.findall(src), TOKEN.findall(out)
    starts, pos = [], 0
    for t in a:
        starts.append(pos)
        pos += len(t)
    starts.append(pos)
    first_lower = src.lstrip()[:1].islower()
    last_word = max((i for i, t in enumerate(a) if t.strip()), default=0)
    result = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        before, after = a[i1:i2], b[j1:j2]
        if not allowed(before, after, i1 == 0, i2 > last_word, first_lower):
            continue
        cls = edit_class("".join(before), "".join(after), lexicon)
        if cls in MESSAGES:
            result.append({"start": starts[i1], "end": starts[i2], "level": "error", "rule": "SAGE_" + cls.upper(),
                           "fix": "".join(after), "message": MESSAGES[cls]})
    return result
