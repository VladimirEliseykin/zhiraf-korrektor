"""Evaluate a SAGE model dir (HF) the way the sage-large report did: run it over dev / test / official / dev2,
score its edits per type (right / false / wrong place / missed) and check the agreement with our taggers.

    python sage_eval.py MODEL_DIR --out OUT_DIR [--sets dev test official dev2] [--limit N] [--batch 16]
        [--root /home/general/vm/win7] [--no-gen] [--no-agreement]

Outputs: OUT_DIR/out-<set>.jsonl (model outputs, resumable), OUT_DIR/score.txt, OUT_DIR/score.json.
The data (spike gold, dev2, tagger prediction caches in runs/) lives in --root, the checkout with the git-ignored
files; code is imported from there too (the same files as in git). Run on CPU under the resource cap:
    systemd-run --user --wait --collect -P -p MemoryMax=4G -p MemorySwapMax=0 -p CPUQuota=400% \\
        --setenv=OMP_NUM_THREADS=4 nice -n 19 python sage_eval.py ...
Scoring = bench.edits of src vs output against gold; type = coverage.kind; "right" = the exact gold edit,
"place" = touches a gold edit but differs (counted as false in precision), disputed fragments are ignored.
Tagger agreement: the comma and form members shipped in the engine (min / max over members of the probability
of the same edit), as in sage-large-report.md section 3.
"""
import argparse
import collections
import json
import os
import re
import sys
import time

TYPE = {"запятая": "comma", "окончание": "ending", "слитно/дефис": "join/hyphen", "орфография/слово": "spelling",
        "регистр": "case", "другая пунктуация": "other punct", "несколько слов": "multiword"}
TYPES = ["comma", "ending", "join/hyphen", "spelling", "case", "other punct", "multiword"]
COMMA_RUNS = ["gpu-ft8-gpu-ft5-r6-commas", "gpu-ft8-gpu-ft-r3-commas", "gpu-ft8-large-commas-e0"]
FORM_RUNS = ["gpu-ft-large-commas", "gpu-ft-r6-commas", "gpu-ft-r3-commas"]
WORDTOK = re.compile(r"\w")


def postprocess(src, out):
    """As engine/spellcheck/sage.py: the final sentence punctuation of src is kept, N before a digit -> №."""
    out = out.strip()
    if src and src[-1] in ".:;!?" and (not out or out[-1] not in ".:;!?"):
        out += src[-1]
    if "№" in src:
        out = re.sub(r"\bN(?=\s?\d)", "№", out)
    return out


class Env:
    def __init__(self, root):
        self.root = root
        for sub in ("train", "spike", "engine"):
            sys.path.insert(0, os.path.join(root, sub))
        import bench
        self.bench = bench

    def items(self, name):
        if name == "dev2":
            rows = [json.loads(l) for l in open(os.path.join(self.root, "data-public/converted/dev2.jsonl"), encoding="utf-8")]
            seen, items = set(), []
            for r in rows:
                if r["src"] not in seen:
                    seen.add(r["src"])
                    items.append({"src": r["src"], "gold": r["gold"], "disputed": [], "doc": r.get("doc", "")})
            return items
        return self.bench.load_sets()[name]


