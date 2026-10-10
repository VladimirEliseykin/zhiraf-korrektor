"""Word-to-token alignment: training (HF fast tokenizer, train/tagger.py encode) and product (`tokenizers` from
tokenizer.json, engine/spellcheck/tagger.py) must pick the same token for every word, for ruBERT (WordPiece) and
ruRoBERTa (byte-level BPE). The real tokenizer files of the models are used (vocabularies only); the tests are
skipped where the models folder or transformers is missing."""
import json
import os
import sys

import pytest

import zhiraf
from spellcheck import tagger as product
from spellcheck.text import words_of

MODELS = os.environ.get("ZHIRAF_BASE_MODELS", "/home/general/vm/win7/models")
BERT = os.path.join(MODELS, "ruBert-base")
ROBERTA = os.path.join(MODELS, "ruRoberta-large")

# invented; every kind of word boundary the tokenizers could disagree about
TRICKY = [
    "Привет, мир!",
    "слово",
    "«Кто-то из-за угла» сказал: \"да\".",
    "(Слово) в скобках, [и] в квадратных; {и} в фигурных.",
    "Он купил iPhone 15 Pro и пошёл домой.",
    "В 2024-м году цены выросли на 3,5% (по данным ООО «Ромашка»).",
    "Что-то не так — сказал он — и ушёл.",
    "Письмо на ivan@mail.ru, см. http://example.ru/a?b=1&c=2.",
    "  Двойной  пробел,\tтаб и\nперенос строки.",
    "Слово... и ещё слово?! Да!!!",
    "Разделитель/слэш и под_чёркивание, а ещё 5-10 штук.",
    "ВСЕ ЗАГЛАВНЫЕ БУКВЫ, и ёжик, и Ёлка.",
    "Mixed текст с English words, и 3D-модель.",
    "Кто-нибудь по-прежнему считает, что в-третьих нельзя?",
    "Цена: 1 000 руб.; скидка — 10 %, итого 900.",
    "'Одинарные' кавычки и „немецкие“, и “anglijskie”.",
    "Слово с неразрывным пробелом и мягким­переносом.",
    "а",
    "1",
    "Здравствуйте , уважаемый ,коллега",
]


def _long_text():
    return " ".join("Это предложение номер %d, которое повторяется, чтобы текст не поместился в окно." % i
                    for i in range(40))


def _need(path):
    if not os.path.isdir(path):
        pytest.skip("model %s is not downloaded" % path)


@pytest.fixture(scope="module", params=["ruBert-base", "ruRoberta-large"])
def pair(request, tmp_path_factory):
    """(training tokenizer, product tokenizer) of one base model; the product one reads the saved tokenizer.json."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    path = os.path.join(MODELS, request.param)
    _need(path)
    sys.path.insert(0, os.path.join(zhiraf.ROOT, "train"))
    import tagger as tg
    train_tok = tg.load_base_tokenizer(path)
    out = str(tmp_path_factory.mktemp(request.param))
    train_tok.save_pretrained(out)
    import export_tagger
    export_tagger.compat_tokenizer_json(os.path.join(out, "tokenizer.json"))
    prod_tok = product.load_tokenizer(os.path.join(out, "tokenizer.json"))
    prod_tok.enable_truncation(product.MAX_TOKENS)
    prod_tok.no_padding()
    return tg, train_tok, prod_tok


@pytest.mark.parametrize("text", TRICKY + [_long_text()])
def test_training_and_product_pick_the_same_tokens(pair, text):
    tg, train_tok, prod_tok = pair
    ids, _, _, train_pos, _ = tg.encode(train_tok, text)
    enc = prod_tok.encode(text)
    assert enc.ids == ids
    assert product.word_positions(enc.offsets, text) == train_pos


@pytest.mark.parametrize("text", TRICKY)
def test_every_word_gets_a_token_that_starts_at_it(pair, text):
    tg, train_tok, prod_tok = pair
    enc = prod_tok.encode(text)
    pos = product.word_positions(enc.offsets, text)
    words = list(words_of(text))
    assert sorted(pos) == list(range(len(words)))
    for w, t in pos.items():
        assert enc.offsets[t][0] == words[w].start()
        assert enc.offsets[t][1] > enc.offsets[t][0]


def test_first_word_of_a_sentence_and_after_punctuation_is_tokenized_like_in_running_text(pair):
    _, train_tok, _ = pair
    # the same word at the start and after a space gets the same token ids (RoBERTa: add_prefix_space)
    a = train_tok("шоколадный шоколадный", add_special_tokens=False)["input_ids"]
    assert len(a) % 2 == 0 and a[:len(a) // 2] == a[len(a) // 2:]


def test_truncation_keeps_the_limit_and_special_tokens_in_both(pair):
    tg, train_tok, prod_tok = pair
    text = _long_text()
    ids = tg.encode(train_tok, text)[0]
    assert len(ids) == product.MAX_TOKENS == len(prod_tok.encode(text).ids)
    assert ids[0] == train_tok.cls_token_id and ids[-1] == train_tok.sep_token_id


def test_product_reads_the_tokenizer_json_of_newer_tokenizers(tmp_path):
    """tokenizers 0.20+ writes BPE merges as pairs; the pinned 0.19.1 only reads "a b" strings."""
    _need(ROBERTA)
    pytest.importorskip("transformers")
    from transformers import AutoTokenizer
    AutoTokenizer.from_pretrained(ROBERTA, add_prefix_space=True).save_pretrained(str(tmp_path))
    path = str(tmp_path / "tokenizer.json")
    tok = product.load_tokenizer(path)  # either format
    assert tok.encode("Привет, мир").ids
    data = json.load(open(path, encoding="utf-8"))
    data["model"]["merges"] = [" ".join(m) if isinstance(m, list) else m for m in data["model"]["merges"]]
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    assert product.load_tokenizer(path).encode("Привет, мир").ids == tok.encode("Привет, мир").ids


def test_product_alignment_with_a_byte_level_bpe_built_from_the_vocabulary_files():
    """No transformers needed: the product-side rule on a tokenizer assembled from vocab.json/merges.txt."""
    _need(ROBERTA)
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    tok = Tokenizer(models.BPE.from_file(os.path.join(ROBERTA, "vocab.json"), os.path.join(ROBERTA, "merges.txt")))
    tok.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=True)
    tok.post_processor = processors.RobertaProcessing(("</s>", 2), ("<s>", 1), trim_offsets=True,
                                                      add_prefix_space=True)
    for text in TRICKY:
        enc = tok.encode(text)
        pos = product.word_positions(enc.offsets, text)
        words = list(words_of(text))
        assert sorted(pos) == list(range(len(words))), text
        for w, t in pos.items():
            assert enc.offsets[t][0] == words[w].start()
