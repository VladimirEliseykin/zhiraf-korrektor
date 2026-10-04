from zhiraf.review import ACCEPTED, DICTIONARY, MANUAL, OPEN, SKIPPED, ReviewSession
from zhiraf.storage import Dictionary

TEXT = "Так же сотрудники с информации работают"


def f(start, end, fix, level="error", rule="MODEL_FORM", message="m"):
    return {"start": start, "end": end, "fix": fix, "level": level, "rule": rule, "message": message}


def session(text=TEXT, dictionary=None):
    s = ReviewSession([text, "Второй абзац текста"], dictionary)
    s.add_findings(0, 0, [f(0, 6, "Также", rule="RULE_TAKZHE"), f(17, 17, ",", rule="MODEL_COMMA"),
                          f(20, 30, "информацией")])
    return s


def test_marks_are_ordered_and_first_is_current():
    s = session()
    assert [(m.start, m.end) for m in s.marks] == [(0, 6), (17, 17), (20, 30)]
    assert s.current is s.marks[0] and s.marks[0].original == "Так же"


def test_accept_moves_on_and_shifts_later_marks():
    s = session()
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(0, 6, "Также")]
    assert s.current is s.marks[1]
    assert s.span(s.marks[1]) == (16, 16)
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(16, 16, ",")]
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(20, 30, "информацией")]
    assert s.text(0) == "Также сотрудники, с информацией работают"
    assert s.current is None and s.counts()["fixed"] == 3


def test_skip_marks_and_counts():
    s = session()
    s.skip()
    assert s.marks[0].status == SKIPPED and s.current is s.marks[1]
    c = s.counts()
    assert (c["errors"], c["skipped"], c["total"]) == (2, 1, 3)


def test_manual_fix_and_replacements_in_original_coordinates():
    s = session()
    s.go_next()
    s.go_next()
    s.manual("сведениями")
    assert s.marks[2].status == MANUAL and s.text(0) == "Так же сотрудники с сведениями работают"
    assert [(r.paragraph, r.start, r.end, r.text) for r in s.replacements()] == [(0, 20, 30, "сведениями")]


def test_undo_reverts_text_and_status():
    s = session()
    s.accept()
    s.accept()
    edits = s.undo()
    assert [(e.start, e.end, e.text) for e in edits] == [(16, 17, "")]
    assert s.marks[1].status == OPEN and s.current is s.marks[1]
    assert s.text(0) == "Также сотрудники с информации работают"


def test_accept_all_errors_is_one_undo_step():
    s = session()
    s.add_findings(1, 0, [f(0, 6, "Вторый", level="check")])
    edits = s.accept_all_errors()
    assert len(edits) == 3 and s.text(0) == "Также сотрудники, с информацией работают"
    assert s.counts()["checks"] == 1 and s.current is s.marks[3]
    s.undo()
    assert s.text(0) == TEXT and s.counts()["errors"] == 3


def test_navigation_wraps_and_skips_handled():
    s = session()
    s.go_next()
    s.skip()
    assert s.current.start == 20
    assert s.go_next().start == 0      # wraps to the first still open
    assert s.go_prev().start == 20


def test_add_to_dictionary_resolves_same_word_everywhere(tmp_path):
    d = Dictionary(str(tmp_path / "d.txt"))
    s = ReviewSession(["Слово ИСПДн и опять ИСПДн тут"], d)
    s.add_findings(0, 0, [f(6, 11, None, level="check", rule="RULE_TYPO"), f(20, 25, None, level="check", rule="RULE_TYPO")])
    assert s.add_to_dictionary() == "ИСПДн"
    assert "испдн" in d and [m.status for m in s.marks] == [DICTIONARY, DICTIONARY]


def test_dictionary_words_are_not_marked(tmp_path):
    d = Dictionary(str(tmp_path / "d.txt"))
    d.add("ИСПДн")
    s = ReviewSession(["Система ИСПДн работает"], d)
    assert s.add_findings(0, 0, [f(8, 13, None, level="check", rule="RULE_TYPO")]) == []


def test_comma_marks_cannot_go_to_dictionary():
    s = session()
    s.go_next()
    assert s.current.rule == "MODEL_COMMA" and s.add_to_dictionary() is None


def test_late_finding_on_a_handled_place_is_dropped():
    s = session()
    s.accept()                                    # "Так же" -> "Также"
    s.skip()                                      # the comma
    late = s.add_findings(0, 0, [f(0, 3, "Как", rule="SAGE_TYPO"), f(17, 17, ",", rule="MODEL_COMMA")])
    assert late == [] and len(s.marks) == 3


def test_better_finding_replaces_open_one_in_the_same_place():
    s = ReviewSession(["с информации работают"])
    s.add_findings(0, 0, [f(2, 12, "информацией", level="check")])
    s.add_findings(0, 0, [f(2, 12, "информацией", level="error", rule="SAGE_TYPO")])
    assert [(m.level, m.rule) for m in s.marks] == [("error", "SAGE_TYPO")] and s.current is s.marks[0]


def test_offsets_of_a_later_sentence():
    s = ReviewSession(["Первое предложение. Так же второе."])
    s.add_findings(0, 20, [f(0, 6, "Также", rule="RULE_TAKZHE")])
    assert s.marks[0].original == "Так же"


def test_replace_paragraph_forgets_its_marks():
    s = session()
    s.accept()
    s.replace_paragraph(0, "Совсем новый текст")
    assert s.marks == [] and s.current is None and s.text(0) == "Совсем новый текст"
    assert s.undo() == []


def test_manual_with_the_original_text_is_a_skip():
    s = session()
    s.go_next()
    s.go_next()
    assert s.manual("информации") == []
    assert s.marks[2].status == SKIPPED and s.replacements() == [] and s.text(0) == TEXT


def test_undo_of_add_to_dictionary_removes_the_word(tmp_path):
    d = Dictionary(str(tmp_path / "d.txt"))
    s = ReviewSession(["Слово ИСПДн и опять ИСПДн тут"], d)
    s.add_findings(0, 0, [f(6, 11, None, level="check", rule="RULE_TYPO"), f(20, 25, None, level="check", rule="RULE_TYPO")])
    s.add_to_dictionary()
    assert s.undo() == []
    assert "испдн" not in d and [m.status for m in s.marks] == [OPEN, OPEN]


def test_findings_of_an_old_paragraph_version_are_dropped():
    s = ReviewSession(["Так же"])
    assert s.version(0) == 0
    s.replace_paragraph(0, "Так же тут")
    assert s.version(0) == 1
    assert s.add_findings(0, 0, [f(0, 6, "Также")], version=0) == [] and s.marks == []
    assert len(s.add_findings(0, 0, [f(0, 6, "Также")], version=1)) == 1


def test_many_marks_are_handled_fast():
    import time
    s = ReviewSession(["0123456789" * 3] * 300)
    for p in range(300):
        s.add_findings(p, 0, [f(i * 3, i * 3 + 2, "xyz") for i in range(10)])
    assert len(s.marks) == 3000
    t = time.monotonic()
    assert len(s.accept_all_errors()) == 3000
    assert time.monotonic() - t < 1
    t = time.monotonic()
    assert len(s.undo()) == 3000
    assert time.monotonic() - t < 1
    assert s.counts()["errors"] == 3000
