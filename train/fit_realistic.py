"""Derive the count tables of the realistic generator from the DEV gold (counts only, no sentence text).

Usage: python fit_realistic.py        # prints the MISSING_COMMA / SPURIOUS_COMMA / FORM_ERRORS / WRONG_CASE literals
The output is pasted into corrupt.py; rerun only if the dev gold or the context classes change."""
import collections
import math
import re
import sys

import corrupt as cr
import error_profile as ep
from error_context import prev_group

COMMA_FEATURES = ("ctx", "where", "first_comma", "prev")
CANDIDATE_POS = {"NOUN", "ADJF", "PRTF", "VERB", "ADJS", "PRTS"}


def comma_value(feats, name):
    return prev_group(feats["prev_pos"]) if name == "prev" else feats[name]


def fit_tables(items):
    """Count tables from dev items (src/gold): (missing, spurious, forms, wrong_case, totals)."""
    missing = {f: collections.defaultdict(lambda: [0, 0]) for f in COMMA_FEATURES}
    spurious = {f: collections.defaultdict(lambda: [0, 0]) for f in COMMA_FEATURES}
    forms = collections.defaultdict(lambda: [0, 0])
    wrong_case = collections.Counter()
    totals = collections.Counter()
    skipped = cr.PREPS | cr.CONJ      # the generator never puts a comma after these, so they are no places
    for it in items:
        gold = it["gold"]
        ms = ep.words_of(gold)
        totals["sentences"] += 1
        totals["words"] += len(ms)
        gaps = {i: (has, f) for i, has, f in ep.comma_gaps(gold, ms)}
        for i, (has, f) in gaps.items():
            if not has and ms[i].group(0).lower() in skipped:
                continue
            table = missing if has else spurious     # gold commas can be lost, gold gaps without one can gain one
            for name in COMMA_FEATURES:
                table[name][comma_value(f, name)][1] += 1
        for i, m in enumerate(ms):
            w = m.group(0).lower()
            if re.fullmatch(r"[а-яё]+", w) and len(w) >= 3 and ep._parse(w).tag.POS in CANDIDATE_POS:
                forms[ep.form_features(gold, ms, i, set())["ctx"]][1] += 1
        for kind, gi, detail, si in ep.real_edits(it["src"], gold):
            if kind in ("comma_add", "comma_del") and gi in gaps:
                has, f = gaps[gi]
                if not has and ms[gi].group(0).lower() in skipped:
                    continue
                table = missing if kind == "comma_add" else spurious
                for name in COMMA_FEATURES:
                    table[name][comma_value(f, name)][0] += 1
                totals[kind] += 1
            elif kind == "form" and gi is not None:
                forms[ep.form_features(gold, ms, gi, detail)["ctx"]][0] += 1
                totals["form"] += 1
    freeze = lambda t: {f: {k: tuple(v) for k, v in t[f].items()} for f in t}  # noqa: E731
    return freeze(missing), freeze(spurious), {k: tuple(v) for k, v in forms.items()}, wrong_case, totals


def item_places(it):
    """Every place of the dev gold where an error of each kind could be made, with its features and event count.

    Returns {kind: [(features, events, weight of the round-4 heuristics)]} for kind in missing / spurious / form;
    mirrors the generator's candidates."""
    places = {"missing": [], "spurious": [], "form": []}
    for it in [it]:
        gold = it["gold"]
        ms = ep.words_of(gold)
        if len(ms) < 4:
            continue
        drop, add = cr.comma_candidates(gold, ms)
        events = collections.Counter()
        for kind, gi, detail, si in ep.real_edits(it["src"], gold):
            if kind in ("comma_add", "comma_del", "form") and gi is not None:
                events[(kind, gi)] += 1
        for i, feats in drop:
            places["missing"].append(({n: comma_value(feats, n) for n in COMMA_FEATURES}, events[("comma_add", i)],
                                      cr.comma_drop_weight(gold, ms, i)))
        for i, feats in add:
            plausible = cr.spurious_comma_plausible(ms, i, ms[i + 1].group(0).lower())
            places["spurious"].append(({n: comma_value(feats, n) for n in COMMA_FEATURES}, events[("comma_del", i)],
                                       1.0 if plausible else 0.0))
        for i, ctx, heuristic in cr.form_candidates(gold, ms):
            places["form"].append(({"ctx": ctx}, events[("form", i)], heuristic))
    return places


