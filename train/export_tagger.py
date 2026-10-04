"""Export a tagger run to ONNX (fp32 and dynamically quantised int8) for the Windows 7 runtime.

Usage (export venv: torch 2.4.1, transformers 4.44.2, onnx, onnxruntime):
    python export_tagger.py <run_dir> <out_dir>
Writes model.onnx and model-int8.onnx plus labels.json and tokenizer files. IR version is set to 8:
onnxruntime 1.14, the last one for Windows 7, reads nothing newer.
"""
import json
import os
import shutil
import sys

import onnx
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from torch import nn
from transformers import AutoModel

N_COMMA = 3


class TaggerModel(nn.Module):
    """Same layout as tagger.TaggerModel (state dict keys must match)."""

    def __init__(self, base, n_form):
        super().__init__()
        # eager attention exports to plain MatMul/Softmax; SDPA needs opset 14+
        self.encoder = AutoModel.from_pretrained(base, attn_implementation="eager")
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.comma_head = nn.Linear(hidden, N_COMMA)
        self.form_head = nn.Linear(hidden, n_form)

    def forward(self, input_ids, attention_mask):
        h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return self.comma_head(h), self.form_head(h)


def main():
    run_dir, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    meta = json.load(open(os.path.join(run_dir, "labels.json"), encoding="utf-8"))
    model = TaggerModel(meta["base"], len(meta["form_labels"]))
    model.load_state_dict(torch.load(os.path.join(run_dir, "model.pt"), map_location="cpu", weights_only=True))
    model.eval()
    ids = torch.tensor([[2, 1000, 1001, 1002, 3]])
    fp32 = os.path.join(out_dir, "model.onnx")
    torch.onnx.export(model, (ids, torch.ones_like(ids)), fp32, opset_version=13,
                      input_names=["input_ids", "attention_mask"], output_names=["comma_logits", "form_logits"],
                      dynamic_axes={"input_ids": {0: "b", 1: "t"}, "attention_mask": {0: "b", 1: "t"},
                                    "comma_logits": {0: "b", 1: "t"}, "form_logits": {0: "b", 1: "t"}})
    m = onnx.load(fp32)
    m.ir_version = 8
    onnx.save(m, fp32)
    int8 = os.path.join(out_dir, "model-int8.onnx")
    quantize_dynamic(fp32, int8, weight_type=QuantType.QInt8)
    m = onnx.load(int8)
    m.ir_version = 8
    onnx.save(m, int8)
    for name in os.listdir(run_dir):
        if name in ("labels.json", "vocab.txt", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
            shutil.copy(os.path.join(run_dir, name), out_dir)
    for name in ("model.onnx", "model-int8.onnx"):
        print("%s %.0f MB" % (name, os.path.getsize(os.path.join(out_dir, name)) / 2 ** 20))


if __name__ == "__main__":
    main()
