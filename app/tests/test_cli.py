import os

import pytest
from docfactory import P, R, make_docx
from zhiraf import cli, models_dir as real_models_dir, storage
from zhiraf.documents.docx_format import read_docx


def test_plan_sentences_maps_back_to_paragraphs():
    sentences, where = cli.plan_sentences(["Раз. Два.", "", "Три"])
    assert sentences == ["Раз.", "Два.", "Три"] and where == [(0, 0), (0, 5), (2, 0)]


def test_check_file_accepts_errors_and_saves_copy(tmp_path, models_dir):
    src = make_docx(tmp_path / "Приказ.docx", P(R("Так же был ограничен размер.", bold=True)),
                    P(R("Документ определяющий порядок утверждён.")), P(R("Работа с информации ведётся.")))
    result = cli.check_file(src, models_dir, accept_errors=True, factories="fakes:make_factories")
    assert result["saved"].endswith("Приказ (исправлено).docx") and result["not_applied"] == 0
    out = read_docx(result["saved"])
    assert [p.text for p in out.paragraphs] == ["Также был ограничен размер.",
                                                "Документ, определяющий порядок утверждён.",
                                                "Работа с информацией ведётся."]
    assert out.paragraphs[0].spans[0].bold is True
    assert result["counts"]["fixed"] == 3
    recent = storage.Recent(storage.Settings()).items()
    assert recent[0]["path"] == os.path.abspath(src) and recent[0]["stats"]["fixed"] == 3


def test_without_accepting_the_copy_is_unchanged(tmp_path, models_dir):
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    result = cli.check_file(src, models_dir, factories="fakes:make_factories")
    assert read_docx(result["saved"]).paragraphs[0].text == "Так же был."
    assert result["counts"]["errors"] == 1


def test_main_prints_summary(tmp_path, models_dir, capsys):
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    code = cli.main(["check", src, "--accept-errors", "--models", models_dir, "--factories", "fakes:make_factories"])
    assert code == 0 and "Исправлено: 1" in capsys.readouterr().out


def test_main_reports_document_errors(tmp_path, models_dir, capsys):
    code = cli.main(["check", str(tmp_path / "нет.docx"), "--models", models_dir])
    assert code == 2 and "Файл не найден" in capsys.readouterr().err


@pytest.mark.slow
def test_real_models_fix_an_ending(tmp_path):
    src = make_docx(tmp_path / "a.docx",
                    P(R("Сотрудники, допущенные к работе с информации ограниченного доступа, указаны в документах.")))
    result = cli.check_file(src, real_models_dir(), accept_errors=True)
    assert "с информацией ограниченного" in read_docx(result["saved"]).paragraphs[0].text
