"""Edit tagger: a small BERT that labels every word with a comma action and a word-form action,
and optionally (--spell) a spelling action: JOIN / HYPHEN / SPLIT / LOWER / UPPER.

train:   python tagger.py train --corpus corpus.jsonl --exclude a.jsonl b.json ... --out run_dir
predict: used from evaluation code via EditTagger(run_dir).predict(text)
"""
import argparse
import collections
import json
import math
import multiprocessing
import os
import random
import sys
import time

import torch
from torch import nn
from transformers import AutoConfig, AutoModel, AutoTokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corrupt import (COMMA_ADD, COMMA_DEL, COMMA_KEEP, FORM_KEEP, SPELL_LABELS,  # noqa: E402
                     corrupt, corrupt_spell, restore, words_of)
import overlap_check  # noqa: E402
import pair_labels  # noqa: E402

COMMA_LABELS = [COMMA_KEEP, COMMA_ADD, COMMA_DEL]
MAX_TOKENS = 192
MAX_BAD_STEPS = 20  # non-finite steps in a row before a run gives up


def device(force=None):
    """force="cpu" keeps a run off the accelerator that another job is using."""
    if force:
        return torch.device(force)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return torch.device("xpu")
    return torch.device("cpu")


class TaggerModel(nn.Module):
    def __init__(self, base, n_form, n_spell=0):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(base)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(0.1)
        self.comma_head = nn.Linear(hidden, len(COMMA_LABELS))
        self.form_head = nn.Linear(hidden, n_form)
        # models trained before the spelling head have no such weights: the key must not exist for them
        self.spell_head = nn.Linear(hidden, n_spell) if n_spell else None

    def forward(self, input_ids, attention_mask):
        h = self.dropout(self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state)
        if self.spell_head is None:
            return self.comma_head(h), self.form_head(h)
        return self.comma_head(h), self.form_head(h), self.spell_head(h)


def load_weights(model, state):
    """Load a state dict; a checkpoint without the spelling head leaves that head freshly initialised.

    Anything else missing or unexpected is still an error."""
    missing, unexpected = model.load_state_dict(state, strict=False)
    missing = [k for k in missing if not k.startswith("spell_head.")]
    if missing or unexpected:
        raise RuntimeError("checkpoint does not fit the model: missing %s, unexpected %s" % (missing, unexpected))
    return [k for k in model.state_dict() if k.startswith("spell_head.") and k not in state]


def load_base_tokenizer(base):
    """Tokenizer of a fresh base model.

    ruBert models are cased; the default BertTokenizer lowercases and strips accents, turning
    "информационной" into "информационнои" and hiding exactly the endings the model has to fix.
    RoBERTa (byte-level BPE) gets add_prefix_space=True: every word, the first one too, is tokenized as
    "Ġword" like in running text; the offsets exclude the space (trim_offsets), so a word's first token
    starts exactly at the word, as with WordPiece."""
    if AutoConfig.from_pretrained(base).model_type == "roberta":
        return AutoTokenizer.from_pretrained(base, add_prefix_space=True)
    return AutoTokenizer.from_pretrained(base, do_lower_case=False, strip_accents=False)


def encode(tokenizer, text, comma=None, form=None, form_index=None, spell=None):
    """Tokenize text; put each word's labels on its first subtoken, -100 elsewhere.

    Labels are aligned with words_of(text), the words of the corrupted text. Returns
    (ids, comma_y, form_y, word_pos, spell_y); spell_y stays -100 without spell labels."""
    enc = tokenizer(text, return_offsets_mapping=True, truncation=True, max_length=MAX_TOKENS)
    starts = {m.start(): i for i, m in enumerate(words_of(text))}
    comma_y = [-100] * len(enc["input_ids"])
    form_y = [-100] * len(enc["input_ids"])
    spell_y = [-100] * len(enc["input_ids"])
    word_pos = {}
    for t, (a, b) in enumerate(enc["offset_mapping"]):
        if b > a and a in starts and starts[a] not in word_pos:
            w = starts[a]
            word_pos[w] = t
            if comma is not None:
                comma_y[t] = COMMA_LABELS.index(comma[w])
                form_y[t] = form_index.get(form[w], -100)
                if spell is not None:
                    spell_y[t] = SPELL_LABELS.index(spell[w])
    return enc["input_ids"], comma_y, form_y, word_pos, spell_y


