"""Spelling labels: the corruptions (train/corrupt.py), the checker findings, the product tagger decoding.

All sentences are invented; no gold or corpus text is used here."""
import os
import random
import sys

import numpy as np
import pytest

import zhiraf
from fakes import FakeTagger
from spellcheck import tagger as product_tagger
from spellcheck.checker import SPELL_THRESHOLDS, Checker, merge, spell_findings
from spellcheck.text import words_of

TRAIN = os.path.join(zhiraf.ROOT, "train")
sys.path.insert(0, TRAIN)
import corrupt as cr  # noqa: E402

KEEP = cr.SPELL_KEEP
CLEAN = {"p_clean": 1.0}  # no comma/form errors: only the spelling pass edits the sentence


def only(kind, p=1.0):
    return {"p_spell": p, "rates": {kind: 1e9}}


def make(text, kind, seed=0):
    return cr.corrupt_spell(text, random.Random(seed), **only(kind), **CLEAN)


def labelled(c, spell):
    return [(m.group(0), l) for m, l in zip(words_of(c), spell) if l != KEEP]


# ---- corruptions ----------------------------------------------------------------------------------

SENTENCES = [
    "Компания получила сверхдоходности от продажи акций, поэтому руководство пересмотрело планы.",
    "Отчеты по незакрытых договорам были сданы вовремя, зато все остальные остались до конца собрания.",
    "Из-за задержки какой-то документ не был принят, хотя директор Иван Петров подписал приказ.",
    "Налоговая служба направила письмо директору департамента о городе Москве.",
    "Мы решили не делать лишней работы сегодня и не отвечать на письмо.",
    "Короткое предложение.",
]


def test_flags_off_reproduce_corrupt_exactly():
    for seed in range(40):
        for text in SENTENCES:
            a, b = random.Random(seed), random.Random(seed)
            old = cr.corrupt(text, a)
            new = cr.corrupt_spell(text, b)
            assert new[:3] == old and set(new[3]) <= {KEEP} and len(new[3]) == len(old[1])
            assert a.getstate() == b.getstate()  # the generator is not touched: later sentences are the same


def test_decimal_comma_is_never_dropped():
    # "27,5" is two words for words_of; dropping its comma glued them into "275" and the example was lost
    text = "Доля выросла до 27,5 процента за год работы"
    for seed in range(200):
        c, comma, form = cr.corrupt(text, random.Random(seed), p_clean=0.0, max_edits=3, p_form=0.0)
        assert "27,5" in c and len(words_of(c)) == len(comma) == len(form)


def test_restore_without_spell_labels_is_unchanged():
    text = "Мы пришли рано мы ушли"
    comma = [cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_ADD, cr.COMMA_KEEP, cr.COMMA_KEEP]
    form = [cr.FORM_KEEP] * 5
    assert cr.restore(text, comma, form) == cr.restore(text, comma, form, [KEEP] * 5) == "Мы пришли рано, мы ушли"


@pytest.mark.parametrize("kind", ["join", "hyphen", "split", "lower", "upper"])
def test_labels_align_with_words_and_restore_the_clean_text(kind):
    seen = 0
    for text in SENTENCES:
        for seed in range(6):
            c, comma, form, spell = make(text, kind, seed)
            assert len(words_of(c)) == len(spell) == len(comma) == len(form)
            assert cr.restore(c, comma, form, spell) == text
            seen += any(l != KEEP for l in spell)
    assert seen, "no sentence got a %s error" % kind


def test_join_splits_a_word_and_labels_the_first_part():
    c, comma, form, spell = make("Компания получила сверхдоходности от продажи акций, поэтому руководство ушло.", "join", 3)
    assert labelled(c, spell) in ([("сверх", "JOIN")], [("по", "JOIN")])
    c, _, _, spell = make("Отчеты по незакрытых договорам были сданы вовремя.", "join")
    assert c == "Отчеты по не закрытых договорам были сданы вовремя." and labelled(c, spell) == [("не", "JOIN")]


def test_split_word_keeps_its_comma_on_the_second_part():
    text = "Мы пришли рано, зато остальные остались."
    c, comma, form, spell = make(text, "join")
    assert c == "Мы пришли рано, за то остальные остались."
    assert labelled(c, spell) == [("за", "JOIN")]


