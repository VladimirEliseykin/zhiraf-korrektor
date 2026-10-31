from zhiraf.documents.model import Document, Paragraph, Span
from zhiraf.review import ReviewSession
from zhiraf.ui.runs import (Run, display_range, final_paragraphs, final_spans, paragraph_runs, to_utf16,
                            utf16_len)


def finding(start, end, fix, level="error", rule="MODEL_FORM"):
    return {"start": start, "end": end, "fix": fix, "level": level, "rule": rule, "message": "m"}


def make(text, *findings):
    session = ReviewSession([text])
    session.add_findings(0, 0, list(findings))
    return session


def test_runs_keep_bold_of_the_replaced_word():
    par = Paragraph([Span("Работа "), Span("с информации", bold=True)])
    session = make(par.text, finding(9, 19, "информацией"))
    session.accept()
    mark = session.marks[0]
    assert final_spans(par, session, 0) == [Span("Работа "), Span("с информацией", bold=True)]
    runs = paragraph_runs(par, session, 0)
    assert Run("информацией", bold=True, mark=(mark.id, "accepted", "error")) in runs
    assert "".join(r.text for r in runs) == "Работа с информацией"


def test_zero_width_mark_is_shown_on_previous_character():
    par = Paragraph([Span("Документ определяющий")])
    session = make(par.text, finding(8, 8, ","))
    mark = session.marks[0]
    assert session.span(mark) == (8, 8)
    assert display_range(session, mark) == (7, 8)
    session.accept()
    assert session.text(0).startswith("Документ, ")
    assert session.span(mark) == (8, 9)
    assert display_range(session, mark) == (8, 9)


def test_zero_width_mark_at_paragraph_start():
    session = make("слово", finding(0, 0, "«"))
    assert display_range(session, session.marks[0]) == (0, 1)


def test_inserted_text_takes_previous_format():
    par = Paragraph([Span("Док", bold=True), Span("умент определяющий")])
    session = make(par.text, finding(8, 8, ","))
    session.accept()
    assert final_spans(par, session, 0) == [Span("Док", bold=True), Span("умент, определяющий")]
    par2 = Paragraph([Span("слово", italic=True)])
    s2 = make("слово", finding(0, 0, "«"))
    s2.accept()
    assert final_spans(par2, s2, 0) == [Span("«слово", italic=True)]


def test_dictionary_status_has_no_mark():
    par = Paragraph([Span("ошбка")])
    session = make("ошбка", finding(0, 5, "ошибка", rule="RULE_TYPO"))
    session.add_to_dictionary()
    assert session.marks[0].status == "dictionary"
    assert paragraph_runs(par, session, 0) == [Run("ошбка")]


def test_skipped_keeps_mark_with_status_skipped():
    par = Paragraph([Span("ошбка")])
    session = make("ошбка", finding(0, 5, "ошибка"))
    mark = session.marks[0]
    session.skip()
    assert paragraph_runs(par, session, 0) == [Run("ошбка", mark=(mark.id, "skipped", "error"))]


def test_show_checks_false_hides_check_marks():
    par = Paragraph([Span("ab cd")])
    session = make("ab cd", finding(0, 2, "x", level="check"), finding(3, 5, "y"))
    runs = paragraph_runs(par, session, 0, show_checks=False)
    assert [r.mark is None for r in runs] == [True, False]
    assert paragraph_runs(par, session, 0)[0].mark is not None


def test_final_paragraphs_keep_style_and_table():
    doc = Document([Paragraph([Span("Заголовок")], style="h1", table=(0, 1, 2), has_image=True)], "docx")
    session = ReviewSession([doc.paragraphs[0].text])
    out = final_paragraphs(doc, session)
    assert (out[0].style, out[0].table, out[0].has_image) == ("h1", (0, 1, 2), True)
    assert out[0].spans == [Span("Заголовок")]


def test_emoji_positions():
    par = Paragraph([Span("Яблоко🍎 сорт")])
    session = make(par.text, finding(8, 12, "сорта"))
    runs = paragraph_runs(par, session, 0)
    assert runs[-1].text == "сорт" and runs[-1].mark is not None


def test_utf16_helpers():
    text = "Яблоко🍎 сорт x"
    assert utf16_len("Яблоко🍎") == 8
    assert to_utf16(text, 6) == 6
    assert to_utf16(text, 7) == 8
    assert to_utf16(text, 8) == 9
    assert to_utf16(text, text.index(" ") + 1) == len(text.encode("utf-16-le")) // 2 - 1
    assert utf16_len(" ") == 1


class _NoScan(list):
    def __iter__(self):
        raise AssertionError("session.marks was scanned")


def test_runs_of_one_paragraph_do_not_scan_all_marks():
    par = Paragraph([Span("Работа с информации")])
    session = make(par.text, finding(9, 19, "информацией"))
    session.accept()
    session.marks = _NoScan(session.marks)   # only the per-paragraph index may be used
    assert "".join(r.text for r in paragraph_runs(par, session, 0)) == "Работа с информацией"
    assert "".join(s.text for s in final_spans(par, session, 0)) == "Работа с информацией"


def test_marks_of_unknown_paragraph_is_empty():
    assert list(ReviewSession(["a"]).marks_of(5)) == []
