"""Edit tagger: a small BERT that labels every word with a comma action and a word-form action.

train:   python tagger.py train --corpus corpus.jsonl --exclude a.jsonl b.json ... --out run_dir
predict: used from evaluation code via EditTagger(run_dir).predict(text)
"""
import argparse
import collections
import json
import math
import os
import random
import sys
import time

import torch
from torch import nn
from transformers import AutoModel, AutoTokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corrupt import COMMA_ADD, COMMA_DEL, COMMA_KEEP, FORM_KEEP, corrupt, restore, words_of  # noqa: E402
import overlap_check  # noqa: E402

COMMA_LABELS = [COMMA_KEEP, COMMA_ADD, COMMA_DEL]
MAX_TOKENS = 192


def device():
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return torch.device("xpu")
    return torch.device("cpu")


class TaggerModel(nn.Module):
    def __init__(self, base, n_form):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(base)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.comma_head = nn.Linear(hidden, len(COMMA_LABELS))
        self.form_head = nn.Linear(hidden, n_form)

    def forward(self, input_ids, attention_mask):
        h = self.dropout(self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state)
        return self.comma_head(h), self.form_head(h)


def encode(tokenizer, text, comma=None, form=None, form_index=None):
    """Tokenize text; put each word's labels on its first subtoken, -100 elsewhere."""
    enc = tokenizer(text, return_offsets_mapping=True, truncation=True, max_length=MAX_TOKENS)
    starts = {m.start(): i for i, m in enumerate(words_of(text))}
    comma_y = [-100] * len(enc["input_ids"])
    form_y = [-100] * len(enc["input_ids"])
    word_pos = {}
    for t, (a, b) in enumerate(enc["offset_mapping"]):
        if b > a and a in starts and starts[a] not in word_pos:
            w = starts[a]
            word_pos[w] = t
            if comma is not None:
                comma_y[t] = COMMA_LABELS.index(comma[w])
                form_y[t] = form_index.get(form[w], -100)
    return enc["input_ids"], comma_y, form_y, word_pos


def collate(batch, pad_id):
    width = max(len(x[0]) for x in batch)
    ids = torch.full((len(batch), width), pad_id)
    mask = torch.zeros((len(batch), width), dtype=torch.long)
    cy = torch.full((len(batch), width), -100)
    fy = torch.full((len(batch), width), -100)
    for r, (i, c, f) in enumerate(batch):
        ids[r, :len(i)] = torch.tensor(i)
        mask[r, :len(i)] = 1
        cy[r, :len(c)] = torch.tensor(c)
        fy[r, :len(f)] = torch.tensor(f)
    return ids, mask, cy, fy


def load_corpus(path, exclude_paths):
    # compare without punctuation, case and ё: an evaluation sentence must not reach training
    # even when it differs from its twin only by the very commas or letters the model is scored on
    exclude = set()
    for p in exclude_paths:
        exclude |= overlap_check.eval_keys(p)
    sents = [json.loads(line)["src"] for line in open(path, encoding="utf-8")]
    return [s for s in sents if overlap_check.key(s) not in exclude], len(exclude)


ERROR_DENSITY = {"p_clean": 0.25, "max_edits": 3, "p_single": 0.0, "p_form": 0.45, "placement": True}


def make_examples(sents, seed):
    """Corrupt every sentence once; keep only examples whose labels exactly restore the original."""
    rng = random.Random(seed)
    out = []
    for s in sents:
        c, cm, fm = corrupt(s, rng, **ERROR_DENSITY)
        if restore(c, cm, fm) == s:
            out.append((c, cm, fm))
    return out


def build_form_vocab(examples, min_count):
    counts = collections.Counter(l for _, _, fm in examples for l in fm if l != FORM_KEEP)
    labels = [FORM_KEEP] + [l for l, n in counts.most_common() if n >= min_count]
    return labels


def evaluate(model, tokenizer, examples, form_labels, dev):
    form_index = {l: i for i, l in enumerate(form_labels)}
    stats = collections.Counter()
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(examples), 64):
            chunk = examples[start:start + 64]
            batch = [encode(tokenizer, c, cm, fm, form_index)[:3] for c, cm, fm in chunk]
            ids, mask, cy, fy = collate(batch, tokenizer.pad_token_id)
            cl, fl = model(ids.to(dev), mask.to(dev))
            cp, fp = cl.argmax(-1).cpu(), fl.argmax(-1).cpu()
            for gold, pred, name in ((cy, cp, "comma"), (fy, fp, "form")):
                valid = gold != -100
                g, p = gold[valid], pred[valid]
                stats[name + "_tp"] += int(((p == g) & (g != 0)).sum())
                stats[name + "_fp"] += int(((p != g) & (p != 0)).sum())
                stats[name + "_fn"] += int(((p != g) & (g != 0)).sum())
    model.train()
    report = {}
    for name in ("comma", "form"):
        tp, fp, fn = stats[name + "_tp"], stats[name + "_fp"], stats[name + "_fn"]
        report[name] = {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3)}
    return report