def generate(model_dir, env, names, out_dir, limit, batch, threads):
    import resource
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from spellcheck.guards import prepare
    torch.set_num_threads(threads)
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_dir).eval()
    for name in names:
        srcs = list(dict.fromkeys(i["src"] for i in env.items(name)))
        path = os.path.join(out_dir, "out-%s.jsonl" % name)
        done = {}
        if os.path.exists(path):
            done = {json.loads(l)["src"] for l in open(path, encoding="utf-8")}
        todo = [s for s in srcs if s not in done]
        if limit:
            todo = todo[:limit]
        bodies = {s: prepare(s)[1] for s in todo}
        todo.sort(key=lambda s: len(bodies[s]))
        print("%s: todo %d of %d" % (name, len(todo), len(srcs)), flush=True)
        t0 = time.time()
        with open(path, "a", encoding="utf-8") as f:
            for b in range(0, len(todo), batch):
                chunk = todo[b:b + batch]
                enc = tok([bodies[s] for s in chunk], padding="longest", truncation=False, return_tensors="pt")
                t1 = time.time()
                with torch.inference_mode():
                    out = model.generate(**enc, max_length=int(enc["input_ids"].size(1) * 1.5) + 4)
                dt = time.time() - t1
                for s, o in zip(chunk, tok.batch_decode(out, skip_special_tokens=True, clean_up_tokenization_spaces=False)):
                    f.write(json.dumps({"src": s, "out": o, "sec": dt / len(chunk)}, ensure_ascii=False) + "\n")
                f.flush()
                if (b // batch) % 20 == 0:
                    print("  %d/%d %.0fs rss %.1fG" % (b + len(chunk), len(todo), time.time() - t0,
                                                       resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6), flush=True)


def load_cache(root, run):
    cache = {}
    for f in ("bench-preds.json", "bench-preds2.json"):
        p = os.path.join(root, "runs", run, f)
        if os.path.exists(p):
            cache.update(json.load(open(p, encoding="utf-8")))
    return cache


def word_ordinal(tokens, i):
    return sum(1 for t in tokens[:i] if WORDTOK.match(t))


def score(env, names, out_dir, agreement, log):
    import coverage
    import tagger_eval as te
    bench = env.bench
    cc = [load_cache(env.root, r) for r in COMMA_RUNS] if agreement else []
    fc = [load_cache(env.root, r) for r in FORM_RUNS] if agreement else []
    eng_path = os.path.join(os.path.dirname(env.root.rstrip("/")), "win7-profiles/work/findings-R8b.json")
    eng = json.load(open(eng_path, encoding="utf-8")) if agreement and os.path.exists(eng_path) else {}
    if eng:
        from spellcheck import checker
    res = {}
    for name in names:
        items = env.items(name)
        outs = {json.loads(l)["src"]: json.loads(l) for l in open(os.path.join(out_dir, "out-%s.jsonl" % name), encoding="utf-8")}
        items = [i for i in items if i["src"] in outs]
        R = {"n": len(items), "right": collections.Counter(), "false": collections.Counter(), "place": collections.Counter(),
             "ignored": collections.Counter(), "missed": collections.Counter(), "gold": collections.Counter(), "probs": [],
             "changed": 0}
        for item in items:
            src = item["src"]
            marker, body = te.prepare(src)
            out = marker + postprocess(body, outs[src]["out"])
            R["changed"] += out != src
            gold = list(bench.edits(src, item["gold"]))
            gk = {g[:3] for g in gold}
            sysed = bench.edits(src, out)
            ranges = bench.disputed_ranges(src, item["disputed"])
            toks = bench.SCORE_TOKEN.findall(bench.normalize(src))
            mtoks = bench.SCORE_TOKEN.findall(bench.normalize(marker)) if marker.strip() else []
            produced = {e[:3] for e in sysed}
            for g in gold:
                R["gold"][TYPE[coverage.kind(g)]] += 1
                if g[:3] not in produced:
                    R["missed"][TYPE[coverage.kind(g)]] += 1
            sure, chk = [], []
            for f in eng.get(src, []):
                g2 = dict(f, fix=f["fix"] if f.get("fix") is not None else "█")
                es = list(bench.edits(src, checker.apply(src, [g2], levels=(f["level"],))))
                (sure if f["level"] == "error" else chk).extend(es)
            for e in sysed:
                t = TYPE[coverage.kind(e)]
                if e[:3] in gk:
                    v = "right"
                elif any(e[0] < r[1] and e[1] > r[0] or e[0] == r[0] for r in ranges):
                    v = "ignored"
                elif any(coverage.touches(e, g) for g in gold):
                    v = "place"
                else:
                    v = "false"
                R[v][t] += 1
                if t not in ("comma", "ending") or not agreement:
                    continue
                k = word_ordinal(toks, e[0]) - len([x for x in mtoks if WORDTOK.match(x)])
                probs = []
                if t == "comma":
                    ins = e[2] == (",",) and e[1] == e[0]
                    wi = k - 1
                    for c in cc:
                        ent = c.get(src)
                        if not ent or not (0 <= wi < len(ent[3])) or ent[1] != body:
                            probs = None
                            break
                        probs.append(ent[3][wi]["comma"]["ADD" if ins else "DEL"])
                else:
                    wi = k
                    word = e[3][0] if len(e[3]) == 1 else None
                    for c in fc:
                        ent = c.get(src)
                        if not ent or not (0 <= wi < len(ent[3])) or ent[1] != body or word is None or len(e[2]) != 1:
                            probs = None
                            break
                        p = ent[3][wi]
                        lab = p["form"]
                        new = te.inflect(word, lab) if lab != "KEEP" else None
                        probs.append(p["form_p"] if new and bench.normalize(new) == e[2][0] else 0.0)
                R["probs"].append({"set": name, "t": t, "v": v, "p": probs, "has_eng": src in eng,
                                   "engine_sure": any(x[:3] == e[:3] for x in sure),
                                   "engine_touch": any(coverage.touches(e, x) for x in sure + chk)})
        res[name] = R
        log("== %s: %d sentences, %d changed" % (name, R["n"], R["changed"]))
        log("%-12s %6s %6s %6s %6s %6s %6s %7s %7s" % ("type", "gold", "right", "false", "place", "disp", "missed", "recall", "prec"))
        for t in TYPES:
            r, f, p = R["right"][t], R["false"][t], R["place"][t]
            log("%-12s %6d %6d %6d %6d %6d %6d %6.0f%% %6.0f%%" % (
                t, R["gold"][t], r, f, p, R["ignored"][t], R["missed"][t],
                100.0 * r / max(R["gold"][t], 1), 100.0 * r / max(r + f + p, 1)))
        log("total right %d false %d place %d" % (sum(R["right"].values()), sum(R["false"].values()), sum(R["place"].values())))
        if name == "official":
            log("official clean: false edits %d = %.3f per sentence, sentences changed %.1f%%" % (
                sum(R["false"].values()) + sum(R["place"].values()), (sum(R["false"].values()) + sum(R["place"].values())) / max(R["n"], 1),
                100.0 * R["changed"] / max(R["n"], 1)))
    if "dev" in res and "test" in res:
        n = res["dev"]["n"] + res["test"]["n"]
        fa = sum(res[k]["false"][t] + res[k]["place"][t] for k in ("dev", "test") for t in TYPES)
        log("\ndev+test: false edits (false+place) per 100 sentences: %.1f   [engine today: 0.6 error / 1.9 check]" % (100.0 * fa / n))
        for t in ("comma", "ending"):
            r = sum(res[k]["right"][t] for k in ("dev", "test"))
            f = sum(res[k]["false"][t] + res[k]["place"][t] for k in ("dev", "test"))
            g = sum(res[k]["gold"][t] for k in ("dev", "test"))
            log("dev+test %s: precision %d/%d = %.0f%%, recall %d/%d = %.0f%%" % (t, r, r + f, 100.0 * r / max(r + f, 1), r, g, 100.0 * r / max(g, 1)))
    if agreement:
        log("\nAGREEMENT (right/(right+false+place) of SAGE edits by tagger members' probability for the same edit)")
        for n in names:
            for t in ("comma", "ending"):
                sub = [r for r in res[n]["probs"] if r["t"] == t]
                ok = [r for r in sub if r["p"] is not None]
                line = "%s %s: edits %d mapped %d |" % (n, t, len(sub), len(ok))
                for th in (0.0, 0.3, 0.5):
                    for agg, f in (("min", min), ("max", max)):
                        if th == 0 and agg == "max":
                            continue
                        hit = [r for r in ok if f(r["p"]) >= th] if th else ok
                        rt = sum(r["v"] == "right" for r in hit)
                        fl = sum(r["v"] in ("false", "place") for r in hit)
                        line += (" %s>=%.1f: %d/%d(P=%.2f)" % (agg, th, rt, rt + fl, rt / max(1, rt + fl))) if th else \
                            (" all: %d/%d(P=%.2f)" % (rt, rt + fl, rt / max(1, rt + fl)))
                log(line)
        if eng:
            log("\nPROMOTION: edit not emitted at engine error level, tagger min-prob band, dev+test right/false+place | official false")
            for t in ("comma", "ending"):
                for lo, hi in ((0.0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 0.9), (0.9, 1.01)):
                    def pick(sets_):
                        return [r for n in sets_ if n in res for r in res[n]["probs"] if r["t"] == t and r["p"] is not None
                                and r["has_eng"] and not r["engine_sure"] and lo <= min(r["p"]) < hi]
                    a, o = pick(["dev", "test"]), pick(["official"])
                    log("%s p[%.1f,%.1f): dev+test right %d false %d | official false %d" % (
                        t, lo, hi, sum(r["v"] == "right" for r in a), sum(r["v"] in ("false", "place") for r in a), len(o)))
    json.dump({n: {k: (dict(v) if isinstance(v, collections.Counter) else v) for k, v in R.items()} for n, R in res.items()},
              open(os.path.join(out_dir, "score.json"), "w"), ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sets", nargs="+", default=["dev", "test", "official", "dev2"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--threads", type=int, default=int(os.environ.get("OMP_NUM_THREADS", 4)))
    ap.add_argument("--root", default="/home/general/vm/win7")
    ap.add_argument("--no-gen", action="store_true")
    ap.add_argument("--no-agreement", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    env = Env(a.root)
    if not a.no_gen:
        generate(a.model, env, a.sets, a.out, a.limit, a.batch, a.threads)
    lines = []

    def log(s):
        print(s, flush=True)
        lines.append(s)
    score(env, a.sets, a.out, not a.no_agreement, log)
    open(os.path.join(a.out, "score.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