def dev_places(items, cache=None):
    """Places of all items; cache (id -> places) avoids recomputing them for every fold."""
    out = {"missing": [], "spurious": [], "form": []}
    for it in items:
        key = id(it)
        if cache is not None and key in cache:
            one = cache[key]
        else:
            one = item_places(it)
            if cache is not None:
                cache[key] = one
        for kind in out:
            out[kind] += one[kind]
    return out


# penalty strength per kind, chosen by the document-wise cross-validation (python fit_realistic.py cv): held-out
# log-likelihood is best at ridge 2 for missing commas, 1 for spurious ones, 8 for forms
RIDGE = {"missing": 2.0, "spurious": 1.0, "form": 8.0}
FORMS_ON_HEURISTICS = True


def heuristic_offsets(places):
    """log of the round-4 heuristic weight of every place, mixed with 10% flat so that no place has zero rate."""
    mean_w = sum(x[2] for x in places) / len(places)
    return [math.log(0.9 * x[2] / mean_w + 0.1) for x in places]


def fit_loglinear(places, features, prior_weight=None, ridge=2.0, iterations=150, use_heuristics=False):
    """Poisson log-linear model rate(place) = base * prod_f weight[f][value], fitted by penalised maximum likelihood.

    The penalty ridge/2 * (log weight - log prior weight)^2 per value pulls values with few places or events
    towards the overall rate (or, for a value in prior_weight = {feature: {value: factor}}, towards that factor):
    with 150 events spread over dozens of values the raw rates are noise, and ridge is chosen by cross-validation
    (error_profile.py cv). Each pass updates one value at a time by a damped Newton step, then the base rate is set
    so that the total expected number of events equals the observed one. Returns (base rate, weights)."""
    prior_weight = prior_weight or {}
    n = len(places)
    offset = heuristic_offsets(places) if use_heuristics else [0.0] * n
    total_events = sum(x[1] for x in places)
    log_w = {f: {} for f in features}
    mu = {f: {} for f in features}
    for p, *_ in places:
        for f in features:
            log_w[f].setdefault(p[f], 0.0)
    for f in features:
        for v in log_w[f]:
            mu[f][v] = math.log(prior_weight.get(f, {}).get(v, 1.0))
            log_w[f][v] = mu[f][v]
    events = {f: collections.Counter() for f in features}
    for p, e, *_ in places:
        for f in features:
            events[f][p[f]] += e
    base = total_events / n
    for _ in range(iterations):
        for f in features:
            expected = collections.Counter()
            for (p, *_), off in zip(places, offset):
                expected[p[f]] += base * math.exp(off + sum(log_w[g][p[g]] for g in features))
            for v in log_w[f]:
                grad = events[f][v] - expected[v] - ridge * (log_w[f][v] - mu[f][v])
                log_w[f][v] += grad / (expected[v] + ridge)
        base = total_events / sum(math.exp(off + sum(log_w[g][p[g]] for g in features))
                                 for (p, *_), off in zip(places, offset))
    # gauge: the mean log weight over places is 0 for every table, the base rate carries the level
    places_of = {f: collections.Counter(p[f] for p, *_ in places) for f in features}
    for f in features:
        shift = sum(c * log_w[f][v] for v, c in places_of[f].items()) / n
        for v in log_w[f]:
            log_w[f][v] -= shift
        base *= math.exp(shift)
    return base, {f: {v: round(math.exp(x), 3) for v, x in log_w[f].items()} for f in features}


def fit_weights(items, ridge=None):
    """Rates and weights from dev items: ({kind: base}, missing, spurious, forms, totals)."""
    _, _, _, _, totals = fit_tables(items)
    places = dev_places(items)
    r = {k: ridge for k in RIDGE} if ridge is not None else RIDGE
    miss_base, missing = fit_loglinear(places["missing"], COMMA_FEATURES, ridge=r["missing"])
    spur_base, spurious = fit_loglinear(places["spurious"], COMMA_FEATURES, cr.PRIOR_FACTOR["SPURIOUS"], ridge=r["spurious"])
    form_base, forms = fit_loglinear(places["form"], ("ctx",), ridge=r["form"], use_heuristics=FORMS_ON_HEURISTICS)
    return {"missing": miss_base, "spurious": spur_base, "form": form_base}, missing, spurious, forms["ctx"], totals