def test_comma_label_of_a_split_word_moves_to_its_second_part(monkeypatch):
    # the comma tagger saw "поэтому" and wants a comma after it (the comma was dropped by the first pass)
    stub = ("Он ушёл поэтому как мы знаем", [cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_ADD] + [cr.COMMA_KEEP] * 3,
            [cr.FORM_KEEP] * 6)
    monkeypatch.setattr(cr, "corrupt", lambda text, rng, **kw: stub)
    c, comma, form, spell = cr.corrupt_spell("ignored", random.Random(0), **only("join"))
    assert c == "Он ушёл по этому как мы знаем"
    assert comma == [cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_ADD] + [cr.COMMA_KEEP] * 3
    assert spell[2] == "JOIN" and len(form) == 7
    assert cr.restore(c, comma, form, spell) == "Он ушёл поэтому, как мы знаем"


def test_capital_of_a_split_word_stays_on_the_first_part():
    c, _, _, spell = make("Поэтому мы решили остаться дома надолго.", "join")
    assert c.startswith("По этому мы") and spell[0] == "JOIN"


def test_restore_moves_the_comma_onto_the_joined_word():
    text = "Мы пришли за то мы рано"
    comma = [cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_KEEP, cr.COMMA_ADD, cr.COMMA_KEEP, cr.COMMA_KEEP]
    spell = [KEEP, KEEP, "JOIN", KEEP, KEEP, KEEP]
    assert cr.restore(text, comma, [cr.FORM_KEEP] * 6, spell) == "Мы пришли зато, мы рано"


def test_hyphen_replaces_the_hyphen_with_a_space():
    c, _, _, spell = make("Из-за задержки документ не был принят.", "hyphen")
    assert c == "Из за задержки документ не был принят." and labelled(c, spell) == [("Из", "HYPHEN")]
    c, _, _, spell = make("Кто-нибудь должен был прийти.", "hyphen")
    assert c == "Кто нибудь должен был прийти." and spell[0] == "HYPHEN"


def test_hyphen_at_a_line_break_is_not_a_compound():
    # "заво-да" is a hyphenated "завода": the corruption would teach a wrong rule
    c, _, _, spell = make("Мы приехали на заво-да утром.", "hyphen")
    assert c == "Мы приехали на заво-да утром." and set(spell) == {KEEP}


def test_split_error_joins_ne_with_a_verb():
    c, _, _, spell = make("Мы решили не делать лишней работы.", "split")
    assert c == "Мы решили неделать лишней работы." and labelled(c, spell) == [("неделать", "SPLIT")]
    comma = [cr.COMMA_KEEP] * 5
    assert cr.restore(c, comma, [cr.FORM_KEEP] * 5, spell) == "Мы решили не делать лишней работы."


def test_ne_with_a_noun_or_adjective_is_not_joined():
    c, _, _, spell = make("Это не проблема для нас.", "split")
    assert set(spell) == {KEEP}


def test_lower_capitalises_a_common_noun_after_a_capitalised_word():
    c, _, _, spell = make("Налоговая газета направила письмо.", "lower", 1)
    assert ("Письмо", "LOWER") in labelled(c, spell) or ("Газета", "LOWER") in labelled(c, spell)
    for seed in range(8):
        c, _, _, spell = make("Налоговая газета направила письмо.", "lower", seed)
        assert not spell[0] == "LOWER"  # the first word of a sentence is never a LOWER target


def test_upper_lowercases_a_sentence_start_or_a_name():
    c, _, _, spell = make("Порядок утверждён приказом руководителя.", "upper")
    assert c == "порядок утверждён приказом руководителя." and spell[0] == "UPPER"
    results = [make("Заместитель Иван Петров подписал приказ.", "upper", s) for s in range(20)]
    names = {labelled(c, sp)[0][0] for c, _, _, sp in results if labelled(c, sp)}
    assert names & {"иван", "петров"}


def test_protected_places_are_never_touched():
    texts = ['В программе «Из-за океана» участвовали Wi-Fi и ЭВМ-класса в 2020-2021 годах.',
             'См. «Налоговая служба» и "не делать" а также [Электронный ресурс] // Ведомости.',
             "Файл Web-технологий версии 2-3 готов.",
             "Файл с ГОСТ Р 5-6 и АО Иван."]
    for text in texts:
        for kind in ("join", "hyphen", "split", "lower", "upper"):
            for seed in range(4):
                c, comma, form, spell = make(text, kind, seed)
                if kind in ("lower", "upper"):
                    # a plain common noun may change; quoted, latin, numeric and abbreviated words may not
                    assert all(t in c for t in ("«Из-за океана»", "Wi-Fi", "ЭВМ-класса", "2020-2021", "ГОСТ", "АО", "5-6") if t in text)
                else:
                    assert c == text and set(spell) == {KEEP}, (kind, c)


