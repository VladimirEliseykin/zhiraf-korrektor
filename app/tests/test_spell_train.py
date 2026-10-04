"""The training side of the spelling head: tagger.py with a tiny random BERT (needs torch + transformers,
which only the training venv has; elsewhere these tests are skipped)."""
import os
import random
import sys

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

import zhiraf  # noqa: E402

sys.path.insert(0, os.path.join(zhiraf.ROOT, "train"))
import corrupt as cr  # noqa: E402
import tagger as tg  # noqa: E402

SENTENCES = ["Компания получила сверхдоходности от продажи акций, поэтому руководство пересмотрело планы.",
             "Из-за задержки какой-то документ не был принят, хотя директор подписал приказ.",
             "Мы решили не делать лишней работы сегодня и не отвечать на письмо.",
             "Налоговая служба направила письмо директору департамента о городе."] * 10


@pytest.fixture
def tiny(tmp_path):
    from transformers import BertConfig, BertModel, BertTokenizerFast
    config = BertConfig(vocab_size=64, hidden_size=16, num_hidden_layers=1, num_attention_heads=2,
                        intermediate_size=32, max_position_embeddings=256)
    BertModel(config).save_pretrained(str(tmp_path / "base"))
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + list("абвгдежзийклмнопрстуфхцчшщъыьэюя") + [",", "-", "."]
    (tmp_path / "vocab.txt").write_text("\n".join(vocab), encoding="utf-8")
    tokenizer = BertTokenizerFast(str(tmp_path / "vocab.txt"), do_lower_case=False)
    return str(tmp_path / "base"), tokenizer


def old_make_examples(sents, seed):
    """make_examples as it was before the spelling head (kept here to prove the default did not change)."""
    rng = random.Random(seed)
    out = []
    for s in sents:
        c, cm, fm = cr.corrupt(s, rng, **tg.ERROR_DENSITY)
        if cr.restore(c, cm, fm) == s:
            out.append((c, cm, fm))
    return out


def test_make_examples_with_the_head_off_reproduces_the_old_recipe():
    tg.SPELL_DENSITY["p_spell"] = 0.0
    for seed in (1, 12345):
        new = tg.make_examples(SENTENCES, seed)
        assert [e[:3] for e in new] == old_make_examples(SENTENCES, seed)
        assert all(e[3] is None for e in new)


def test_make_examples_with_the_head_on_keeps_only_restorable_aligned_examples():
    tg.SPELL_DENSITY["p_spell"] = 0.5
    try:
        examples = tg.make_examples(SENTENCES, 7)
    finally:
        tg.SPELL_DENSITY["p_spell"] = 0.0
    assert examples and any(l != "KEEP" for e in examples for l in e[3])
    for c, cm, fm, sm in examples:
        assert len(cr.words_of(c)) == len(cm) == len(fm) == len(sm)
        assert cr.restore(c, cm, fm, sm) in SENTENCES


def test_encode_puts_spell_labels_on_first_subtokens(tiny):
    _, tokenizer = tiny
    c, cm, fm, sm = cr.corrupt_spell(SENTENCES[1], random.Random(0), p_spell=1.0, rates={"hyphen": 1e9}, p_clean=1.0)
    ids, comma_y, form_y, word_pos, spell_y = tg.encode(tokenizer, c, cm, fm, {"KEEP": 0}, sm)
    hyphen = [i for i, l in enumerate(sm) if l == "HYPHEN"]
    assert hyphen and spell_y[word_pos[hyphen[0]]] == cr.SPELL_LABELS.index("HYPHEN")
    assert sum(1 for y in spell_y if y != -100) == len(word_pos)
    # without spell labels the target stays ignored
    assert set(tg.encode(tokenizer, c)[4]) == {-100}


def test_head_loading_warm_starts_from_a_model_without_it(tiny):
    base, _ = tiny
    old = tg.TaggerModel(base, 5)
    assert old.spell_head is None and not any(k.startswith("spell_head") for k in old.state_dict())
    new = tg.TaggerModel(base, 5, len(cr.SPELL_LABELS))
    fresh = tg.load_weights(new, old.state_dict())
    assert sorted(fresh) == ["spell_head.bias", "spell_head.weight"]
    assert torch.equal(new.comma_head.weight, old.comma_head.weight) and torch.equal(new.form_head.bias, old.form_head.bias)
    ids = torch.tensor([[2, 5, 6, 3]])
    mask = torch.ones_like(ids)
    assert len(old(ids, mask)) == 2 and len(new(ids, mask)) == 3
    # a checkpoint of the model with the head loads without anything being fresh
    assert tg.load_weights(tg.TaggerModel(base, 5, len(cr.SPELL_LABELS)), new.state_dict()) == []
    # a checkpoint that does not fit is still an error
    with pytest.raises(RuntimeError):
        tg.load_weights(tg.TaggerModel(base, 7), old.state_dict())


def test_evaluate_reports_every_spelling_label(tiny):
    base, tokenizer = tiny
    tg.SPELL_DENSITY["p_spell"] = 0.9
    try:
        examples = tg.make_examples(SENTENCES, 3)
    finally:
        tg.SPELL_DENSITY["p_spell"] = 0.0
    model = tg.TaggerModel(base, 3, len(cr.SPELL_LABELS))
    report = tg.evaluate(model, tokenizer, examples, ["KEEP", "case:gent", "case:nomn"], torch.device("cpu"))
    assert {"comma", "form", "spell"} <= set(report)
    assert all("spell_" + l in report and "n" in report["spell_" + l] for l in cr.SPELL_LABELS[1:])
    assert sum(report["spell_" + l]["n"] for l in cr.SPELL_LABELS[1:]) > 0
    plain = tg.evaluate(tg.TaggerModel(base, 3), tokenizer, [e[:3] + (None,) for e in examples], ["KEEP", "case:gent", "case:nomn"],
                        torch.device("cpu"))
    assert set(plain) == {"comma", "form"}


def test_decode_matches_the_head_layout():
    comma, form, spell = torch.zeros(1, 3, 3), torch.zeros(1, 3, 2), torch.zeros(1, 3, 6)
    spell[0, 1, 2] = 10.0
    res = tg.decode([comma, form, spell], ["KEEP", "case:gent"], {0: 1})
    assert res[0]["spell"]["HYPHEN"] > 0.99 and set(res[0]["spell"]) == set(cr.SPELL_LABELS)
    assert "spell" not in tg.decode([comma, form], ["KEEP", "case:gent"], {0: 1})[0]
