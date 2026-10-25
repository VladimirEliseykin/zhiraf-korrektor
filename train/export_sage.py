"""Export a SAGE (T5 seq2seq) HF model dir to the ONNX files engine/spellcheck/sage.py reads.

    python export_sage.py MODEL_DIR OUT_DIR [--check [--reference engine/models/sage] [--sentences FILE]]

Writes OUT_DIR/encoder_model.onnx, decoder_model_merged.onnx and tokenizer.json, with the I/O names of the
optimum layout the engine was built for:
  encoder_model:         input_ids, attention_mask -> last_hidden_state
  decoder_model_merged:  encoder_attention_mask, input_ids, encoder_hidden_states, past_key_values.N.{decoder,encoder}.{key,value},
                         use_cache_branch -> logits, present.N.{decoder,encoder}.{key,value}
The weights are fp32, opset 13 (what onnxruntime 1.14, the last one for Windows 7, reads with the legacy
exporter's plain ops), IR version capped at 8. The original engine/models/sage was written by optimum-onnx
(`optimum-cli export onnx --task text2text-generation-with-past --opset 13`, torch 2.4.1); no script of it was kept
and optimum 2.1 fails on T5 here (NormalizedConfig allow_new), so this exports the three graphs with the legacy
torch exporter and merges the two decoders with optimum's own `merge_decoders` (the If on use_cache_branch).
Needs: torch, transformers, onnx, optimum (for merge_decoders only), tokenizers.
--check: runs the engine's Sage class on the new files and on --reference over the sentences and compares outputs.
"""
import argparse
import json
import os
import sys
import tempfile

import onnx
import torch
from torch import nn
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
from transformers.cache_utils import DynamicCache, EncoderDecoderCache

OPSET = 13
IR = 8