def test_words_with_form_errors_are_not_spell_edited():
    rng = random.Random(7)
    for text in SENTENCES:
        for _ in range(30):
            c, comma, form, spell = cr.corrupt_spell(text, rng, p_spell=1.0, rates={k: 1e9 for k in cr.SPELL_RATES})
            assert len(words_of(c)) == len(spell) == len(form)
            assert all(l == KEEP for l, f in zip(spell, form) if f != cr.FORM_KEEP)


def test_default_rates_are_small():
    rng = random.Random(3)
    hit = 0
    n = 300
    for k in range(n):
        spell = cr.corrupt_spell(SENTENCES[k % 5], rng, p_spell=0.05, **CLEAN)[3]
        hit += any(l != KEEP for l in spell)
    assert hit < n * 0.5


# ---- checker.spell_findings ------------------------------------------------------------------------

def preds_for(body, labels):
    """Fake predictions: labels = {word index: (label, p)}."""
    out = []
    for i, _ in enumerate(words_of(body)):
        name, p = labels.get(i, (KEEP, 1.0))
        probs = {k: 0.0 for k in cr.SPELL_LABELS}
        probs[name] = p
        probs[KEEP] += 1.0 - p if name != KEEP else 0.0
        out.append({"comma": {"KEEP": 1.0, "ADD": 0.0, "DEL": 0.0}, "form": "KEEP", "form_p": 1.0, "form_keep_p": 1.0,
                    "spell": probs})
    return out


ALL = {label: (0.9, 0.3) for label in cr.SPELL_LABELS if label != "KEEP"}  # every label on, to test the mechanics


LOWER_ON = dict(SPELL_THRESHOLDS, LOWER=(None, 0.97))  # the measured setting, off in the product


def one(body, labels, thresholds=SPELL_THRESHOLDS):
    found = spell_findings(body, preds_for(body, labels), thresholds)
    return [(body[f["start"]:f["end"]], f["fix"], f["level"], f["message"]) for f in found]


def test_join_finding_replaces_both_words():
    body = "Он ушёл по этому пути, но не по этому."
    assert one("Мы остались по этому не стали ждать.", {2: ("JOIN", 0.95)}) == [
        ("по этому", "поэтому", "check", "Возможно, слово пишется слитно")]  # valid apart elsewhere: never sure
    assert one("Компания получила сверх доходности от акций.", {2: ("JOIN", 0.95)}) == [
        ("сверх доходности", "сверхдоходности", "error", "Слово пишется слитно")]
    assert one("Мы остались по этому не стали ждать.", {2: ("JOIN", 0.5)})[0][2:] == ("check", "Возможно, слово пишется слитно")
    assert one(body, {2: ("JOIN", 0.29)}) == []


def test_hyphen_finding():
    assert one("Это сделано из за ошибки.", {2: ("HYPHEN", 0.97)}) == [("из за", "из-за", "error", "Нужен дефис")]


def test_split_finding_puts_a_space_after_ne():
    assert one("Мы решили неделать этого.", {2: ("SPLIT", 0.95)}) == [
        ("неделать", "не делать", "error", "Частица «не» пишется раздельно")]
    assert one("Это незнание вредит.", {1: ("SPLIT", 0.95)}) == []  # a real word, a noun


def test_case_findings():
    assert one("Налоговая Газета направила письмо.", {1: ("LOWER", 0.98)}, LOWER_ON) == [
        ("Газета", "газета", "check", "Возможно, слово пишется с маленькой буквы")]
    assert one("Налоговая Газета направила письмо.", {0: ("LOWER", 0.98)}) == []  # sentence start
    assert one("Директор иван Петров ушёл.", {1: ("UPPER", 0.95)}, ALL) == [
        ("иван", "Иван", "error", "Слово пишется с большой буквы")]
    assert one("Мы видели город москва.", {3: ("UPPER", 0.95)}, ALL)[0][1] == "Москва"
    assert one("Мы видели свежую газету.", {3: ("UPPER", 0.95)}, ALL) == []  # a common noun is not capitalised


