"""The edit tagger (ruBERT-base + comma and word-form heads, optionally a spelling head) through onnxruntime.

Tokenisation and word alignment repeat training exactly (labels sit on each word's first subtoken).
"""
import json
import os

import numpy as np
from tokenizers import Tokenizer

from .text import words_of

MAX_TOKENS = 192
COMMA_LABELS = ("KEEP", "ADD", "DEL")
SPELL_LABELS = ("KEEP", "JOIN", "HYPHEN", "SPLIT", "LOWER", "UPPER")  # order of the head's outputs


def softmax(x):
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def decode(outputs, form_labels, word_pos, spell_labels=SPELL_LABELS):
    """Per-word dicts from the session outputs: (comma, form) or (comma, form, spell) logits, batch of one.

    "spell" is present only when the model has the spelling head."""
    cp, fp = softmax(outputs[0][0]), softmax(outputs[1][0])
    sp = softmax(outputs[2][0]) if len(outputs) > 2 else None
    result = []
    for w, t in sorted(word_pos.items()):
        k = int(fp[t].argmax())
        item = {"comma": {COMMA_LABELS[i]: float(cp[t, i]) for i in range(3)},
                "form": form_labels[k], "form_p": float(fp[t, k]), "form_keep_p": float(fp[t, 0])}
        if sp is not None:
            item["spell"] = {spell_labels[i]: float(sp[t, i]) for i in range(len(spell_labels))}
        result.append(item)
    return result


class EditTagger:
    def __init__(self, model_dir, threads=2):
        import onnxruntime as ort  # late: the decoding above is usable (and testable) without it
        meta = json.load(open(os.path.join(model_dir, "labels.json"), encoding="utf-8"))
        self.form_labels = meta["form_labels"]
        self.spell_labels = tuple(meta.get("spell_labels", SPELL_LABELS))
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        name = "model.onnx" if os.path.exists(os.path.join(model_dir, "model.onnx")) else "model-int8.onnx"
        self.session = ort.InferenceSession(os.path.join(model_dir, name), options, providers=["CPUExecutionProvider"])

    def predict(self, text):
        """Per word of words_of(text): {"comma": {KEEP, ADD, DEL}, "form", "form_p", "form_keep_p"} and, for a
        model with the spelling head, "spell": {KEEP, JOIN, HYPHEN, SPLIT, LOWER, UPPER};
        words past the token limit get no prediction (the list is shorter)."""
        enc = self.tokenizer.encode(text)
        starts = {m.start(): i for i, m in enumerate(words_of(text))}
        word_pos = {}
        for t, (a, b) in enumerate(enc.offsets):
            if b > a and a in starts and starts[a] not in word_pos:
                word_pos[starts[a]] = t
        ids = np.array([enc.ids], dtype=np.int64)
        outputs = self.session.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})
        return decode(outputs, self.form_labels, word_pos, self.spell_labels)
