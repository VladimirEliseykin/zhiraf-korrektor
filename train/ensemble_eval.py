"""N-model ensembles of edit taggers, scored from the cached bench predictions (no model is run).

Usage: python ensemble_eval.py <run_dir>... [--max-models 3] [--out result.json]

For every subset of the given runs (1..max-models) and two combiners it scores
  commas: "min" (agreement: an edit needs every model above the threshold) or "mean" of the probabilities,
          ADD and DEL separately;
  forms:  the form label must be the same argmax in every model; its probability is the min / the mean
          of the models' form_p (the caches keep only the argmax label and its probability).
Edits are scored exactly like threshold_sweep (bench.score, same guards as the engine). One site (a comma
position, a word and its new form) is classified once by applying that single edit, so any threshold
grid is then cheap. Selection uses only dev and clean official text; test is printed on demand.
Model-selection rule per head: most right finds on dev at the "error" threshold, subject to dev false finds
and false alarms on clean official text not above the single reference model at 0.9; ties: fewer models,
fewer false finds.
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tagger_eval as te  # noqa: E402

bench = te.bench
ADD = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
DEL = (0.7, 0.8, 0.9, 0.95, 1.1)
FORM = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
LOW = 0.3  # the "check" band starts here; also the lowest candidate probability


class Data:
    """Flattened words of dev + test + official, per-model probability arrays, lazily classified sites."""

    def __init__(self, sets, runs):
        self.sets = sets
        self.items = sets["dev"] + sets["test"] + sets["official"]
        self.bounds = {}
        a = 0
        for name in ("dev", "test", "official"):
            self.bounds[name] = (a, a + len(sets[name]))
            a += len(sets[name])
        self.runs = []
        self.model = {}
        self.label_id = {"KEEP": 0}
        self.layout = None
        for run in runs:
            self._load(run)
        self.memo = {}

    def _layout(self, cache):
        sent, kind, pre = [], [], []
        self.markers, self.bodies, self.word_pos = [], [], []
        for s, item in enumerate(self.items):
            marker, body = cache[item["src"]][:2]
            self.markers.append(marker)
            self.bodies.append(body)
            ms = te.words_of(body)
            biblio = bool(te.BIBLIOGRAPHY.search(body))
            quotes = te.quoted_spans(body)
            for i, m in enumerate(ms):
                word = m.group(0)
                self.word_pos.append((s, i, m.start(), m.end()))
                sent.append(s)
                in_q = any(x < m.start() < y for x, y in quotes)
                k = 0
                if not biblio and not in_q and not (te.protected(word) and not word.isalpha()):
                    if body[m.end():m.end() + 1] == ",":
                        k = 2
                    elif body[m.end():m.end() + 1] == " " and i < len(ms) - 1:
                        k = 1
                capital_mid = i > 0 and word[:1].isupper()
                form_ok = not biblio and not te.protected(word) and not in_q and not capital_mid
                kind.append(k)
                pre.append(form_ok)
        self.sent = np.array(sent, dtype=np.int32)
        self.kind = np.array(kind, dtype=np.int8)
        self.form_ok = np.array(pre, dtype=bool)
        self.words = [te.words_of(b) for b in self.bodies]
        self.offset = np.cumsum([0] + [len(w) for w in self.words])

    def _load(self, run):
        name = os.path.basename(os.path.normpath(run))
        cache = json.load(open(os.path.join(run, "bench-preds.json"), encoding="utf-8"))
        missing = sum(1 for i in self.items if i["src"] not in cache)
        if missing:
            print("skip %s: cache lacks %d of %d sentences" % (name, missing, len(self.items)), flush=True)
            return
        if self.layout is None:
            self._layout(cache)
            self.layout = True
        n = len(self.sent)
        add = np.zeros(n, dtype=np.float32)
        dele = np.zeros(n, dtype=np.float32)
        fp = np.zeros(n, dtype=np.float32)
        lab = np.zeros(n, dtype=np.int16)
        for s, item in enumerate(self.items):
            marker, body, _, preds = cache[item["src"]]
            assert body == self.bodies[s], name
            o = self.offset[s]
            for i, p in enumerate(preds):
                add[o + i] = p["comma"]["ADD"]
                dele[o + i] = p["comma"]["DEL"]
                fp[o + i] = p["form_p"]
                lab[o + i] = self.label_id.setdefault(p["form"], len(self.label_id))
        self.model[name] = {"add": add, "del": dele, "form_p": fp, "lab": lab}
        self.runs.append(name)
        del cache
        print("loaded %s" % name, flush=True)

    # ----- site classification: apply one edit, score it with bench.score -----
    def site_class(self, w, what):
        """(tp, fp) of one edit: what = 'ADD', 'DEL' or a form label string."""
        key = (w, what)
        if key in self.memo:
            return self.memo[key]
        s, i, a, b = self.word_pos[w]
        body, item = self.bodies[s], self.items[s]
        if what == "ADD":
            new, grp = body[:b] + "," + body[b:], "comma"
        elif what == "DEL":
            new, grp = body[:b] + body[b + 1:], "comma"
        else:
            word = body[a:b]
            repl = te.inflect(word, what) or word
            if repl == word or te.breaks_grammar(body, a, b, repl):
                self.memo[key] = (0, 0)
                return self.memo[key]
            new, grp = body[:a] + repl + body[b:], "other"
        c = bench.score([item], [self.markers[s] + new])
        self.memo[key] = (c[grp + "_tp"], c[grp + "_fp"])
        return self.memo[key]

    def per_sentence(self, idx, vals):
        """Sum of per-site (tp, fp) over the sites idx, per sentence."""
        S = len(self.items)
        tp = np.bincount(self.sent[idx], weights=vals[:, 0], minlength=S) if len(idx) else np.zeros(S)
        fp = np.bincount(self.sent[idx], weights=vals[:, 1], minlength=S) if len(idx) else np.zeros(S)
        return tp, fp

    # ----- combiners -----
    @staticmethod
    def combine(arrs, how):
        return np.min(arrs, axis=0) if how == "min" else np.mean(arrs, axis=0)

    def comma_vectors(self, names, how):
        """{(t_add, t_del): (tp per sentence, fp per sentence)} for the comma head."""
        add = self.combine([self.model[n]["add"] for n in names], how)
        dele = self.combine([self.model[n]["del"] for n in names], how)
        parts = {}
        for kind, label, p, grid in ((1, "ADD", add, ADD), (2, "DEL", dele, DEL)):
            idx = np.nonzero((self.kind == kind) & (p >= LOW))[0]
            vals = np.array([self.site_class(int(w), label) for w in idx], dtype=float).reshape(-1, 2)
            for t in grid:
                keep = p[idx] >= t
                parts[(label, t)] = self.per_sentence(idx[keep], vals[keep])
            parts[(label, LOW)] = self.per_sentence(idx, vals)
        return parts

    def form_vectors(self, names, how):
        """{t_form: (tp, fp) per sentence}: same argmax label in every model, p = min / mean of form_p."""
        labs = [self.model[n]["lab"] for n in names]
        agree = np.all([l == labs[0] for l in labs], axis=0) & (labs[0] != 0) & self.form_ok
        p = self.combine([self.model[n]["form_p"] for n in names], how)
        idx = np.nonzero(agree & (p >= LOW))[0]
        inv = {v: k for k, v in self.label_id.items()}
        vals = np.array([self.site_class(int(w), inv[int(labs[0][w])]) for w in idx], dtype=float).reshape(-1, 2)
        out = {}
        for t in FORM + (LOW,):
            keep = p[idx] >= t
            out[t] = self.per_sentence(idx[keep], vals[keep])
        return out

    def total(self, vec, split):
        a, b = self.bounds[split]
        return int(vec[0][a:b].sum()), int(vec[1][a:b].sum())


def add_vec(x, y):
    return x[0] + y[0], x[1] + y[1]


def build(data, head, max_models):
    """{(names, how): {threshold: (tp per sentence, fp per sentence)}} for every subset of the loaded runs."""
    out = {}
    for k in range(1, max_models + 1):
        for names in itertools.combinations(data.runs, k):
            for how in (("min",) if k == 1 else ("min", "mean")):
                if head == "comma":
                    parts = data.comma_vectors(names, how)
                    vecs = {(ta, td): add_vec(parts[("ADD", ta)], parts[("DEL", td)]) for ta in ADD for td in DEL}
                    for ta in ADD + (LOW,):
                        vecs[("add", ta)] = parts[("ADD", ta)]
                else:
                    vecs = data.form_vectors(names, how)
                out[(names, how)] = {t: (np.rint(v[0]).astype(np.int16), np.rint(v[1]).astype(np.int16))
                                     for t, v in vecs.items()}
        print(head, "k=%d done, sites %d" % (k, len(data.memo)), flush=True)
    return out


def split_sum(data, vec, split):
    a, b = data.bounds[split]
    return int(vec[0][a:b].sum()), int(vec[1][a:b].sum())


def select(data, table, ref_key, ref_t):
    """Feasible configurations (dev false finds and official false alarms <= reference), best first."""
    ref = table[ref_key][ref_t]
    _, ref_fp = split_sum(data, ref, "dev")
    _, ref_off = split_sum(data, ref, "official")
    rows = []
    for (names, how), per_t in table.items():
        for t, v in per_t.items():
            if isinstance(t, tuple) and t[0] == "add":
                continue
            tp, fp = split_sum(data, v, "dev")
            _, off = split_sum(data, v, "official")
            rows.append((-tp, len(names), fp, off, names, how, t, fp <= ref_fp and off <= ref_off))
    return sorted(rows), (split_sum(data, ref, "dev"), ref_off)


def bootstrap_test(data, table, chosen, ref, split="test", rounds=5000, seed=1):
    """Paired bootstrap over sentences: chosen minus reference, right finds and false finds."""
    a, b = data.bounds[split]
    rng = np.random.RandomState(seed)
    ctp, cfp = (v[a:b].astype(float) for v in table[chosen[0]][chosen[1]])
    rtp, rfp = (v[a:b].astype(float) for v in table[ref[0]][ref[1]])
    n = b - a
    d_tp, d_fp = np.zeros(rounds), np.zeros(rounds)
    for r in range(rounds):
        w = np.bincount(rng.randint(0, n, n), minlength=n)
        d_tp[r] = w.dot(ctp - rtp)
        d_fp[r] = w.dot(cfp - rfp)
    lo = lambda x: tuple(np.percentile(x, (2.5, 97.5)))  # noqa: E731
    return {"d_tp": (float((ctp - rtp).sum()),) + lo(d_tp), "d_fp": (float((cfp - rfp).sum()),) + lo(d_fp),
            "p_gain": float((d_tp > 0).mean()), "p_not_worse": float((d_tp >= 0).mean())}


def selection_stability(data, table, ref, rounds=500, seed=2):
    """How often each configuration wins the dev selection on a bootstrap resample of dev."""
    a, b = data.bounds["dev"]
    off_a, off_b = data.bounds["official"]
    keys, TP, FP, OFF = [], [], [], []
    for (names, how), per_t in table.items():
        for t, v in per_t.items():
            if isinstance(t, tuple) and t[0] == "add":
                continue
            keys.append((names, how, t))
            TP.append(v[0][a:b])
            FP.append(v[1][a:b])
            OFF.append(int(v[1][off_a:off_b].sum()))
    TP, FP, OFF = np.array(TP, dtype=float), np.array(FP, dtype=float), np.array(OFF)
    rtp, rfp = table[ref[0]][ref[1]]
    ref_off = int(rfp[off_a:off_b].sum())
    n = b - a
    size = np.array([len(k[0]) for k in keys])
    rng = np.random.RandomState(seed)
    wins = {}
    ref_idx = keys.index((ref[0][0], ref[0][1], ref[1]))
    for _ in range(rounds):
        w = np.bincount(rng.randint(0, n, n), minlength=n).astype(float)
        tp, fp = TP.dot(w), FP.dot(w)
        ok = (fp <= fp[ref_idx]) & (OFF <= ref_off)
        score = np.where(ok, tp * 1000 - size * 10 - fp, -1e9)
        k = int(score.argmax())
        wins[keys[k]] = wins.get(keys[k], 0) + 1
    return sorted(wins.items(), key=lambda x: -x[1]), rounds


def main():
    args = sys.argv[1:]
    max_models = 3
    if "--max-models" in args:
        i = args.index("--max-models")
        max_models = int(args[i + 1])
        del args[i:i + 2]
    sets = bench.load_sets()
    data = Data(sets, args)
    n = {k: len(v) for k, v in sets.items()}
    print("dev %(dev)d test %(test)d official %(official)d" % n)
    for head, ref_run, ref_t in (("comma", "round3-base", (0.9, 0.9)), ("form", "round5-base", 0.9)):
        table = build(data, head, max_models)
        rows, (ref_dev, ref_off) = select(data, table, ((ref_run,), "min"), ref_t)
        print("\n=== %s: reference %s at %s: dev tp/fp %s, official fp %d ===" % (head, ref_run, ref_t, ref_dev, ref_off))
        best = [r for r in rows if r[7]]
        shown = {}
        for r in best:
            shown.setdefault((r[4], r[5]), r)
        print("best feasible per (models, combiner) on dev (right, false, official false):")
        for r in sorted(shown.values())[:25]:
            print("  dev tp %3d fp %3d off_fp %2d | %s %s %s" % (-r[0], r[2], r[3], "+".join(r[4]), r[5], r[6]))
        top = best[0]
        chosen = ((top[4], top[5]), top[6])
        ref = (((ref_run,), "min"), ref_t)
        print("\nCHOSEN on dev: %s %s %s" % ("+".join(top[4]), top[5], top[6]))
        wins, rounds = selection_stability(data, table, ref)
        print("selection stability over %d dev bootstrap resamples (top 8):" % rounds)
        for (names, how, t), c in wins[:8]:
            print("  %3d%%  %s %s %s" % (100 * c // rounds, "+".join(names), how, t))
        print("TEST (looked at once, for the chosen configuration):")
        for label, key in (("chosen", chosen), ("reference", ref)):
            v = table[key[0]][key[1]]
            print("  %-9s test tp/fp %s | official fp %s | dev tp/fp %s" % (
                label, split_sum(data, v, "test"), split_sum(data, v, "official")[1], split_sum(data, v, "dev")))
        print("  paired bootstrap on test:", bootstrap_test(data, table, chosen, ref))
        if head == "comma":
            for label, key in (("chosen", chosen), ("reference", ref)):
                names, how = key[0]
                for t in (LOW, 0.5):
                    v = table[(names, how)][("add", t)]
                    print("  check band ADD>=%.1f %-9s dev tp/fp %s test tp/fp %s official fp %d" % (
                        t, label, split_sum(data, v, "dev"), split_sum(data, v, "test"), split_sum(data, v, "official")[1]))
    return data


if __name__ == "__main__":
    main()