def test_sentence_start_capital_is_only_a_check_and_only_for_whole_sentences():
    assert one("порядок утверждён приказом.", {0: ("UPPER", 0.99)}, ALL) == [
        ("порядок", "Порядок", "check", "Возможно, слово пишется с большой буквы")]
    assert one("обеспечение доступа;", {0: ("UPPER", 0.99)}, ALL) == []  # a list item


def test_names_and_known_words_are_not_lowered():
    assert one("Мы видели Российская Федерация там.", {3: ("LOWER", 0.99)}) == []  # a capital of official language
    assert one("Мы видели Российская Федерация там.", {2: ("LOWER", 0.99)}) == []  # an adjective is never lowered


def test_spell_findings_skip_quotes_protected_words_and_bibliography():
    assert one("Книга «Из за океана» вышла.", {2: ("HYPHEN", 0.99)}) == []
    assert one("Файл Wi Fi готов.", {1: ("HYPHEN", 0.99)}) == []
    assert one("Иванов А. Из за океана // Ведомости.", {2: ("HYPHEN", 0.99)}) == []
    assert one("Мы остались по, этому не стали.", {2: ("JOIN", 0.99)}) == []  # not a plain gap


def test_no_op_for_a_model_without_the_head():
    body = "Мы остались по этому не стали ждать."
    preds = preds_for(body, {2: ("JOIN", 0.99)})
    for p in preds:
        del p["spell"]
    assert spell_findings(body, preds) == [] and spell_findings(body, []) == []


def test_spell_findings_merge_with_other_findings():
    body = "Мы остались по этому не стали ждать."
    found = spell_findings(body, preds_for(body, {2: ("JOIN", 0.95)}))
    comma = {"start": 14, "end": 14, "level": "check", "rule": "MODEL_COMMA", "fix": ",", "message": "m"}
    assert [f["rule"] for f in merge(found + [comma])] == ["MODEL_SPELL"]  # an insertion inside the joined span: the sure one wins
    form = {"start": 15, "end": 20, "level": "check", "rule": "MODEL_FORM", "fix": "этой", "message": "m"}
    assert [f["rule"] for f in merge(found + [form])] == ["MODEL_SPELL"]  # same place: the surer level wins
    far = {"start": 30, "end": 35, "level": "check", "rule": "MODEL_FORM", "fix": "ждали", "message": "m"}
    assert [f["rule"] for f in merge(found + [far])] == ["MODEL_SPELL", "MODEL_FORM"]


def test_spelling_comes_from_the_spell_stage_only(models_dir):
    spell = {"доходности": ("KEEP", 1.0), "сверх": ("JOIN", 0.95)}
    factories = {"commas": lambda: FakeTagger(spell=spell), "forms": lambda: FakeTagger(),
                 "spell": lambda: FakeTagger(spell=spell), "sage": lambda: None}
    checker = Checker(models_dir, factories=factories)
    found = {}
    for stage, i, items in checker.stream(["Мы получили сверх доходности от акций."], stages=("commas", "forms", "spell")):
        found[stage] = [(f["rule"], f["fix"], f["level"]) for f in items]
    assert found["spell"] == [("MODEL_SPELL", "сверхдоходности", "error")]
    assert found["commas"] == found["forms"] == []  # a model with the head in another stage adds no spelling


# ---- product tagger decoding -----------------------------------------------------------------------

def logits(n_tokens, n_form, spell_hot=None):
    comma = np.zeros((1, n_tokens, 3), dtype=np.float32)
    form = np.zeros((1, n_tokens, n_form), dtype=np.float32)
    form[..., 0] = 5
    comma[..., 0] = 5
    out = [comma, form]
    if spell_hot is not None:
        sp = np.zeros((1, n_tokens, 6), dtype=np.float32)
        sp[..., 0] = 5
        for t, k in spell_hot.items():
            sp[0, t, 0], sp[0, t, k] = 0.0, 9.0
        out.append(sp)
    return out


def test_decode_without_the_head_has_no_spell_key():
    res = product_tagger.decode(logits(4, 3), ["KEEP", "case:gent", "number:plur"], {0: 1, 1: 2})
    assert len(res) == 2 and all("spell" not in r for r in res)
    assert res[0]["form"] == "KEEP" and 0.9 < res[0]["form_p"] <= 1.0


