import os

import pytest

from zhiraf.documents import opener
from zhiraf.documents.model import (DocumentError, Paragraph, Replacement, Span, UnsupportedFormat,
                                    apply_replacements, corrected_path)


def test_paragraph_text_joins_spans():
    assert Paragraph([Span("Важный ", bold=True), Span("текст")]).text == "Важный текст"


def test_apply_replacements_in_any_order():
    reps = [Replacement(0, 9, 9, ","), Replacement(0, 0, 4, "Этот")]
    assert apply_replacements("Тест речь пример", reps) == "Этот речь, пример"


def test_apply_replacement_deletes_with_empty_text():
    assert apply_replacements("Однако, всё", [Replacement(0, 6, 7, "")]) == "Однако всё"


def test_corrected_path_never_collides(tmp_path):
    src = str(tmp_path / "Приказ.docx")
    first = corrected_path(src)
    assert os.path.basename(first) == "Приказ (исправлено).docx"
    open(first, "w").close()
    assert os.path.basename(corrected_path(src)) == "Приказ (исправлено 2).docx"
    assert os.path.basename(corrected_path(src, "doc")) == "Приказ (исправлено).doc"


def test_txt_round_trip_keeps_encoding_and_newlines(tmp_path):
    src = tmp_path / "заметка.txt"
    src.write_bytes("Так же был ограничен.\r\nВторая строка.".encode("cp1251"))
    doc = opener.open_document(str(src))
    assert [p.text for p in doc.paragraphs] == ["Так же был ограничен.", "Вторая строка."]
    report = opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert report.applied == 1
    assert open(report.path, "rb").read() == "Также был ограничен.\r\nВторая строка.".encode("cp1251")


def test_txt_utf8_with_bom_keeps_bom(tmp_path):
    src = tmp_path / "a.txt"
    src.write_bytes("﻿Текст".encode("utf-8"))
    doc = opener.open_document(str(src))
    report = opener.save_document(doc, [])
    assert open(report.path, "rb").read() == "﻿Текст".encode("utf-8")


def test_original_is_never_overwritten(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("Текст", encoding="utf-8")
    doc = opener.open_document(str(src))
    with pytest.raises(DocumentError):
        opener.save_document(doc, [], dst=str(src))


def test_unsupported_and_missing_files(tmp_path):
    with pytest.raises(UnsupportedFormat):
        opener.open_document(str(tmp_path / "картинка.png"))
    with pytest.raises(DocumentError):
        opener.open_document(str(tmp_path / "нет.txt"))
