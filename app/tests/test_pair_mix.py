"""Mixing real pairs into a training batch (train/tagger.py _make_batch, pair_indices). Invented sentences; needs torch."""
import os
import sys

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

import zhiraf  # noqa: E402

sys.path.insert(0, os.path.join(zhiraf.ROOT, "train"))
import pair_labels as pl  # noqa: E402
import tagger as tg  # noqa: E402
from test_spell_train import SENTENCES, tiny  # noqa: E402,F401

PAIRS = [{"src": "Мы решили что пойдем %s." % w, "gold": "Мы решили, что пойдем %s." % w} for w in
         ("домой", "гулять", "спать", "обедать", "играть", "читать", "петь", "бежать", "плавать", "ехать")]


def gen(tokenizer, k, pairs, batch=10, epoch=0, seed=0):
    sents = [s + " " * i for i, s in enumerate(SENTENCES)]  # 40 sentences
    tg._GEN.clear()
    tg.ERROR_DENSITY.update(p_clean=0.25, max_edits=3, p_single=0.0, p_form=0.45, placement=True)
    tg._GEN.update(order=list(range(len(sents))), sents=sents, batch=batch, epoch=epoch, seed=seed,
                   tokenizer=tokenizer, form_index={"KEEP": 0}, k=k, pairs=pairs, steps=4, pair_cache={})
    return tg._make_batch


def examples():
    return [(r["src"], r["comma"], r["form"], None) for r in pl.convert(PAIRS)[0]]


def test_pairs_per_batch_follows_the_share():
    assert tg.pairs_per_batch(32, 0.3) == 10 and tg.pairs_per_batch(32, 0.0) == 0
    assert tg.pairs_per_batch(32, 0.0001) == 1 and tg.pairs_per_batch(32, 1.0) == 31


def test_pair_indices_cycle_through_every_pair_each_pass_and_are_deterministic():
    n = 7
    stream = tg.pair_indices(n, 3 * n, 0, seed=5)
    for p in range(3):
        assert sorted(stream[p * n:(p + 1) * n]) == list(range(n))
    assert stream[:n] != stream[n:2 * n] or n == 1  # reshuffled per pass
    assert tg.pair_indices(n, 3 * n, 0, seed=5) == stream
    assert tg.pair_indices(n, 3 * n, 0, seed=6) != stream
    # any window of the stream is the same wherever it is computed (a worker, a resume)
    assert tg.pair_indices(n, 5, 4, seed=5) == stream[4:9]


def test_batch_takes_the_share_from_real_pairs(tiny):
    _, tokenizer = tiny
    pairs = examples()
    batch = gen(tokenizer, 3, pairs)(1)
    assert len(batch) == 10  # 7 synthetic + 3 real (a synthetic example that fails to restore is not replaced)
    real = {p[0] for p in pairs}
    from_pairs = sum(1 for t in tg_texts(gen(tokenizer, 3, pairs), 1) if t in real)
    assert from_pairs == 3


def tg_texts(make, bi):
    """Texts of the examples a batch is made of (undo nothing: the same calls as _make_batch)."""
    g = tg._GEN
    first = (g["epoch"] * g["steps"] + bi) * g["k"]
    return [g["pairs"][p][0] for p in tg.pair_indices(len(g["pairs"]), g["k"], first, g["seed"], {})]


def test_same_batch_twice_is_identical(tiny):
    _, tokenizer = tiny
    pairs = examples()
    a = gen(tokenizer, 3, pairs, seed=2)(2)
    b = gen(tokenizer, 3, pairs, seed=2)(2)
    assert a == b
    assert gen(tokenizer, 3, pairs, seed=3)(2) != a


def test_flags_off_batch_is_what_make_examples_gives(tiny):
    _, tokenizer = tiny
    make = gen(tokenizer, 0, [])
    g = tg._GEN
    idx = g["order"][1 * 10:2 * 10]
    chunk = tg.make_examples([g["sents"][i] for i in idx], seed=(1000 + 0) * 1_000_003 + 1)
    want = []
    for c, cm, fm, sm in chunk:
        e = tg.encode(tokenizer, c, cm, fm, {"KEEP": 0}, sm)
        want.append(e[:3] + e[4:])
    assert make(1) == want


def test_load_pair_examples_converts_raw_pairs_and_drops_evaluation_sentences(tmp_path):
    import json
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in PAIRS), encoding="utf-8")
    evalf = tmp_path / "eval.jsonl"
    evalf.write_text(json.dumps({"src": "Мы решили, что пойдем спать!"}, ensure_ascii=False) + "\n", encoding="utf-8")
    ex, keys, cut = tg.load_pair_examples([str(raw)], [str(evalf)])
    assert cut == 1 and len(ex) == len(PAIRS) - 1
    assert tg.overlap_check.key("Мы решили, что пойдем домой.") in keys


def test_load_corpus_skips_lines_and_pair_sentences(tmp_path):
    import json
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("".join(json.dumps({"src": "Предложение номер %d." % i}, ensure_ascii=False) + "\n" for i in range(1, 6)),
                      encoding="utf-8")
    sents, _ = tg.load_corpus(str(corpus), [], skip_lines=[2], skip_keys={tg.overlap_check.key("Предложение номер 4.")})
    assert sents == ["Предложение номер 1.", "Предложение номер 3.", "Предложение номер 5."]
    assert len(tg.load_corpus(str(corpus), [])[0]) == 5
