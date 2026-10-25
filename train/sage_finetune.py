"""Fine-tune ai-forever/sage-fredt5-distilled-95m (T5 seq2seq) on real error pairs: commas, word forms, spelling.

    python sage_finetune.py --data DIR --out RUN_DIR [--base ai-forever/sage-fredt5-distilled-95m]
        [--lr 5e-5] [--epochs 3] [--clean-share 0.6] [--batch 32] [--max-len 192] [--seed 1]

DIR holds sage_err.jsonl and sage_clean.jsonl (built by sage_data.py: rows {"src","gold","pool"}).
Input = src exactly as at inference: the tokenizer prepends <LM> (id 50357) and adds no </s>.
Target = gold tokens WITHOUT <LM> + </s> (the model generates [0, tokens, 2]; the engine stops at 2).
Every epoch uses all erroneous pairs and enough clean ones (src == gold) for the --clean-share: hard
negatives first, the rest sampled from the other clean pools anew each epoch.
A random 5% of both files is held out (never trained on); the best checkpoint by greedy exact match on it
(mean of the exact-match rate on erroneous and on clean sentences) is written as a plain HF model dir to RUN_DIR.
"""
import argparse
import json
import math
import os
import random
import time

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def read(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def encode(tok, rows, max_len):
    srcs = tok([r["src"] for r in rows], truncation=False)["input_ids"]
    golds = tok([r["gold"] for r in rows], add_special_tokens=False, truncation=False)["input_ids"]
    out, dropped = [], 0
    for r, s, g in zip(rows, srcs, golds):
        g = g + [tok.eos_token_id]
        if len(s) > max_len or len(g) > max_len:
            dropped += 1
            continue
        out.append({"src": r["src"], "gold": r["gold"], "pool": r.get("pool", ""), "x": s, "y": g})
    return out, dropped


def batches(items, batch, rng):
    """Shuffled batches; sentences of similar length together (chunks of 50 batches sorted by length)."""
    items = items[:]
    rng.shuffle(items)
    chunk = batch * 50
    out = []
    for i in range(0, len(items), chunk):
        part = sorted(items[i:i + chunk], key=lambda e: len(e["x"]))
        out += [part[j:j + batch] for j in range(0, len(part), batch)]
    rng.shuffle(out)
    return out


def collate(batch, pad, device):
    lx, ly = max(len(e["x"]) for e in batch), max(len(e["y"]) for e in batch)
    x = torch.tensor([e["x"] + [pad] * (lx - len(e["x"])) for e in batch])
    y = torch.tensor([e["y"] + [-100] * (ly - len(e["y"])) for e in batch])
    return x.to(device), (x != pad).long().to(device), y.to(device)


@torch.inference_mode()
def generate(model, tok, texts, device, bf16, batch=64):
    """Greedy, as at inference: max_length = 1.5 * input length."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    result = [None] * len(texts)
    for b in range(0, len(order), batch):
        idx = order[b:b + batch]
        enc = tok([texts[i] for i in idx], padding="longest", return_tensors="pt").to(device)
        with torch.autocast(device, dtype=torch.bfloat16, enabled=bf16):
            out = model.generate(**enc, max_length=int(enc["input_ids"].size(1) * 1.5) + 4, num_beams=1, do_sample=False)
        for i, o in zip(idx, tok.batch_decode(out, skip_special_tokens=True)):
            result[i] = o.strip()
    return result


def evaluate(model, tok, val, device, bf16):
    model.eval()
    loss_sum = n_tok = 0
    with torch.inference_mode():
        for b in range(0, len(val), 64):
            batch = val[b:b + 64]
            x, m, y = collate(batch, tok.pad_token_id, device)
            with torch.autocast(device, dtype=torch.bfloat16, enabled=bf16):
                logits = model(input_ids=x, attention_mask=m, labels=y).logits
            loss = torch.nn.functional.cross_entropy(logits.float().transpose(1, 2), y, ignore_index=-100, reduction="sum")
            loss_sum += loss.item()
            n_tok += (y != -100).sum().item()
    out = generate(model, tok, [e["src"] for e in val], device, bf16)
    err = [o == e["gold"] for o, e in zip(out, val) if e["src"] != e["gold"]]
    clean = [o == e["gold"] for o, e in zip(out, val) if e["src"] == e["gold"]]
    res = {"val_loss": loss_sum / max(n_tok, 1), "exact_err": sum(err) / max(len(err), 1),
           "exact_clean": sum(clean) / max(len(clean), 1), "n_err": len(err), "n_clean": len(clean)}
    res["score"] = 0.5 * (res["exact_err"] + res["exact_clean"])
    model.train()
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="ai-forever/sage-fredt5-distilled-95m")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--clean-share", type=float, default=0.6)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--max-len", type=int, default=192)
    ap.add_argument("--val-frac", type=float, default=0.05)
    ap.add_argument("--evals-per-epoch", type=int, default=2)
    ap.add_argument("--warmup", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--synth-err", help="jsonl of synthetic error pairs (sage_synth.py): all of them every epoch")
    ap.add_argument("--synth-clean", help="jsonl of synthetic clean pairs: sampled to reach --clean-share")
    ap.add_argument("--real-repeat", type=int, default=1, help="the real error pairs and real clean ones count this many times per epoch")
    ap.add_argument("--split-seed", type=int, help="seed of the held-out split (default --seed); keep it equal between runs to share the held-out set")
    ap.add_argument("--limit", type=int, default=0, help="smoke test: use this many error pairs (and the clean share of them)")
    ap.add_argument("--max-steps", type=int, default=0, help="smoke test: stop after this many steps")
    a = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    bf16 = device == "cuda"
    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    split_rng = random.Random(a.split_seed if a.split_seed is not None else a.seed)
    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.base)
    assert tok("а")["input_ids"][0] == 50357, "the tokenizer must prepend <LM>"
    err, d1 = encode(tok, read(os.path.join(a.data, "sage_err.jsonl")), a.max_len)
    clean, d2 = encode(tok, read(os.path.join(a.data, "sage_clean.jsonl")), a.max_len)
    split_rng.shuffle(err)
    split_rng.shuffle(clean)
    synth_err, synth_clean = [], []
    if a.synth_err:
        synth_err, d3 = encode(tok, read(a.synth_err), a.max_len)
    if a.synth_clean:
        synth_clean, d4 = encode(tok, read(a.synth_clean), a.max_len)
    if a.limit:
        err, clean = err[:a.limit], clean[:int(a.limit * 2)]
    ve, vc = int(len(err) * a.val_frac), int(len(clean) * a.val_frac)
    val, err_tr, clean_tr = err[:ve] + clean[:vc], err[ve:], clean[vc:]
    hard = [e for e in clean_tr if e["pool"] == "hard"] * a.real_repeat
    other = [e for e in clean_tr if e["pool"] != "hard"] * a.real_repeat + synth_clean
    errs = err_tr * a.real_repeat + synth_err
    need = round(len(errs) * a.clean_share / (1 - a.clean_share))
    print("err train %d (real %d x%d + synthetic %d) clean pool %d (hard %d, other real %d, synthetic %d) val %d (err %d) | "
          "too long dropped: err %d clean %d | clean per epoch %d (share %.2f) | device %s bf16 %s" % (
              len(errs), len(err_tr), a.real_repeat, len(synth_err), len(clean_tr) + len(synth_clean), len(hard), len(other) - len(synth_clean),
              len(synth_clean), len(val), ve, d1, d2, need, a.clean_share, device, bf16), flush=True)

    def epoch_items():
        picked = rng.sample(hard, min(len(hard), need))
        rest = need - len(picked)
        picked += rng.sample(other, min(rest, len(other)))
        return errs + picked

    steps_per_epoch = math.ceil((len(errs) + need) / a.batch)
    total = steps_per_epoch * a.epochs
    model = AutoModelForSeq2SeqLM.from_pretrained(a.base).to(device)
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.01)
    warm = max(1, int(total * a.warmup))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min((s + 1) / warm, max(0.0, (total - s) / max(total - warm, 1))))
    eval_every = max(1, steps_per_epoch // a.evals_per_epoch)
    log = open(os.path.join(a.out, "log.jsonl"), "a", encoding="utf-8")
    best, step, t0 = None, 0, time.time()
    base = evaluate(model, tok, val, device, bf16)
    print("base model on held-out:", base, flush=True)
    log.write(json.dumps({"step": 0, **base}) + "\n")
    for epoch in range(a.epochs):
        run_loss, run_n = 0.0, 0
        for batch in batches(epoch_items(), a.batch, rng):
            x, m, y = collate(batch, tok.pad_token_id, device)
            with torch.autocast(device, dtype=torch.bfloat16, enabled=bf16):
                loss = model(input_ids=x, attention_mask=m, labels=y).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            run_loss += loss.item()
            run_n += 1
            if step % 50 == 0:
                print("epoch %d step %d/%d loss %.4f lr %.2e %.0fs" % (epoch + 1, step, total, run_loss / run_n,
                                                                          sched.get_last_lr()[0], time.time() - t0), flush=True)
                run_loss, run_n = 0.0, 0
            last = step == total or (a.max_steps and step >= a.max_steps)
            if step % eval_every == 0 or last:
                res = evaluate(model, tok, val, device, bf16)
                res.update(step=step, epoch=round(step / steps_per_epoch, 2), seconds=round(time.time() - t0))
                print("EVAL", json.dumps(res), flush=True)
                log.write(json.dumps(res) + "\n")
                log.flush()
                if best is None or res["score"] > best["score"]:
                    best = res
                    model.save_pretrained(a.out, safe_serialization=True)
                    tok.save_pretrained(a.out)
                    json.dump({"best": best, "base_model": a.base, "args": vars(a)},
                              open(os.path.join(a.out, "train_summary.json"), "w"), indent=1)
            if last:
                break
        if a.max_steps and step >= a.max_steps:
            break
    print("done: best %s in %.0fs" % (best, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
