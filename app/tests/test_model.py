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


def test_txt_utf16_round_trip_keeps_encoding(tmp_path):
    src = tmp_path / "utf16.txt"
    src.write_bytes("Текст на русском".encode("utf-16"))
    doc = opener.open_document(str(src))
    report = opener.save_document(doc, [])
    assert open(report.path, "rb").read() == "Текст на русском".encode("utf-16")


def test_bom_file_with_invalid_utf8_raises_error(tmp_path):
    src = tmp_path / "invalid.txt"
    # UTF-8 BOM followed by invalid UTF-8 bytes
    src.write_bytes(b"\xef\xbb\xbf\xff\xfe")
    with pytest.raises(DocumentError) as exc_info:
        opener.open_document(str(src))
    assert "неизвестная кодировка" in str(exc_info.value)


def test_replacement_with_char_not_in_cp1251_raises_error(tmp_path):
    src = tmp_path / "cp1251.txt"
    src.write_bytes("Простой текст".encode("cp1251"))
    doc = opener.open_document(str(src))
    # Arrow character (→) is not in CP1251
    with pytest.raises(DocumentError) as exc_info:
        opener.save_document(doc, [Replacement(0, 0, 0, "→")])
    assert "нельзя сохранить" in str(exc_info.value)
    # Verify no output file or .part file remains
    report_name = os.path.basename(str(tmp_path / "cp1251 (исправлено).txt"))
    assert not (tmp_path / report_name).exists()
    assert not (tmp_path / (report_name + ".part")).exists()


def test_opening_directory_as_txt_raises_error(tmp_path):
    dir_path = tmp_path / "x.txt"
    dir_path.mkdir()
    with pytest.raises(DocumentError):
        opener.open_document(str(dir_path))


def _txt(tmp_path, name="a.txt"):
    path = tmp_path / name
    path.write_text("Так же был\n", encoding="utf-8")
    return str(path)


def test_reader_failure_becomes_a_document_error(tmp_path, monkeypatch):
    def broken(path):
        raise RuntimeError("secret paragraph text")
    monkeypatch.setitem(opener.READERS, ".txt", broken)
    with pytest.raises(DocumentError) as e:
        opener.open_document(_txt(tmp_path))
    assert str(e.value) == "Не удалось открыть «a.txt»: файл повреждён."


def test_reader_out_of_memory_becomes_a_document_error(tmp_path, monkeypatch):
    def huge(path):
        raise MemoryError()
    monkeypatch.setitem(opener.READERS, ".txt", huge)
    with pytest.raises(DocumentError) as e:
        opener.open_document(_txt(tmp_path))
    assert str(e.value) == "Не хватило памяти, чтобы открыть «a.txt»."


def test_save_without_any_destination_is_a_document_error(tmp_path):
    doc = opener.open_document(_txt(tmp_path))
    doc.path = None
    with pytest.raises(DocumentError) as e:
        opener.save_document(doc, [])
    assert str(e.value) == "Укажите, куда сохранить документ."


def test_save_of_an_unknown_kind_is_a_document_error(tmp_path):
    doc = opener.open_document(_txt(tmp_path))
    doc.kind = "rtf"
    with pytest.raises(DocumentError):
        opener.save_document(doc, [])


def test_saver_failures_become_document_errors(tmp_path, monkeypatch):
    doc = opener.open_document(_txt(tmp_path))

    def memory(*a):
        raise MemoryError()

    def other(*a):
        raise ValueError("secret")
    monkeypatch.setitem(opener.SAVERS, "txt", memory)
    with pytest.raises(DocumentError) as e:
        opener.save_document(doc, [], str(tmp_path / "out.txt"))
    assert str(e.value) == "Не хватило памяти, чтобы сохранить «out.txt»."
    monkeypatch.setitem(opener.SAVERS, "txt", other)
    with pytest.raises(DocumentError) as e:
        opener.save_document(doc, [], str(tmp_path / "out.txt"))
    assert str(e.value) == "Не удалось сохранить «out.txt»." and "secret" not in str(e.value)


def test_txt_part_file_is_removed_on_any_failure(tmp_path, monkeypatch):
    doc = opener.open_document(_txt(tmp_path))

    def broken(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", broken)
    out = str(tmp_path / "out.txt")
    with pytest.raises(OSError):
        opener.SAVERS["txt"](doc, [], out)
    assert not os.path.exists(out + ".part") and not os.path.exists(out)