class Encoder(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.encoder = model.encoder

    def forward(self, input_ids, attention_mask):
        return self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state


class Decoder(nn.Module):
    """First step (no past): returns logits and the whole present (decoder self-attention and encoder cross-attention)."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, encoder_attention_mask, input_ids, encoder_hidden_states):
        out = self.model(encoder_outputs=(encoder_hidden_states,), attention_mask=encoder_attention_mask,
                         decoder_input_ids=input_ids, use_cache=True, return_dict=True)
        flat = []
        for layer in out.past_key_values.to_legacy_cache():
            flat += list(layer)
        return (out.logits, *flat)


class DecoderWithPast(nn.Module):
    """Next steps: past in, only the new decoder self-attention key/value out (cross-attention stays as given)."""

    def __init__(self, model, layers):
        super().__init__()
        self.model = model
        self.layers = layers

    def forward(self, encoder_attention_mask, input_ids, *past):
        legacy = tuple(tuple(past[4 * i:4 * i + 4]) for i in range(self.layers))
        cache = EncoderDecoderCache.from_legacy_cache(legacy)
        # the encoder output is not needed: the cross-attention key/value come from the cache
        batch = input_ids.shape[0]
        enc = torch.zeros(batch, past[2].shape[2], self.model.config.d_model)
        out = self.model(encoder_outputs=(enc,), attention_mask=encoder_attention_mask, decoder_input_ids=input_ids,
                         past_key_values=cache, use_cache=True, return_dict=True)
        flat = []
        for layer in out.past_key_values.to_legacy_cache():
            flat += [layer[0], layer[1]]
        return (out.logits, *flat)


def names(prefix, layers, cross=True):
    out = []
    for i in range(layers):
        out += ["%s.%d.decoder.key" % (prefix, i), "%s.%d.decoder.value" % (prefix, i)]
        if cross:
            out += ["%s.%d.encoder.key" % (prefix, i), "%s.%d.encoder.value" % (prefix, i)]
    return out


def export(module, args, path, inputs, outputs, axes):
    torch.onnx.export(module, args, path, dynamo=False, opset_version=OPSET, input_names=inputs,
                      output_names=outputs, dynamic_axes=axes, do_constant_folding=True)


def compat_tokenizer_json(path):
    """tokenizers 0.20+ writes BPE merges as [a, b] pairs; 0.19 (pinned for Windows 7) only reads "a b" strings."""
    data = json.load(open(path, encoding="utf-8"))
    merges = data.get("model", {}).get("merges")
    if merges and isinstance(merges[0], list):
        data["model"]["merges"] = [" ".join(m) for m in merges]
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)


def export_all(model_dir, out_dir):
    from optimum.onnx.graph_transformations import merge_decoders
    os.makedirs(out_dir, exist_ok=True)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir, torch_dtype=torch.float32).eval()
    cfg = model.config
    layers, heads, dim = cfg.num_decoder_layers, cfg.num_heads, cfg.d_kv
    tmp = tempfile.mkdtemp(prefix="sage-export-")
    b, s, t = 2, 7, 5
    ids = torch.randint(5, 1000, (b, s))
    mask = torch.ones(b, s, dtype=torch.long)
    enc_path = os.path.join(out_dir, "encoder_model.onnx")
    export(Encoder(model), (ids, mask), enc_path, ["input_ids", "attention_mask"], ["last_hidden_state"],
           {"input_ids": {0: "batch_size", 1: "encoder_sequence_length"}, "attention_mask": {0: "batch_size", 1: "encoder_sequence_length"},
            "last_hidden_state": {0: "batch_size", 1: "encoder_sequence_length"}})
    with torch.no_grad():
        hidden = Encoder(model)(ids, mask)
    dec_ids = torch.randint(5, 1000, (b, 1))
    present = names("present", layers)
    axes = {"encoder_attention_mask": {0: "batch_size", 1: "encoder_sequence_length"},
            "input_ids": {0: "batch_size", 1: "decoder_sequence_length"},
            "encoder_hidden_states": {0: "batch_size", 1: "encoder_sequence_length"},
            "logits": {0: "batch_size", 1: "decoder_sequence_length"}}
    for n in present:
        axes[n] = {0: "batch_size", 2: "encoder_sequence_length_out" if ".encoder." in n else "past_decoder_sequence_length + 1"}
    dec_path = os.path.join(tmp, "decoder_model.onnx")
    export(Decoder(model), (mask, dec_ids, hidden), dec_path, ["encoder_attention_mask", "input_ids", "encoder_hidden_states"],
           ["logits"] + present, axes)
    # shapes of a real past: decoder side t tokens, encoder side s tokens
    past = []
    for _ in range(layers):
        past += [torch.randn(b, heads, t, dim), torch.randn(b, heads, t, dim), torch.randn(b, heads, s, dim), torch.randn(b, heads, s, dim)]
    pnames = names("past_key_values", layers)
    axes_p = {"encoder_attention_mask": axes["encoder_attention_mask"], "input_ids": axes["input_ids"], "logits": axes["logits"]}
    for n in pnames:
        axes_p[n] = {0: "batch_size", 2: "encoder_sequence_length" if ".encoder." in n else "past_decoder_sequence_length"}
    out_names = ["logits"] + names("present", layers, cross=False)
    for n in out_names[1:]:
        axes_p[n] = {0: "batch_size", 2: "past_decoder_sequence_length + 1"}
    wp_path = os.path.join(tmp, "decoder_with_past_model.onnx")
    export(DecoderWithPast(model, layers), (mask, dec_ids, *past), wp_path, ["encoder_attention_mask", "input_ids"] + pnames,
           out_names, axes_p)
    merge_decoders(dec_path, wp_path, strict=False, save_path=os.path.join(tmp, "decoder_model_merged.onnx"))
    merged = onnx.load(os.path.join(tmp, "decoder_model_merged.onnx"))
    for m, path in ((merged, os.path.join(out_dir, "decoder_model_merged.onnx")), (onnx.load(enc_path), enc_path)):
        m.ir_version = min(m.ir_version, IR)
        onnx.save(m, path)
    tok = AutoTokenizer.from_pretrained(model_dir)
    tok.backend_tokenizer.save(os.path.join(out_dir, "tokenizer.json"))
    compat_tokenizer_json(os.path.join(out_dir, "tokenizer.json"))
    for name in ("encoder_model.onnx", "decoder_model_merged.onnx", "tokenizer.json"):
        print("%s %.0f MB" % (name, os.path.getsize(os.path.join(out_dir, name)) / 2 ** 20))


def describe(model_dir):
    import onnxruntime as ort
    res = {}
    for f in ("encoder_model", "decoder_model_merged"):
        m = onnx.load(os.path.join(model_dir, f + ".onnx"), load_external_data=False)
        s = ort.InferenceSession(os.path.join(model_dir, f + ".onnx"), providers=["CPUExecutionProvider"])
        res[f] = {"ir": m.ir_version, "opset": [(o.domain, o.version) for o in m.opset_import],
                  "inputs": [i.name for i in s.get_inputs()], "outputs": [o.name for o in s.get_outputs()]}
    return res


def check(new_dir, reference, sentences, model_dir, threads=2):
    """Same I/O names / IR / opset as the reference, and the engine's Sage gives identical corrections."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
    from spellcheck.sage import Sage
    a, b = describe(new_dir), describe(reference)
    for f in a:
        print(f, "IR", a[f]["ir"], "(reference %d)" % b[f]["ir"], "opset", a[f]["opset"], "| same input names:",
              sorted(a[f]["inputs"]) == sorted(b[f]["inputs"]), "| same output names:", sorted(a[f]["outputs"]) == sorted(b[f]["outputs"]))
        assert a[f]["ir"] <= IR and all(v <= 13 for d, v in a[f]["opset"] if d == "")
    new, ref = Sage(new_dir, threads), Sage(reference, threads)
    tok = AutoTokenizer.from_pretrained(model_dir)
    hf = AutoModelForSeq2SeqLM.from_pretrained(model_dir).eval()
    same_ref = same_hf = 0
    for text in sentences:
        o_new, o_ref = new.correct(text), ref.correct(text)
        enc = tok([text], return_tensors="pt")
        with torch.inference_mode():
            g = hf.generate(**enc, max_length=int(enc["input_ids"].size(1) * 1.5) + 4)
        o_hf = tok.decode(g[0], skip_special_tokens=True)
        from spellcheck.sage import postprocess
        o_hf = postprocess(text, o_hf)
        same_ref += o_new == o_ref
        same_hf += o_new == o_hf
        if o_new != o_ref or o_new != o_hf:
            print("DIFF", repr(text), "\n  new:", repr(o_new), "\n  ref:", repr(o_ref), "\n  hf: ", repr(o_hf))
    print("outputs equal to the reference ONNX: %d/%d, to HF generate: %d/%d" % (same_ref, len(sentences), same_hf, len(sentences)))
    return same_ref == len(sentences)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--reference", default="/home/general/vm/win7/engine/models/sage")
    ap.add_argument("--sentences", help="jsonl with src, or a text file with one sentence per line")
    ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    export_all(a.model, a.out)
    if a.check:
        path = a.sentences or "/home/general/vm/win7/data-public/converted/dev2.jsonl"
        sents = []
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                sents.append(json.loads(line)["src"] if line.startswith("{") else line)
        step = max(1, len(sents) // a.n)
        ok = check(a.out, a.reference, sents[::step][:a.n], a.model)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
