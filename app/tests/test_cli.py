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


def test_main_reports_a_crashed_check_without_traceback(tmp_path, models_dir, capsys):
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    code = cli.main(["check", src, "--models", models_dir, "--factories", "fakes:make_broken_factories"])
    err = capsys.readouterr().err
    assert code == 3 and "Проверка прервалась" in err and "Traceback" not in err


@pytest.mark.slow
def test_real_models_fix_an_ending(tmp_path):
    src = make_docx(tmp_path / "a.docx",
                    P(R("Сотрудники, допущенные к работе с информации ограниченного доступа, указаны в документах.")))
    result = cli.check_file(src, real_models_dir(), accept_errors=True)
    assert "с информацией ограниченного" in read_docx(result["saved"]).paragraphs[0].text


def test_missing_models_names_the_first_missing_item(tmp_path):
    from zhiraf import missing_models
    folder = tmp_path / "empty"
    folder.mkdir()
    assert "vocab.tsv" in missing_models(str(folder))
    (folder / "vocab.tsv").write_text("а\t1\n", encoding="utf-8")
    assert "sage" in missing_models(str(folder))
    for name in ("sage", "commas", "forms"):
        (folder / name).mkdir()
    assert missing_models(str(folder)) is None
    assert "Не найдена папка" in missing_models(str(tmp_path / "нет"))


def test_check_file_reports_missing_models(tmp_path):
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(cli.CheckError) as e:
        cli.check_file(src, str(empty))
    assert "vocab.tsv" in str(e.value)


def test_plan_sentences_lives_in_segment():
    from zhiraf import segment
    assert cli.plan_sentences is segment.plan_sentences


def test_crash_message_has_no_technical_words(tmp_path, models_dir):
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    with pytest.raises(cli.CheckError) as e:
        cli.check_file(src, models_dir, factories="fakes:make_broken_factories")
    assert str(e.value) == "Проверка прервалась из-за внутренней ошибки."


def test_a_failing_recent_list_does_not_lose_the_result(tmp_path, models_dir, monkeypatch):
    def broken(self, *a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(storage.Recent, "touch", broken)
    src = make_docx(tmp_path / "a.docx", P(R("Так же был.")))
    result = cli.check_file(src, models_dir, accept_errors=True, factories="fakes:make_factories")
    assert os.path.exists(result["saved"])


def test_progress_line_has_no_tail_when_almost_done(capsys):
    class Almost:
        def remaining_seconds(self):
            return 0.0

        def fraction(self):
            return 0.99
    cli._progress_line(Almost())
    assert "осталось" not in capsys.readouterr().err