def train(args):
    # round 5: real documents have ~0.13 errors per sentence; a much denser synthetic error rate
    # teaches the model to "find" errors in correct text, so the density is configurable
    ERROR_DENSITY.update(p_clean=args.p_clean, max_edits=args.max_edits, p_single=args.p_single, p_form=args.p_form,
                         placement=not args.uniform_placement)
    dev = device()
    print("device:", dev, flush=True)
    sents, n_excl = load_corpus(args.corpus, args.exclude)
    random.Random(0).shuffle(sents)
    val_sents, train_sents = sents[:args.val], sents[args.val:]
    print("corpus %d sentences (excluded %d eval sentences), train %d val %d" % (
        len(sents), n_excl, len(train_sents), len(val_sents)), flush=True)
    val = make_examples(val_sents, seed=12345)
    if args.init:
        # warm start: the head layout must match the previous run, so reuse its label list
        init_meta = json.load(open(os.path.join(args.init, "labels.json"), encoding="utf-8"))
        form_labels = init_meta["form_labels"]
    else:
        probe = make_examples(train_sents[:50000], seed=1)
        form_labels = build_form_vocab(probe, args.min_label_count)
    form_index = {l: i for i, l in enumerate(form_labels)}
    print("form labels:", len(form_labels), flush=True)

    os.makedirs(args.out, exist_ok=True)
    if args.init:
        tokenizer = AutoTokenizer.from_pretrained(args.init)  # warm start: the tokenizer the weights learned with
    else:
        # ruBert models are cased; the default BertTokenizer lowercases and strips accents, turning
        # "информационной" into "информационнои" and hiding exactly the endings the model has to fix
        tokenizer = AutoTokenizer.from_pretrained(args.base, do_lower_case=False, strip_accents=False)
    tokenizer.save_pretrained(args.out)
    json.dump({"base": args.base, "form_labels": form_labels, "comma_labels": COMMA_LABELS},
              open(os.path.join(args.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    model = TaggerModel(args.base, len(form_labels))
    if args.init:
        model.load_state_dict(torch.load(os.path.join(args.init, "model.pt"), map_location="cpu", weights_only=True))
        print("warm start from", args.init, flush=True)
    model = model.to(dev)
    optim = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps_per_epoch = math.ceil(len(train_sents) / args.batch)
    total = steps_per_epoch * args.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim, lambda s: min(1.0, s / max(1, int(0.05 * total))) * max(0.0, (total - s) / total))
    loss_fn = nn.CrossEntropyLoss(ignore_index=-100)
    step, start_epoch, start_batch = 0, 0, 0
    ckpt_path = os.path.join(args.out, "checkpoint.pt")
    if os.path.exists(ckpt_path):
        # resume after a crash or a memory-pressure kill: same order, same errors, same schedule
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
        model.load_state_dict(ckpt["model"])
        optim.load_state_dict(ckpt["optim"])
        sched.load_state_dict(ckpt["sched"])
        step, start_epoch, start_batch = ckpt["step"], ckpt["epoch"], ckpt["batch"]
        print("resumed at epoch %d batch %d (step %d)" % (start_epoch, start_batch, step), flush=True)
    t0 = time.time()
    for epoch in range(start_epoch, args.epochs):
        # errors are generated batch by batch (not the whole corpus at once) to keep memory small
        order = list(range(len(train_sents)))
        random.Random(epoch).shuffle(order)
        first = start_batch if epoch == start_epoch else 0
        for bi in range(first, steps_per_epoch):
            idx = order[bi * args.batch:(bi + 1) * args.batch]
            chunk = make_examples([train_sents[k] for k in idx], seed=(1000 + epoch) * 1_000_003 + bi)
            if not chunk:
                continue
            batch = [encode(tokenizer, c, cm, fm, form_index)[:3] for c, cm, fm in chunk]
            ids, mask, cy, fy = collate(batch, tokenizer.pad_token_id)
            ids, mask, cy, fy = ids.to(dev), mask.to(dev), cy.to(dev), fy.to(dev)
            with torch.autocast(device_type=dev.type, dtype=torch.bfloat16, enabled=dev.type == "xpu"):
                cl, fl = model(ids, mask)
            loss = loss_fn(cl.float().reshape(-1, cl.shape[-1]), cy.reshape(-1)) + \
                loss_fn(fl.float().reshape(-1, fl.shape[-1]), fy.reshape(-1))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            if step % 200 == 0:
                print("epoch %d step %d/%d loss %.4f  %.1f min" % (epoch, step, total, loss.item(), (time.time() - t0) / 60), flush=True)
            if step % args.save_every == 0:
                tmp = ckpt_path + ".tmp"
                torch.save({"model": model.state_dict(), "optim": optim.state_dict(), "sched": sched.state_dict(),
                            "step": step, "epoch": epoch, "batch": bi + 1}, tmp)
                os.replace(tmp, ckpt_path)  # atomic: a kill during saving never corrupts the checkpoint
        report = evaluate(model, tokenizer, val, form_labels, dev)
        print("epoch %d validation: %s" % (epoch, json.dumps(report)), flush=True)
        torch.save(model.state_dict(), os.path.join(args.out, "model-epoch%d.pt" % epoch))
        torch.save(model.state_dict(), os.path.join(args.out, "model.pt"))
        torch.save({"model": model.state_dict(), "optim": optim.state_dict(), "sched": sched.state_dict(),
                    "step": step, "epoch": epoch + 1, "batch": 0}, ckpt_path)


class EditTagger:
    """Inference wrapper: returns per-word probabilities for comma and form actions."""

    def __init__(self, run_dir, epoch=None):
        meta = json.load(open(os.path.join(run_dir, "labels.json"), encoding="utf-8"))
        self.form_labels = meta["form_labels"]
        self.tokenizer = AutoTokenizer.from_pretrained(run_dir)
        self.session = None
        onnx_files = [n for n in ("model-int8.onnx", "model.onnx") if os.path.exists(os.path.join(run_dir, n))]
        if not os.path.exists(os.path.join(run_dir, "model.pt")) and onnx_files:
            # an export from export_tagger.py: run it the way the Windows 7 program will
            import onnxruntime
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 4
            self.session = onnxruntime.InferenceSession(os.path.join(run_dir, onnx_files[0]), options,
                                                        providers=["CPUExecutionProvider"])
            return
        self.model = TaggerModel(meta["base"], len(self.form_labels))
        name = "model.pt" if epoch is None else "model-epoch%d.pt" % epoch
        self.model.load_state_dict(torch.load(os.path.join(run_dir, name), map_location="cpu", weights_only=True))
        self.model.eval()

    def predict(self, text):
        ids, _, _, word_pos = encode(self.tokenizer, text)
        if self.session is not None:
            import numpy
            cl, fl = self.session.run(None, {"input_ids": numpy.array([ids], dtype=numpy.int64),
                                             "attention_mask": numpy.ones((1, len(ids)), dtype=numpy.int64)})
            cl, fl = torch.from_numpy(cl), torch.from_numpy(fl)
        else:
            with torch.inference_mode():
                cl, fl = self.model(torch.tensor([ids]), torch.ones((1, len(ids)), dtype=torch.long))
        cp, fp = cl[0].softmax(-1), fl[0].softmax(-1)
        result = []
        for w, t in sorted(word_pos.items()):
            c = {COMMA_LABELS[k]: float(cp[t, k]) for k in range(len(COMMA_LABELS))}
            k = int(fp[t].argmax())
            result.append({"comma": c, "form": self.form_labels[k], "form_p": float(fp[t, k]),
                           "form_keep_p": float(fp[t, 0])})
        return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("train")
    t.add_argument("--corpus", required=True)
    t.add_argument("--exclude", nargs="*", default=[])
    t.add_argument("--out", required=True)
    t.add_argument("--base", default="/home/general/vm/win7/models/rubert-tiny2")
    t.add_argument("--epochs", type=int, default=3)
    t.add_argument("--batch", type=int, default=32)
    t.add_argument("--lr", type=float, default=1e-4)
    t.add_argument("--val", type=int, default=3000)
    t.add_argument("--min-label-count", type=int, default=20)
    t.add_argument("--init", default=None, help="run dir to warm-start from (same base model)")
    t.add_argument("--save-every", type=int, default=2000, help="steps between resumable checkpoints")
    t.add_argument("--p-clean", type=float, default=0.25, help="share of sentences left without errors")
    t.add_argument("--max-edits", type=int, default=3)
    t.add_argument("--p-single", type=float, default=0.0, help="probability that a corrupted sentence gets exactly one error")
    t.add_argument("--p-form", type=float, default=0.45, help="share of word-form edits among the errors (rest are commas)")
    t.add_argument("--uniform-placement", action="store_true",
                   help="pick error places uniformly (generator before round 4, as in round 3)")
    a = ap.parse_args()
    if a.cmd == "train":
        train(a)
