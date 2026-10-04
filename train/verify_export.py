"""Check an exported ONNX tagger against the torch run it came from.

Usage: python verify_export.py <run_dir> <onnx_dir> <sentences.txt>   (one sentence per line, 50 are enough)
Compares the softmax of both heads on every token: the largest probability difference must stay below 1e-3,
as it did for the earlier exports. Run it with the export venv (torch, onnx, onnxruntime, tokenizers).
"""
import json
import os
import sys

import numpy as np
import onnxruntime as ort
import torch
from tokenizers import Tokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_tagger import TaggerModel  # noqa: E402

LIMIT = 1e-3
MAX_TOKENS = 192


def softmax(x):
    e = np.exp(x - x.max(-1, keepdims=True))
    return e / e.sum(-1, keepdims=True)


def main():
    run_dir, onnx_dir, sentences_path = sys.argv[1:4]
    meta = json.load(open(os.path.join(run_dir, "labels.json"), encoding="utf-8"))
    n_spell = len(meta.get("spell_labels", ()))
    model = TaggerModel(meta["base"], len(meta["form_labels"]), n_spell)
    model.load_state_dict(torch.load(os.path.join(run_dir, "model.pt"), map_location="cpu", weights_only=True))
    model.eval()
    tokenizer = Tokenizer.from_file(os.path.join(onnx_dir, "tokenizer.json"))
    tokenizer.enable_truncation(MAX_TOKENS)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(os.path.join(onnx_dir, "model.onnx"), options, providers=["CPUExecutionProvider"])
    sentences = [l.rstrip("\n") for l in open(sentences_path, encoding="utf-8") if l.strip()]
    worst = {"comma": 0.0, "form": 0.0}
    if n_spell:
        worst["spell"] = 0.0
    for text in sentences:
        ids = np.array([tokenizer.encode(text).ids], dtype=np.int64)
        mask = np.ones_like(ids)
        with torch.no_grad():
            torch_out = model(torch.from_numpy(ids), torch.from_numpy(mask))
        tc, tf = torch_out[0], torch_out[1]
        onnx_out = session.run(None, {"input_ids": ids, "attention_mask": mask})
        oc, of = onnx_out[0], onnx_out[1]
        if n_spell:
            worst["spell"] = max(worst["spell"], float(np.abs(softmax(torch_out[2].numpy()) - softmax(onnx_out[2])).max()))
        worst["comma"] = max(worst["comma"], float(np.abs(softmax(tc.numpy()) - softmax(oc)).max()))
        worst["form"] = max(worst["form"], float(np.abs(softmax(tf.numpy()) - softmax(of)).max()))
    print("%s: %d sentences, max probability difference comma %.2e, form %.2e%s -> %s" % (
        os.path.basename(os.path.normpath(onnx_dir)), len(sentences), worst["comma"], worst["form"],
        ", spell %.2e" % worst["spell"] if n_spell else "",
        "OK" if max(worst.values()) < LIMIT else "FAIL"))
    return 0 if max(worst.values()) < LIMIT else 1


if __name__ == "__main__":
    sys.exit(main())
