"""Spelling rules of the engine (rules.py) and the SAGE typo acceptance (sage.py), on made-up sentences."""
import pytest

from spellcheck import rules, sage


@pytest.fixture(scope="module")
def lexicon(tmp_path_factory):
    path = tmp_path_factory.mktemp("vocab") / "vocab.tsv"
    words = {"правила": 300, "работы": 300, "средне": 300, "годового": 300, "районах": 500}
    path.write_text("".join("%s\t%d\n" % kv for kv in words.items()), encoding="utf-8")
    return rules.Lexicon(None, str(path))


def found(text, lexicon, rule):
    return [(f["level"], f["fix"]) for f in rules.check(text, lexicon, rules.DocContext()) if f["rule"] == rule]


def test_iz_za_and_iz_pod(lexicon):
    assert found("Это вызвано из за ошибки.", lexicon, "IZ_ZA") == [("error", "из-за")]
    assert found("Достал из под стола.", lexicon, "IZ_ZA") == [("error", "из-под")]
    assert found("Это вызвано из-за ошибки.", lexicon, "IZ_ZA") == []


def test_short_participle_with_one_n(lexicon):
    assert found("Эти угрозы связанны с подменой данных.", lexicon, "PRTS_NN") == [("error", "связаны")]
    assert found("Эти угрозы связаны с подменой данных.", lexicon, "PRTS_NN") == []
    assert found("Это сказано особенно в этом разделе.", lexicon, "PRTS_NN") == []  # an adverb, not a participle


def test_local_network_without_hyphen(lexicon):
    assert found("Для локально-вычислительной сети.", lexicon, "LOCAL_NET") == [("error", "локальной вычислительной")]
    assert found("Локально-вычислительная сеть.", lexicon, "LOCAL_NET") == [("error", "Локальная вычислительная")]


def test_ne_with_bare_participle(lexicon):
    assert found("Это один из не выполненных работ.", lexicon, "NE_JOIN") == [("check", "невыполненных")]
    assert found("Эти заявки не оплаченные поступили позже.", lexicon, "NE_JOIN") == \
        [("check", "неоплаченные")]
    assert found("Меры, не предусмотренные законом, не применяются.", lexicon, "NE_JOIN") == []  # a dependent
    assert found("Список еще не выполненных работ.", lexicon, "NE_JOIN") == []  # an adverb before "не"


def test_glued_words(lexicon):
    assert found("Соблюдайте правилаработы системы.", lexicon, "GLUED_WORDS") == \
        [("check", "правила работы")]
    assert found("Уровень отстает от среднегодового значения.", lexicon, "GLUED_WORDS") == []  # a compound prefix


def test_typo_keeps_the_first_letter_and_one_edit(lexicon):
    assert found("В рйонах области.", lexicon, "TYPO") == [("check", "районах")]
    assert found("В кайонах области.", lexicon, "TYPO") == []  # another first letter: not a slip of the keys


def test_sage_accepts_only_slips_of_the_keys():
    assert sage.typo_like("населени", "населения")
    assert not sage.typo_like("асимметрично", "симметрично")  # a stripped prefix is another word


# --- the fine-tuned SAGE votes on endings of the taggers (train/sage_policy_eval.py, sage-ft-report.md) ---

def check_mark(rule, start, end, fix):
    return {"start": start, "end": end, "level": "check", "rule": rule, "fix": fix, "message": ""}


def test_sage_alone_adds_no_comma_or_ending(lexicon):
    assert sage.findings("Он сказал что дом стоит.", "Он сказал, что дом стоит.", lexicon, seen=[]) == []
    assert sage.findings("Мы видим красивая дом.", "Мы видим красивый дом.", lexicon,
                         seen=[check_mark("MODEL_FORM", 0, 2, "Мы")]) == []   # the tagger marked another place
    assert sage.findings("Мы видим красивая дом.", "Мы видим красивый дом.", lexicon) == []


def test_sage_commas_do_not_vote(lexicon):
    assert sage.findings("Он сказал что дом стоит.", "Он сказал, что дом стоит.", lexicon,
                         seen=[check_mark("MODEL_COMMA", 9, 9, ",")]) == []
    assert sage.findings("Это дом, и сад.", "Это дом и сад.", lexicon, seen=[check_mark("MODEL_COMMA", 7, 8, "")]) == []


def test_sage_confirms_a_tagger_check_ending(lexicon):
    src, out = "Мы видим красивая дом.", "Мы видим красивый дом."
    got = sage.findings(src, out, lexicon, seen=[check_mark("MODEL_FORM", 9, 17, "красивый")])
    assert [(f["rule"], f["level"], f["fix"]) for f in got] == [("SAGE_ENDING", "error", "красивый")]
    assert src[got[0]["start"]:got[0]["end"]] == "красивая"


def test_sage_keeps_joined_spelling_as_before(lexicon):
    got = sage.findings("Кто то пришёл.", "Кто-то пришёл.", lexicon)
    assert [(f["rule"], f["level"]) for f in got] == [("SAGE_JOIN", "error")]