def collate(batch, pad_id):
    width = max(len(x[0]) for x in batch)
    ids = torch.full((len(batch), width), pad_id)
    mask = torch.zeros((len(batch), width), dtype=torch.long)
    cy = torch.full((len(batch), width), -100)
    fy = torch.full((len(batch), width), -100)
    sy = torch.full((len(batch), width), -100)
    for r, (i, c, f, s) in enumerate(batch):
        ids[r, :len(i)] = torch.tensor(i)
        mask[r, :len(i)] = 1
        cy[r, :len(c)] = torch.tensor(c)
        fy[r, :len(f)] = torch.tensor(f)
        sy[r, :len(s)] = torch.tensor(s)
    return ids, mask, cy, fy, sy


def load_corpus(path, exclude_paths, skip_lines=(), skip_keys=()):
    """Sentences of the corpus without the evaluation ones (and, for real-pair runs, without skip_lines, 1-based
    line numbers of path, and without sentences whose key is in skip_keys: the clean twins of the real pairs)."""
    # compare without punctuation, case and ё: an evaluation sentence must not reach training
    # even when it differs from its twin only by the very commas or letters the model is scored on
    exclude = set()
    for p in exclude_paths:
        exclude |= overlap_check.eval_keys(p)
    skip_lines = set(skip_lines)
    sents = [json.loads(line)["src"] for n, line in enumerate(open(path, encoding="utf-8"), 1) if n not in skip_lines]
    skip = exclude | set(skip_keys)
    return [s for s in sents if overlap_check.key(s) not in skip], len(exclude)


def load_pair_examples(paths, exclude_paths=()):
    """Real error pairs as training examples (text, comma labels, form labels, None) plus the keys of the
    sentences they come from. Files are the jsonl of pair_labels.py (with labels) or raw {"src", "gold"} pairs,
    which are converted on the fly. A pair that coincides with an evaluation sentence is dropped."""
    exclude = set()
    for p in exclude_paths:
        exclude |= overlap_check.eval_keys(p)
    records = []
    for path in paths:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        records += rows if rows and "comma" in rows[0] else pair_labels.convert(rows)[0]
    kept = [r for r in records if overlap_check.key(r["src"]) not in exclude and overlap_check.key(r["gold"]) not in exclude]
    keys = {overlap_check.key(t) for r in kept for t in (r["src"], r["gold"])}
    return [(r["src"], r["comma"], r["form"], None) for r in kept], keys, len(records) - len(kept)


def pairs_per_batch(batch, share):
    """How many examples of a batch come from the real pairs: 0 without pairs, else at least 1 and at most batch - 1."""
    if not share:
        return 0
    return min(batch - 1, max(1, round(batch * share)))


def pair_indices(n, k, first, seed, cache=None):
    """Indices of the k real pairs at positions first .. first+k-1 of the endless stream "pass 0, pass 1, ...", each
    pass a fresh shuffle of range(n) under the seed. Stateless, so it is the same in a worker or after a resume."""
    cache = {} if cache is None else cache
    out = []
    for p in range(first, first + k):
        number = p // n
        if number not in cache:
            order = list(range(n))
            random.Random(31_337 + number + 1_000_003 * seed).shuffle(order)
            cache.clear()  # a batch spans at most two passes; older ones are never asked for again
            cache[number] = order
        out.append(cache[number][p % n])
    return out


ERROR_DENSITY = {"p_clean": 0.25, "max_edits": 3, "p_single": 0.0, "p_form": 0.45, "placement": True}
SPELL_DENSITY = {"p_spell": 0.0}  # share of sentences that also get a spelling error; 0 = no spelling head


