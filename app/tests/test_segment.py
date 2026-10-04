from zhiraf.segment import split_sentences


def parts(text):
    return [text[s:e] for s, e in split_sentences(text)]


def test_two_sentences():
    assert parts("Первое предложение. Второе предложение.") == ["Первое предложение.", "Второе предложение."]


def test_question_exclamation_and_ellipsis():
    assert parts("Кто виноват? Не мы! Посмотрим… Вот так.") == ["Кто виноват?", "Не мы!", "Посмотрим…", "Вот так."]


def test_abbreviations_do_not_split():
    text = "Приказ от 1 марта 2025 г. Минфина, т. е. ведомства, и т.д. Согласно ст. 5 Закона всё верно."
    assert parts(text) == [text]


def test_initials_do_not_split():
    assert parts("Отчёт подписал А. С. Иванов. Он согласен.") == ["Отчёт подписал А. С. Иванов.", "Он согласен."]


def test_numbered_heading_is_not_a_sentence():
    assert parts("1. Общие положения настоящего регламента.") == ["1. Общие положения настоящего регламента."]
    assert parts("2.1. Термины. Далее текст.") == ["2.1. Термины.", "Далее текст."]


def test_no_split_before_lowercase():
    assert parts("Сумма 5 тыс. руб. уплачена.") == ["Сумма 5 тыс. руб. уплачена."]


def test_closing_quote_stays_with_sentence():
    assert parts("Он сказал: «Готово.» Мы ушли.") == ["Он сказал: «Готово.»", "Мы ушли."]


def test_offsets_skip_surrounding_whitespace():
    text = "  Раз.   Два.  "
    assert split_sentences(text) == [(2, 6), (9, 13)]


def test_text_without_final_period():
    assert parts("Перечень мер защиты информации") == ["Перечень мер защиты информации"]


def test_empty_and_blank():
    assert split_sentences("") == [] and split_sentences("   ") == []
