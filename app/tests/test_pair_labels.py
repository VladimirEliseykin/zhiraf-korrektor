"""Real error pairs -> comma/form labels (train/pair_labels.py). All sentences are invented."""
import json
import os
import sys

import pytest

import zhiraf

sys.path.insert(0, os.path.join(zhiraf.ROOT, "train"))
import corrupt as cr  # noqa: E402
import pair_labels as pl  # noqa: E402


def derive(src, gold):
    r = pl.derive(src, gold)
    assert r[0] is not None, r[1]
    return r[0]


def test_missing_and_spurious_comma_become_add_and_del():
    s, g, comma, form = derive("Мы решили что завтра пойдем в музей.", "Мы решили, что завтра пойдем в музей.")
    assert comma[words_index(s, "решили")] == "ADD" and comma.count("ADD") == 1
    assert set(form) == {"KEEP"}
    s, g, comma, form = derive("Он пришел, домой поздно.", "Он пришел домой поздно.")
    assert comma[words_index(s, "пришел")] == "DEL" and comma.count("DEL") == 1


def words_index(text, word):
    return [m.group(0) for m in cr.words_of(text)].index(word)


def test_form_edit_gets_a_form_label_and_restores():
    s, g, comma, form = derive("Мы увидели красивая картина.", "Мы увидели красивую картину.")
    assert s == "Мы увидели красивая картина." or s.split()[2] in ("красивая", "красивую")
    assert cr.restore(s, comma, form) == g
    assert any(f != "KEEP" for f in form)


def test_unmodelled_edits_are_normalised_into_src():
    # the capital, the ё, the final period and the misspelling come from gold; only the comma is left to label
    s, g, comma, form = derive("все пришли на встречу но ждал еще один человек", "Все пришли на встречу, но ждал ещё один человек.")
    assert s == "Все пришли на встречу но ждал ещё один человек."
    assert g == "Все пришли на встречу, но ждал ещё один человек."
    assert comma.count("ADD") == 1 and cr.restore(s, comma, form) == g
    s, g, comma, form = derive("Собака лаеть на прохожих.", "Собака лает на прохожих.")
    assert s == g and set(comma) == {"KEEP"} and set(form) == {"KEEP"}


def test_clean_pair_is_all_keep():
    s, g, comma, form = derive("Это обычное предложение без ошибок.", "Это обычное предложение без ошибок.")
    assert s == g and set(comma) == set(form) == {"KEEP"}


def test_labels_are_aligned_with_the_words_of_src():
    s, g, comma, form = derive("Мы знаем что он придет и он принесет подарки друзьям.", "Мы знаем, что он придет, и он принесет подарки друзьям.")
    assert len(cr.words_of(s)) == len(comma) == len(form)
    assert cr.restore(s, comma, form) == g


def test_heavy_rewrites_are_dropped_with_a_reason():
    r = pl.derive("Это совсем другое предложение про погоду сегодня.", "Никто не знает куда уходит время зимой в горах.")
    assert r[0] is None and r[1] in ("too_much_rewriting", "rewrite_too_long")
    assert pl.derive("", "Текст.")[1] == "no_words"
    assert pl.derive("слово " * 200, "слово " * 200)[1] == "too_long"


def test_convert_counts_kept_and_dropped_and_every_kept_pair_restores():
    pairs = [{"src": "Мы решили что пойдем.", "gold": "Мы решили, что пойдем."},
             {"src": "Всё хорошо.", "gold": "Всё хорошо."},
             {"src": "Один два три четыре пять шесть семь восемь.", "gold": "Ни о чём не говорит этот длинный текст совсем."},
             {"src": "Мы увидели красивая картина.", "gold": "Мы увидели красивую картину."}]
    kept, stats = pl.convert(pairs)
    assert stats["input"] == 4 and stats["kept"] == len(kept) == 3 and sum(stats["dropped"].values()) == 1
    assert stats["with_comma_add"] == 1 and stats["clean_after_normalisation"] == 1
    for r in kept:
        assert cr.restore(r["src"], r["comma"], r["form"]) == r["gold"]


def test_main_writes_jsonl_that_loads_as_training_examples(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text(json.dumps({"src": "Мы решили что пойдем.", "gold": "Мы решили, что пойдем."}, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    kept, _ = pl.convert(pl.read_pairs([str(src)]))
    out = tmp_path / "out.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    (text, comma, form, spell), = pl.load_records([str(out)])
    assert text == "Мы решили что пойдем." and comma.count("ADD") == 1 and spell is None