def make_examples(sents, seed):
    """Corrupt every sentence once; keep only examples whose labels exactly restore the original.

    Examples are (text, comma labels, form labels, spell labels or None). With the spelling head off the
    generator is called exactly as before, so a seed gives the same corrupted texts as the old recipes."""
    rng = random.Random(seed)
    out = []
    spelling = SPELL_DENSITY["p_spell"] > 0
    for s in sents:
        if spelling:
            c, cm, fm, sm = corrupt_spell(s, rng, **SPELL_DENSITY, **ERROR_DENSITY)
        else:
            (c, cm, fm), sm = corrupt(s, rng, **ERROR_DENSITY), None
        if restore(c, cm, fm, sm) == s:
            out.append((c, cm, fm, sm))
    return out


def build_form_vocab(examples, min_count):
    counts = collections.Counter(l for _, _, fm, _ in examples for l in fm if l != FORM_KEEP)
    labels = [FORM_KEEP] + [l for l, n in counts.most_common() if n >= min_count]
    return labels


def prf(tp, fp, fn):
    return {"precision": round(tp / max(1, tp + fp), 3), "recall": round(tp / max(1, tp + fn), 3)}


def evaluate(model, tokenizer, examples, form_labels, dev):
    """Precision/recall of the comma and form heads (non-KEEP classes) and, with a spelling head,
    of every spelling label ("spell" in the report, "spell_<LABEL>" with the gold count "n")."""
    form_index = {l: i for i, l in enumerate(form_labels)}
    spelling = model.spell_head is not None
    stats = collections.Counter()
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(examples), 64):
            chunk = examples[start:start + 64]
            batch = []
            for c, cm, fm, sm in chunk:
                e = encode(tokenizer, c, cm, fm, form_index, sm)
                batch.append(e[:3] + e[4:])
            ids, mask, cy, fy, sy = collate(batch, tokenizer.pad_token_id)
            out = model(ids.to(dev), mask.to(dev))
            heads = [(cy, out[0], "comma"), (fy, out[1], "form")]
            if spelling:
                heads.append((sy, out[2], "spell"))
            for gold, logits, name in heads:
                pred = logits.argmax(-1).cpu()
                valid = gold != -100
                g, p = gold[valid], pred[valid]
                stats[name + "_tp"] += int(((p == g) & (g != 0)).sum())
                stats[name + "_fp"] += int(((p != g) & (p != 0)).sum())
                stats[name + "_fn"] += int(((p != g) & (g != 0)).sum())
                if name == "spell":
                    for k, label in enumerate(SPELL_LABELS[1:], 1):
                        stats["spell_%s_tp" % label] += int(((p == k) & (g == k)).sum())
                        stats["spell_%s_fp" % label] += int(((p == k) & (g != k)).sum())
                        stats["spell_%s_fn" % label] += int(((p != k) & (g == k)).sum())
    model.train()
    report = {}
    for name in ("comma", "form") + (("spell",) if spelling else ()):
        report[name] = prf(stats[name + "_tp"], stats[name + "_fp"], stats[name + "_fn"])
    if spelling:
        for label in SPELL_LABELS[1:]:
            tp, fp, fn = (stats["spell_%s_%s" % (label, k)] for k in ("tp", "fp", "fn"))
            report["spell_" + label] = dict(prf(tp, fp, fn), n=tp + fn)
    return report


_GEN = {}  # what _make_batch needs; set before the worker pool forks, so the workers inherit it