def test_decode_with_the_head_gives_probabilities_per_label():
    res = product_tagger.decode(logits(4, 3, {2: 1}), ["KEEP", "a", "b"], {0: 1, 1: 2})
    assert set(res[0]["spell"]) == set(cr.SPELL_LABELS) and res[1]["spell"]["JOIN"] > 0.99
    assert res[0]["spell"]["KEEP"] > 0.9 and abs(sum(res[1]["spell"].values()) - 1.0) < 1e-5


class FakeEncoding:
    def __init__(self, text):
        import re
        self.offsets = [(0, 0)] + [m.span() for m in re.finditer(r"\w+", text)] + [(0, 0)]
        self.ids = list(range(len(self.offsets)))


class FakeTokenizer:
    def encode(self, text):
        return FakeEncoding(text)


class FakeSession:
    def __init__(self, with_head):
        self.with_head = with_head

    def run(self, _, feed):
        n = feed["input_ids"].shape[1]
        return logits(n, 2, {2: 1} if self.with_head else None)


@pytest.mark.parametrize("with_head", [False, True])
def test_product_tagger_predicts_with_and_without_the_head(with_head):
    t = product_tagger.EditTagger.__new__(product_tagger.EditTagger)
    t.form_labels, t.tokenizer, t.session = ["KEEP", "case:gent"], FakeTokenizer(), FakeSession(with_head)
    t.spell_labels = product_tagger.SPELL_LABELS
    res = t.predict("Мы пошли домой")
    assert len(res) == 3 and all(set(r["comma"]) == {"KEEP", "ADD", "DEL"} for r in res)
    assert ("spell" in res[1]) == with_head
    if with_head:
        assert res[1]["spell"]["JOIN"] > 0.99 and res[0]["spell"]["KEEP"] > 0.9


# ---- review fixes: title nouns, ambiguous pairs, symmetric guards ---------------------------------------

def capital_file_lemmas():
    path = os.path.join(zhiraf.ENGINE_DIR, "spellcheck", "capital_lemmas.txt")
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip() and not line.startswith("#")}


TITLE_NOUNS = ["министерство", "служба", "комитет", "департамент", "управление", "банк", "комиссия", "агентство",
               "закон", "финансы", "центр", "фонд", "институт", "федерация"]


def test_title_nouns_are_in_the_shipped_list_and_it_is_the_only_copy():
    from spellcheck import checker
    lemmas = capital_file_lemmas()
    assert set(TITLE_NOUNS) <= lemmas and len(lemmas) > 1000
    assert checker.CAPITAL_LEMMAS == lemmas and cr.CAPITAL_LEMMAS == lemmas
    assert "федерация" not in open(os.path.join(TRAIN, "corrupt.py"), encoding="utf-8").read()


def test_lower_never_capitalises_a_title_noun():
    text = "Мы отправили письмо в министерство и обратились в комитет по закону для проверки."
    lemmas = capital_file_lemmas()
    seen = set()
    for seed in range(60):
        c, _, _, spell = make(text, "lower", seed)
        for word, label in labelled(c, spell):
            assert label == "LOWER"
            seen.add(word)
    assert seen and not {w.lower() for w in seen} & {"министерство", "комитет", "закону", "закон"}
    assert all(not any(w.lower() == t for t in lemmas) for w in seen)


def test_lower_places_carry_no_role_or_capitalised_neighbour_weight():
    c = "Налоговая газета опубликовала письмо директора совета."
    cands = cr.spell_candidates(c, words_of(c), [cr.COMMA_KEEP] * 7, [cr.FORM_KEEP] * 7)["lower"]
    assert cands and {w for _, w, _ in cands} == {1.0}


def test_lower_finding_skips_title_nouns_whatever_the_probability():
    body = "Мы отправили письмо в Министерство юстиции."
    assert one(body, {4: ("LOWER", 0.999)}) == []
    assert one("Мы отправили письмо в Комитет по делам.", {4: ("LOWER", 0.999)}) == []


def test_lower_is_sure_or_nothing():
    body = "Налоговая Газета направила письмо."
    assert one(body, {1: ("LOWER", 0.96)}) == []
    assert one(body, {1: ("LOWER", 0.5)}) == []
    assert one(body, {1: ("LOWER", 0.98)}, LOWER_ON) == [("Газета", "газета", "check", "Возможно, слово пишется с маленькой буквы")]


def test_join_of_ne_needs_a_known_joined_word():
    assert one("Мы решили не делать этого.", {2: ("JOIN", 0.99)}) == []       # "неделать" is no word
    assert one("Отчеты по не закрытых договорам сданы.", {2: ("JOIN", 0.99)})[0][1] == "незакрытых"


