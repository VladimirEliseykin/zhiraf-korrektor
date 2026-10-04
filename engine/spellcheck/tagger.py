"""The edit tagger (ruBERT-base + comma and word-form heads) through onnxruntime.

Tokenisation and word alignment repeat training exactly (labels sit on each word's first subtoken).
"""
import json
import os

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from .text import words_of

MAX_TOKENS = 192
COMMA_LABELS = ("KEEP", "ADD", "DEL")


def softmax(x):
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


class EditTagger:
    def __init__(self, model_dir, threads=2):
        meta = json.load(open(os.path.join(model_dir, "labels.json"), encoding="utf-8"))
        self.form_labels = meta["form_labels"]
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        name = "model.onnx" if os.path.exists(os.path.join(model_dir, "model.onnx")) else "model-int8.onnx"
        self.session = ort.InferenceSession(os.path.join(model_dir, name), options, providers=["CPUExecutionProvider"])

    def predict(self, text):
        """Per word of words_of(text): {"comma": {KEEP, ADD, DEL}, "form", "form_p", "form_keep_p"};
        words past the token limit get no prediction (the list is shorter)."""
        enc = self.tokenizer.encode(text)
        starts = {m.start(): i for i, m in enumerate(words_of(text))}
        word_pos = {}
        for t, (a, b) in enumerate(enc.offsets):
            if b > a and a in starts and starts[a] not in word_pos:
                word_pos[starts[a]] = t
        ids = np.array([enc.ids], dtype=np.int64)
        cl, fl = self.session.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})
        cp, fp = softmax(cl[0]), softmax(fl[0])
        result = []
        for w, t in sorted(word_pos.items()):
            k = int(fp[t].argmax())
            result.append({"comma": {COMMA_LABELS[i]: float(cp[t, i]) for i in range(3)},
                           "form": self.form_labels[k], "form_p": float(fp[t, k]), "form_keep_p": float(fp[t, 0])})
        return result
