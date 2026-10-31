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


def test_initials_without_spaces_do_not_split():
    assert parts("Отчёт подписал А.С. Иванов. Он согласен.") == ["Отчёт подписал А.С. Иванов.", "Он согласен."]


def test_multiple_initials_do_not_split():
    assert parts("Директор И.И. Петров утвердил план.") == ["Директор И.И. Петров утвердил план."]


def test_abbreviation_with_nds_split():
    assert parts("В т.ч. НДС уплачен. Далее.") == ["В т.ч. НДС уплачен.", "Далее."]


def test_sentence_kinds_follow_the_paragraph_role():
    from zhiraf.documents.model import Paragraph, Span
    from zhiraf.segment import plan_sentences, sentence_kinds
    paragraphs = [Paragraph([Span("Один. Два.")]), Paragraph([Span("Раздел")], style="h1"),
                  Paragraph([Span("ячейка")], table=(0, 1, 1)), Paragraph([Span("пункт")], style="list")]
    sentences, where = plan_sentences([p.text for p in paragraphs])
    assert sentence_kinds(paragraphs, where) == ["body", "body", "heading", "table", "list"]
    titled = [Paragraph([Span("Название")], style="title"), Paragraph([Span("Подраздел")], style="h3"),
              Paragraph([Span("в таблице")], style="h2", table=(0, 0, 0))]
    _, where = plan_sentences([p.text for p in titled])
    assert sentence_kinds(titled, where) == ["heading", "heading", "table"]