def _make_batch(bi):
    """Corrupted and encoded examples of batch bi: the same seed whether built here or in a worker,
    so --workers changes the speed and nothing else."""
    g = _GEN
    syn = g["batch"] - g["k"]  # examples from the generator; k come from the real pairs (0 = as before)
    idx = g["order"][bi * syn:(bi + 1) * syn]
    chunk = make_examples([g["sents"][k] for k in idx],
                          seed=(1000 + g["epoch"]) * 1_000_003 + bi + 7_919_000_000 * g["seed"])
    if g["k"]:
        first = (g["epoch"] * g["steps"] + bi) * g["k"]
        chunk = chunk + [g["pairs"][p] for p in pair_indices(len(g["pairs"]), g["k"], first, g["seed"], g["pair_cache"])]
    batch = []
    for c, cm, fm, sm in chunk:
        e = encode(g["tokenizer"], c, cm, fm, g["form_index"], sm)
        batch.append(e[:3] + e[4:])
    return batch


def train(args):
    # round 5: real documents have ~0.13 errors per sentence; a much denser synthetic error rate
    # teaches the model to "find" errors in correct text, so the density is configurable
    ERROR_DENSITY.update(p_clean=args.p_clean, max_edits=args.max_edits, p_single=args.p_single, p_form=args.p_form,
                         placement=not args.uniform_placement)
    if args.realistic:
        # round 9: errors as in the dev profile (train/error_profile.py); the count follows the sentence length
        ERROR_DENSITY.update(realistic=True, error_rate=args.error_rate, form_scale=args.form_scale)
    SPELL_DENSITY.update(p_spell=args.p_spell if args.spell else 0.0)
    if args.threads:
        torch.set_num_threads(args.threads)
    dev = device(args.device)
    print("device:", dev, flush=True)
    pairs, k = [], 0
    skip_lines = [int(x) for x in open(args.exclude_lines).read().split()] if args.exclude_lines else []
    skip_keys = set()
    if args.pairs:
        pairs, skip_keys, n_cut = load_pair_examples(args.pairs.split(","), args.exclude)
        k = pairs_per_batch(args.batch, args.pairs_share)
        print("real pairs: %d examples (%d dropped as evaluation sentences), %d per batch of %d" % (
            len(pairs), n_cut, k, args.batch), flush=True)
        if not pairs:
            raise SystemExit("--pairs: no usable pair")
    sents, n_excl = load_corpus(args.corpus, args.exclude, skip_lines, skip_keys)
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
        tokenizer = load_base_tokenizer(args.base)
    tokenizer.save_pretrained(args.out)
    meta = {"base": args.base, "form_labels": form_labels, "comma_labels": COMMA_LABELS}
    if args.spell:
        meta["spell_labels"] = SPELL_LABELS  # absent for models without the head
    json.dump(meta, open(os.path.join(args.out, "labels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if args.seed:
        torch.manual_seed(args.seed)  # another start for the new heads: runs differ, ensembles gain
    model = TaggerModel(args.base, len(form_labels), len(SPELL_LABELS) if args.spell else 0)
    if args.init:
        fresh = load_weights(model, torch.load(os.path.join(args.init, "model.pt"), map_location="cpu", weights_only=True))
        print("warm start from", args.init, ("(new head, random init: %s)" % ", ".join(fresh)) if fresh else "", flush=True)
    model = model.to(dev)
    optim = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    syn_batch = args.batch - k
    epoch_sents = int(len(train_sents) * args.epoch_fraction)
    steps_per_epoch = math.ceil(epoch_sents / syn_batch)
    total = steps_per_epoch * args.epochs
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim, lambda s: min(1.0, s / max(1, int(0.05 * total))) * max(0.0, (total - s) / total))
    loss_fn = nn.CrossEntropyLoss(ignore_index=-100)
    step, start_epoch, start_batch = 0, 0, 0
    bad_steps = 0
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
        random.Random(epoch + 1_000_000 * args.seed).shuffle(order)
        order = order[:epoch_sents]
        first = start_batch if epoch == start_epoch else 0
        _GEN.update(order=order, sents=train_sents, batch=args.batch, epoch=epoch, seed=args.seed,
                    tokenizer=tokenizer, form_index=form_index, k=k, pairs=pairs, steps=steps_per_epoch, pair_cache={})
        pool = multiprocessing.get_context("fork").Pool(args.workers) if args.workers else None
        batches = (pool.imap(_make_batch, range(first, steps_per_epoch), chunksize=8) if pool
                   else map(_make_batch, range(first, steps_per_epoch)))
        for bi, batch in zip(range(first, steps_per_epoch), batches):
            if not batch:
                continue
            ids, mask, cy, fy, sy = collate(batch, tokenizer.pad_token_id)
            ids, mask, cy, fy, sy = ids.to(dev), mask.to(dev), cy.to(dev), fy.to(dev), sy.to(dev)
            with torch.autocast(device_type=dev.type, dtype=torch.bfloat16, enabled=dev.type in ("xpu", "cuda")):
                out = model(ids, mask)
            cl, fl = out[0], out[1]
            loss = loss_fn(cl.float().reshape(-1, cl.shape[-1]), cy.reshape(-1)) + \
                loss_fn(fl.float().reshape(-1, fl.shape[-1]), fy.reshape(-1))
            if args.spell:
                sl = out[2]
                loss = loss + args.spell_loss_weight * loss_fn(sl.float().reshape(-1, sl.shape[-1]), sy.reshape(-1))
            # a large model in bf16 once diverged to nan and kept training (and checkpointing) nan weights
            # for hours: skip a non-finite step, give up after a run of them so the queue retries from the
            # last good checkpoint
            if not torch.isfinite(loss):
                optim.zero_grad()
                bad_steps += 1
                if bad_steps >= MAX_BAD_STEPS:
                    raise RuntimeError("loss is not finite for %d steps in a row (step %d)" % (bad_steps, step))
                continue
            loss.backward()
            norm = nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if not torch.isfinite(norm):
                optim.zero_grad()
                bad_steps += 1
                if bad_steps >= MAX_BAD_STEPS:
                    raise RuntimeError("gradient is not finite for %d steps in a row (step %d)" % (bad_steps, step))
                continue
            bad_steps = 0
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            if step % 200 == 0:
                print("epoch %d step %d/%d loss %.4f  %.1f min" % (epoch, step, total, loss.item(), (time.time() - t0) / 60), flush=True)
            if args.max_steps and step >= args.max_steps:
                break
            if step % args.save_every == 0:
                if not all(torch.isfinite(p).all() for p in model.parameters()):
                    raise RuntimeError("weights are not finite at step %d: checkpoint not saved" % step)
                tmp = ckpt_path + ".tmp"
                torch.save({"model": model.state_dict(), "optim": optim.state_dict(), "sched": sched.state_dict(),
                            "step": step, "epoch": epoch, "batch": bi + 1}, tmp)
                os.replace(tmp, ckpt_path)  # atomic: a kill during saving never corrupts the checkpoint
        if pool:
            pool.terminate()
        report = evaluate(model, tokenizer, val, form_labels, dev)
        print("epoch %d validation: %s" % (epoch, json.dumps(report)), flush=True)
        if args.max_steps and step >= args.max_steps:
            # smoke run: only the weights, no epoch copy and no multi-GB optimiser checkpoint
            torch.save(model.state_dict(), os.path.join(args.out, "model.pt"))
            break
        torch.save(model.state_dict(), os.path.join(args.out, "model-epoch%d.pt" % epoch))
        torch.save(model.state_dict(), os.path.join(args.out, "model.pt"))
        torch.save({"model": model.state_dict(), "optim": optim.state_dict(), "sched": sched.state_dict(),
                    "step": step, "epoch": epoch + 1, "batch": 0}, ckpt_path)


def decode(logits, form_labels, word_pos):
    """Per-word probabilities from the head outputs (logits are (comma, form) or (comma, form, spell))."""
    cp, fp = logits[0][0].softmax(-1), logits[1][0].softmax(-1)
    sp = logits[2][0].softmax(-1) if len(logits) > 2 else None
    result = []
    for w, t in sorted(word_pos.items()):
        c = {COMMA_LABELS[k]: float(cp[t, k]) for k in range(len(COMMA_LABELS))}
        k = int(fp[t].argmax())
        item = {"comma": c, "form": form_labels[k], "form_p": float(fp[t, k]), "form_keep_p": float(fp[t, 0])}
        if sp is not None:
            item["spell"] = {SPELL_LABELS[k]: float(sp[t, k]) for k in range(len(SPELL_LABELS))}
        result.append(item)
    return result


class EditTagger:
    """Inference wrapper: returns per-word probabilities for comma, form and (if trained) spelling actions."""

    def __init__(self, run_dir, epoch=None, dev=None):
        self.dev = torch.device(dev) if dev else torch.device("cpu")
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
        self.model = TaggerModel(meta["base"], len(self.form_labels), len(meta.get("spell_labels", ())))
        name = "model.pt" if epoch is None else "model-epoch%d.pt" % epoch
        self.model.load_state_dict(torch.load(os.path.join(run_dir, name), map_location="cpu", weights_only=True))
        self.model.to(self.dev).eval()

    def predict(self, text):
        ids, _, _, word_pos, _ = encode(self.tokenizer, text)
        if self.session is not None:
            import numpy
            outs = self.session.run(None, {"input_ids": numpy.array([ids], dtype=numpy.int64),
                                           "attention_mask": numpy.ones((1, len(ids)), dtype=numpy.int64)})
            logits = [torch.from_numpy(o) for o in outs]
        else:
            with torch.inference_mode():
                logits = self.model(torch.tensor([ids], device=self.dev),
                                    torch.ones((1, len(ids)), dtype=torch.long, device=self.dev))
                logits = [x.cpu() for x in logits]
        return decode(logits, self.form_labels, word_pos)


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
    t.add_argument("--realistic", action="store_true",
                   help="realistic error generator (corrupt_realistic): every place gets an error with its measured "
                        "real rate times --error-rate; --p-clean/--p-single/--p-form/--uniform-placement are ignored, "
                        "--max-edits caps the errors per sentence")
    t.add_argument("--error-rate", type=float, default=10.0,
                   help="with --realistic: error density as a multiple of real documents (1 = about 0.13 errors per "
                        "sentence; 10 is about the density of the old commas recipe, 3 of the old forms recipe)")
    t.add_argument("--form-scale", type=float, default=1.0,
                   help="with --realistic: extra weight of word-form errors against commas (real mix: 40%% forms)")
    t.add_argument("--spell", action="store_true",
                   help="add the spelling head (JOIN/HYPHEN/SPLIT/LOWER/UPPER); a warm start keeps the other heads")
    t.add_argument("--p-spell", type=float, default=0.12,
                   help="with --spell: share of sentences that also get one spelling error (rarely two)")
    t.add_argument("--spell-loss-weight", type=float, default=1.0)
    t.add_argument("--pairs", default=None,
                   help="real error pairs: comma separated jsonl files made by pair_labels.py (or raw src/gold pairs); "
                        "their sentences are also taken out of the synthetic corpus")
    t.add_argument("--pairs-share", type=float, default=0.3,
                   help="with --pairs: share of every batch taken from the real pairs (cycled, reshuffled each pass)")
    t.add_argument("--exclude-lines", default=None,
                   help="file with 1-based line numbers of --corpus that must not be used (e.g. used_lines.txt)")
    t.add_argument("--epoch-fraction", type=float, default=1.0,
                   help="train on this share of the corpus per epoch (0.3 = a short fine-tune; the schedule follows)")
    t.add_argument("--workers", type=int, default=0, help="processes building batches (0 = in the training process)")
    t.add_argument("--seed", type=int, default=0,
                   help="0 = the recipes as before; another value gives another data order, other errors, other head init")
    t.add_argument("--device", default=None, help="force a device (cpu); default: xpu if present, else cpu")
    t.add_argument("--threads", type=int, default=0, help="torch CPU threads (0 = torch default)")
    t.add_argument("--max-steps", type=int, default=0, help="stop after this many steps (smoke runs)")
    a = ap.parse_args()
    if a.cmd == "train":
        train(a)