def heldout_gain(items, ridges, folds=5):
    """Cross-validated log-likelihood gain (nats per held-out event) of the fitted rates and of the round-4
    heuristics over the uniform rate, by kind. Folds are whole documents, so a document's wording never
    sits on both sides. Poisson log-likelihood of the held-out places: sum(events * log rate - rate)."""
    docs = sorted({it.get("doc", "") for it in items})
    fold_of = {d: i % folds for i, d in enumerate(docs)}
    gain = collections.defaultdict(float)
    events_total = collections.Counter()
    cache = {}
    for fold in range(folds):
        train = [it for it in items if fold_of[it.get("doc", "")] != fold]
        test = [it for it in items if fold_of[it.get("doc", "")] == fold]
        tr, te = dev_places(train, cache), dev_places(test, cache)
        for kind, features in (("missing", COMMA_FEATURES), ("spurious", COMMA_FEATURES), ("form", ("ctx",))):
            n_tr, e_tr = len(tr[kind]), sum(x[1] for x in tr[kind])
            uniform = e_tr / n_tr

            def ll(rate_of):
                return sum(e * math.log(rate_of(p, w)) - rate_of(p, w) for p, e, w in te[kind])
            base_ll = ll(lambda p, w: uniform)
            events_total[kind] += sum(x[1] for x in te[kind])
            mean_w = sum(x[2] for x in tr[kind]) / n_tr
            gain[(kind, "round-4 heuristics")] += ll(lambda p, w: uniform * (0.9 * w / mean_w + 0.1)) - base_ll
            for ridge in ridges:
                factors = cr.PRIOR_FACTOR["SPURIOUS"] if kind == "spurious" else None
                base, weights = fit_loglinear(tr[kind], features, factors, ridge=ridge)
                gain[(kind, "ridge %g" % ridge)] += ll(
                    lambda p, w: base * math.prod(weights[f].get(p[f], 1.0) for f in features)) - base_ll
                if kind == "form":      # the fitted context on top of the round-4 heuristics
                    base, weights = fit_loglinear(tr[kind], features, factors, ridge=ridge, use_heuristics=True)
                    gain[(kind, "heuristics+ridge %g" % ridge)] += ll(
                        lambda p, w: base * math.prod(weights[f].get(p[f], 1.0) for f in features)
                        * (0.9 * w / mean_w + 0.1)) - base_ll
    return {k: v / max(1, events_total[k[0]]) for k, v in gain.items()}, events_total


def main():
    missing_c, spurious_c, forms_c, _, totals = fit_tables(ep.load_dev()["dev"])
    base, missing, spurious, forms, _ = fit_weights(ep.load_dev()["dev"])
    print("# dev: %(sentences)d sentences, %(words)d words; %(comma_add)d missing commas, %(comma_del)d spurious, "
          "%(form)d wrong forms" % totals, file=sys.stderr)
    for name, table in (("MISSING_COUNTS", missing_c), ("SPURIOUS_COUNTS", spurious_c)):
        print("%s = {" % name)
        for f in COMMA_FEATURES:
            items = ", ".join('"%s": (%d, %d)' % (k, v[0], v[1]) for k, v in sorted(table[f].items(), key=lambda kv: -kv[1][1]))
            print('    "%s": {%s},' % (f, items))
        print("}")
    print("FORM_COUNTS = {%s}" % ", ".join('"%s": (%d, %d)' % (k, v[0], v[1]) for k, v in sorted(forms_c.items(), key=lambda kv: -kv[1][1])))
    places = dev_places(ep.load_dev()["dev"])["form"]
    print("FORM_HEURISTIC_MEAN = %.4f" % (sum(x[2] for x in places) / len(places)))
    print("BASE_RATE = {%s}" % ", ".join('"%s": %.5f' % kv for kv in base.items()))
    for name, table in (("MISSING_WEIGHT", missing), ("SPURIOUS_WEIGHT", spurious)):
        print("%s = {" % name)
        for f in COMMA_FEATURES:
            print('    "%s": {%s},' % (f, ", ".join('"%s": %.3g' % (k, v) for k, v in sorted(table[f].items(), key=lambda kv: -kv[1]))))
        print("}")
    print("FORM_WEIGHT = {%s}" % ", ".join('"%s": %.3g' % (k, v) for k, v in sorted(forms.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    if sys.argv[1:2] == ["cv"]:
        gains, totals = heldout_gain(ep.load_dev()["dev"], [float(x) for x in sys.argv[2].split(",")])
        print("held-out events:", dict(totals))
        for (kind, model), g in sorted(gains.items()):
            print("%-9s %-20s %+.3f nats per event over the uniform rate" % (kind, model, g))
    else:
        main()