@pytest.mark.parametrize("body", ["Он сделал так же как и мы.", "Это то же самое для нас.", "Он ответил то же же.",
                                  "Он сделал так же же как мы."])
def test_join_skips_a_valid_pair_before_kak_zhe_samoe(body):
    i = [m.group(0) for m in words_of(body)].index("так" if "так" in body else "то")
    assert one(body, {i: ("JOIN", 0.99)}) == []


@pytest.mark.parametrize("body,label_at,fix", [
    ("Он ответил так же быстро.", 2, "также"),
    ("Мы остались по этому не стали ждать.", 2, "поэтому"),
    ("Она сказала что бы мы ушли.", 2, "чтобы"),
    ("Мы заплатим на счет отдела.", 2, "насчет"),
    ("Они пришли за то остались.", 2, "зато"),
])
def test_join_of_an_ambiguous_pair_is_never_sure(body, label_at, fix):
    found = one(body, {label_at: ("JOIN", 0.999)})
    assert len(found) == 1 and found[0][1] == fix and found[0][2] == "check"


def test_join_of_an_unambiguous_pair_stays_sure():
    assert one("Компания получила сверх доходности от акций.", {2: ("JOIN", 0.95)})[0][1:3] == ("сверхдоходности", "error")


def test_hyphen_needs_the_same_dictionary_guard_as_the_generator():
    assert one("Мы приехали на заво да утром.", {3: ("HYPHEN", 0.99)}) == []  # "завода" is a word
    assert one("Это сделано из за ошибки.", {2: ("HYPHEN", 0.99)})[0][1] == "из-за"


def test_corruption_keeps_valid_pairs_before_kak_samoe_zhe_and_ni():
    for text, joined in (("Он пришёл также как и вы вчера.", "также"), ("Они сделали тоже самое для нас.", "тоже"),
                         ("Он решил тоже же как мы вчера.", "тоже"), ("Он сделал это чтобы ни один не ушёл.", "чтобы")):
        for seed in range(40):
            c, _, _, spell = make(text, "join", seed)
            assert joined in c, (c, seed)


def test_ne_with_adjectives_and_participles_is_corrupted_half_as_often():
    c = "Отчеты по незакрытых договорам были сданы вовремя."
    cut = cr.prefix_split("незакрытых")
    assert cut == (2, 2.5)


def test_findings_carry_their_label_and_thresholds_can_be_swept():
    body = "Налоговая Газета направила письмо."
    preds = preds_for(body, {1: ("LOWER", 0.8)})
    assert spell_findings(body, preds) == []                                  # below SURE_LOWER
    found = spell_findings(body, preds, {"LOWER": (0.5, 0.5)})                # the evaluation sweeps both
    assert [f["label"] for f in found] == ["LOWER"]


def test_shipped_spell_thresholds_are_pinned():
    # measured on the real gold with train/spell_eval.py (see the comment at SPELL_THRESHOLDS)
    assert SPELL_THRESHOLDS == {"JOIN": (0.9, 0.3), "HYPHEN": (0.97, 0.7), "LOWER": (None, 1.01), "SPLIT": (0.9, 0.5)}
    assert "UPPER" not in SPELL_THRESHOLDS


def test_shipped_thresholds_per_label():
    assert one("Компания получила сверх доходности от акций.", {2: ("JOIN", 0.89)})[0][2] == "check"
    assert one("Компания получила сверх доходности от акций.", {2: ("JOIN", 0.29)}) == []
    assert one("Это сделано из за ошибки.", {2: ("HYPHEN", 0.96)})[0][2] == "check"
    assert one("Это сделано из за ошибки.", {2: ("HYPHEN", 0.69)}) == []
    assert one("Налоговая Газета направила письмо.", {1: ("LOWER", 0.96)}, LOWER_ON) == []
    assert one("Налоговая Газета направила письмо.", {1: ("LOWER", 0.999)}) == []  # disabled end to end
    assert one("Налоговая Газета направила письмо.", {1: ("LOWER", 0.999)}, LOWER_ON)[0][2] == "check"  # never an error
    assert one("Мы решили неделать этого.", {2: ("SPLIT", 0.89)})[0][2] == "check"
    assert one("Мы решили неделать этого.", {2: ("SPLIT", 0.49)}) == []
    assert one("Директор иван Петров ушёл.", {1: ("UPPER", 0.999)}) == []  # disabled
