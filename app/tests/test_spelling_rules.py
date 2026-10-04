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
