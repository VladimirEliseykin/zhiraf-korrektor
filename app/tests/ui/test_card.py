from PySide2.QtCore import QPoint, QRect, QSize, Qt
from PySide2.QtTest import QTest

from zhiraf.review import ReviewSession
from zhiraf.ui.card import MarkCard, card_position


def make_mark(rule="RULE_TYPO", level="error", fix="информацией", start=0, end=11, text="информацыей"):
    session = ReviewSession([text])
    finding = {"start": start, "end": end, "level": level, "rule": rule, "fix": fix, "message": "Проверьте написание"}
    return session.add_findings(0, 0, [finding])[0]


def test_card_position_below_when_it_fits():
    p = card_position(QRect(0, 0, 800, 600), QRect(100, 100, 60, 20), QSize(700, 90))
    assert p.y() == 100 + 20 + 8 and 12 <= p.x() and p.x() + 700 <= 800 - 12


def test_card_position_above_near_bottom():
    p = card_position(QRect(0, 0, 800, 600), QRect(100, 560, 60, 20), QSize(700, 90))
    assert p.y() + 90 <= 560 - 8


def test_card_shows_error_with_fix(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show_mark(make_mark(), "по ", " дальше")
    assert card.level_label.text() == "Ошибка"
    assert "<s>" in card.fix_label.text() and "<b>" in card.fix_label.text()
    assert card.accept_button.isEnabled() and card.accept_button.text() == "Принять (Enter)"


def test_card_insertion_text(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show_mark(make_mark(rule="RULE_COMMA", fix=",", start=3, end=3, text="так что"), "", "")
    assert "нет запятой" in card.fix_label.text() and "<b>,</b>" in card.fix_label.text()


def test_card_check_without_fix_disables_accept(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show_mark(make_mark(level="check", fix=None), "", "")
    assert card.level_label.text() == "Проверьте"
    assert not card.accept_button.isEnabled()


def test_dictionary_button_only_for_spelling_marks(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show_mark(make_mark(rule="MODEL_FORM"), "", "")
    assert card.dictionary_button.isHidden()
    card.show_mark(make_mark(rule="RULE_TYPO"), "", "")
    assert not card.dictionary_button.isHidden()


def test_manual_edit_prefilled_with_original(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show()
    assert card.manual_edit.isHidden()
    card.show_mark(make_mark(), "", "")
    card.manual_button.click()
    assert not card.manual_edit.isHidden() and card.manual_edit.text() == "информацыей"


def test_manual_edit_enter_emits_text(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show()
    card.show_mark(make_mark(), "", "")
    card.manual_button.click()
    card.manual_edit.setText("информацией")
    with qtbot.waitSignal(card.manual_submitted) as sig:
        QTest.keyClick(card.manual_edit, Qt.Key_Return)
    assert sig.args == ["информацией"]


def test_manual_edit_escape_closes_field(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show()
    card.show_mark(make_mark(), "", "")
    card.manual_button.click()
    QTest.keyClick(card.manual_edit, Qt.Key_Escape)
    assert card.manual_edit.isHidden()


def test_buttons_emit_signals(qtbot):
    card = MarkCard()
    qtbot.addWidget(card)
    card.show_mark(make_mark(), "", "")
    with qtbot.waitSignal(card.accept_clicked):
        card.accept_button.click()
    with qtbot.waitSignal(card.skip_clicked):
        card.skip_button.click()
    with qtbot.waitSignal(card.dictionary_clicked):
        card.dictionary_button.click()
