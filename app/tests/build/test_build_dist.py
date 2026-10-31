import io
import os
import tarfile
import zipfile

import pytest

from build import build_dist


def _zip(path, members):
    with zipfile.ZipFile(str(path), "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return str(path)


@pytest.fixture
def world(tmp_path, monkeypatch):
    files = {
        "python-embed": _zip(tmp_path / "embed.zip", {
            "python.exe": b"py", "pythonw.exe": b"pyw", "python37.dll": b"dll",
            "python37.zip": b"", "python37._pth": b"x"}),
        "wheel:shiboken2": _zip(tmp_path / "sb.whl", {
            "shiboken2/msvcp140.dll": b"a", "shiboken2/vcruntime140.dll": b"b",
            "shiboken2/vcruntime140_1.dll": b"c"}),
        "toolchain": str(tmp_path / "unused.tar.xz"),
    }
    # a real (empty) stdlib zip so prune can open it
    with zipfile.ZipFile(str(tmp_path / "std.zip"), "w") as z:
        z.writestr("json/__init__.py", b"")
    files["python-embed"] = _zip(tmp_path / "embed.zip", {
        "python.exe": b"py", "pythonw.exe": b"pyw", "python37.dll": b"dll",
        "python37.zip": open(str(tmp_path / "std.zip"), "rb").read(), "python37._pth": b"x"})
    tar_path = tmp_path / "ucrt.tar.bz2"
    with tarfile.open(str(tar_path), "w:bz2") as t:
        for name in ("Library/bin/ucrtbase.dll", "Library/bin/api-ms-win-crt-runtime-l1-1-0.dll"):
            ti = tarfile.TarInfo(name)
            ti.size = 1
            t.addfile(ti, io.BytesIO(b"u"))
    files["ucrt"] = str(tar_path)

    repo = tmp_path / "repo"
    (repo / "app" / "zhiraf" / "ui" / "art").mkdir(parents=True)
    (repo / "app" / "zhiraf" / "__init__.py").write_text("x")
    (repo / "app" / "zhiraf" / "ui" / "art" / "logo.png").write_bytes(b"png")
    (repo / "engine" / "spellcheck").mkdir(parents=True)
    (repo / "engine" / "spellcheck" / "core.py").write_text("import os\n")
    (repo / "engine" / "art").mkdir()
    (repo / "engine" / "art" / "start.jpg").write_bytes(b"jpg")
    models = tmp_path / "models"
    models.mkdir()
    (models / "vocab.tsv").write_text("a\n")

    monkeypatch.setattr(build_dist, "fetch_all", lambda lock_path=None, cache_dir=None: files)
    monkeypatch.setattr(build_dist, "toolchain_dir", lambda f, cache: str(tmp_path / "tc"))
    monkeypatch.setattr(build_dist, "make_icon", lambda png, ico: open(ico, "wb").write(b"ico"))

    def fake_launcher(tc, out_exe, ico):
        assert os.path.isfile(ico)
        with open(out_exe, "wb") as f:
            f.write(b"MZ")
    monkeypatch.setattr(build_dist, "make_launcher", fake_launcher)

    out = tmp_path / "out"
    args = ["--out", str(out), "--cache", str(tmp_path / "cache"), "--models", str(models),
            "--repo", str(repo)]
    return args, out


def test_successful_build(world, capsys):
    args, out = world
    assert build_dist.main(args) == 0
    dist = out / "Жираф.Корректор"
    assert (dist / "Жираф.Корректор.exe").read_bytes() == b"MZ"
    assert (dist / "models" / "vocab.tsv").is_file()
    assert not (out / "Жираф.Корректор.tmp").exists()
    text = capsys.readouterr().out
    assert "файлов" in text


def test_check_violation_fails_and_cleans_up(world, monkeypatch, capsys):
    args, out = world
    monkeypatch.setattr(build_dist, "check", lambda d: ["forbidden file: python/_ssl.pyd"])
    assert build_dist.main(args) == 1
    assert not (out / "Жираф.Корректор").exists()
    assert not (out / "Жираф.Корректор.tmp").exists()
    assert "_ssl.pyd" in capsys.readouterr().out


def test_exception_fails_and_cleans_up(world, monkeypatch, capsys):
    args, out = world

    def boom(*a):
        raise RuntimeError("no compiler")
    monkeypatch.setattr(build_dist, "make_launcher", boom)
    assert build_dist.main(args) == 1
    assert not (out / "Жираф.Корректор.tmp").exists()
    assert "no compiler" in capsys.readouterr().out


def test_existing_folder_is_refused_and_kept(world, capsys):
    args, out = world
    (out / "Жираф.Корректор").mkdir(parents=True)
    (out / "Жираф.Корректор" / "keep.txt").write_text("k")
    assert build_dist.main(args) == 1
    assert "уже есть, удалите её" in capsys.readouterr().out
    assert (out / "Жираф.Корректор" / "keep.txt").is_file()
