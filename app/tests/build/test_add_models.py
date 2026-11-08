import os

import pytest

from build import add_models, check_dist, layout

PY = "python"


def put(base, rel, data=b"x"):
    path = os.path.join(str(base), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture
def world(tmp_path):
    """A folder as built with --no-models, and a small fake models dir."""
    dist = tmp_path / "dist"
    for n in layout.REQUIRED_DLLS:
        put(dist, os.path.join(PY, n))
    for rel in ("python/pythonw.exe", "Жираф.Корректор.exe", "engine/art/start.jpg", "app/zhiraf/ui/art/logo.png",
                "python/qt.conf", "python/python37._pth", "ИНСТРУКЦИЯ.txt", "models/" + layout.MODELS_PLACEHOLDER):
        put(dist, rel)
    models = tmp_path / "src-models"
    put(models, "sage/encoder_model.onnx", b"e" * 100)
    put(models, "sage/encoder_model.onnx.data", b"d" * 100)
    put(models, "commas/model.onnx", b"m" * 10)
    put(models, "commas/vocab.txt", b"v")
    put(models, "vocab.tsv", b"a\n")
    put(models, "stray-file.txt", b"s")
    return str(dist), str(models)


def test_copies_models_and_removes_the_placeholder(world, capsys):
    dist, models = world
    assert add_models.main([dist, models]) == 0
    m = os.path.join(dist, "models")
    assert sorted(os.listdir(m)) == ["commas", "sage", "vocab.tsv"]
    assert open(os.path.join(m, "sage", "encoder_model.onnx.data"), "rb").read() == b"d" * 100
    assert open(os.path.join(m, "commas", "vocab.txt"), "rb").read() == b"v"
    assert check_dist.check(dist, models) == []
    assert not os.path.exists(os.path.join(m, layout.MODELS_PLACEHOLDER))
    assert "готово" in capsys.readouterr().out


def test_files_are_real_copies_not_links(world):
    dist, models = world
    assert add_models.main([dist, models]) == 0
    src = os.stat(os.path.join(models, "vocab.tsv"))
    dst = os.stat(os.path.join(dist, "models", "vocab.tsv"))
    assert (src.st_dev, src.st_ino) != (dst.st_dev, dst.st_ino)
    assert dst.st_nlink == 1


def test_no_part_files_remain(world):
    dist, models = world
    assert add_models.main([dist, models]) == 0
    for _root, _dirs, names in os.walk(dist):
        assert not [n for n in names if n.endswith(".part")]


def test_interrupted_copy_leaves_no_half_file_under_the_final_name(world, monkeypatch):
    dist, models = world
    real = add_models.shutil.copyfileobj

    def boom(src, dst, *a, **k):
        dst.write(b"half")
        raise OSError("disk full")
    monkeypatch.setattr(add_models.shutil, "copyfileobj", boom)
    assert add_models.main([dist, models]) == 1
    monkeypatch.setattr(add_models.shutil, "copyfileobj", real)
    assert not os.path.exists(os.path.join(dist, "models", "sage", "encoder_model.onnx"))
    assert not os.path.exists(os.path.join(dist, "models", "vocab.tsv"))
    # a repeated run recovers
    assert add_models.main([dist, models]) == 0
    assert check_dist.check(dist, models) == []


def test_violation_exits_1_and_lists_it(world, capsys):
    dist, models = world
    put(dist, "python/_ssl.pyd")
    assert add_models.main([dist, models]) == 1
    assert "_ssl.pyd" in capsys.readouterr().out


def test_empty_model_file_in_the_source_is_a_violation(world, capsys):
    dist, models = world
    open(os.path.join(models, "commas", "model.onnx"), "wb").close()
    assert add_models.main([dist, models]) == 1
    assert "commas" in capsys.readouterr().out


def test_bad_arguments(world, tmp_path, capsys):
    dist, models = world
    assert add_models.main([dist]) == 2
    assert add_models.main([dist, str(tmp_path / "nope")]) == 1
    assert add_models.main([str(tmp_path / "nope"), models]) == 1


def test_models_dir_without_vocab_is_refused(world, tmp_path):
    dist, models = world
    os.remove(os.path.join(models, "vocab.tsv"))
    assert add_models.main([dist, models]) == 1
