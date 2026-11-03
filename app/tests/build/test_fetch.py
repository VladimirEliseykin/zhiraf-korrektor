import hashlib
import os
import re

import pytest

from build import fetch as F

LOCK = os.path.join(os.path.dirname(F.__file__), "deps.lock")

EXPECTED_NAMES = {
    "python-embed", "ucrt", "toolchain",
    "wheel:numpy", "wheel:onnxruntime", "wheel:tokenizers", "wheel:pymorphy3",
    "wheel:DAWG-Python", "wheel:pymorphy3-dicts-ru", "wheel:lxml",
    "wheel:olefile", "wheel:comtypes", "wheel:psutil", "wheel:PySide2",
    "wheel:shiboken2",
}


def _src(tmp_path, data=b"payload"):
    p = tmp_path / "src.bin"
    p.write_bytes(data)
    return "file://" + str(p), hashlib.sha256(data).hexdigest()


def test_read_lock_skips_comments_and_blanks(tmp_path):
    lock = tmp_path / "x.lock"
    lock.write_text("# c\n\na\tfile:///a\t" + "0" * 64 + "\twheel\n   \n# d\n")
    deps = F.read_lock(str(lock))
    assert [d.name for d in deps] == ["a"]
    assert deps[0].kind == "wheel" and deps[0].url == "file:///a"


def test_fetch_stores_file(tmp_path):
    url, sha = _src(tmp_path)
    cache = tmp_path / "cache"
    path = F.fetch(F.Dep("wheel:x", url, sha, "wheel"), str(cache))
    assert os.path.isfile(path) and open(path, "rb").read() == b"payload"
    assert os.path.dirname(path) == str(cache)


def test_second_fetch_does_not_copy_again(tmp_path):
    url, sha = _src(tmp_path)
    dep = F.Dep("wheel:x", url, sha, "wheel")
    path = F.fetch(dep, str(tmp_path / "cache"))
    os.utime(path, (1000, 1000))
    F.fetch(dep, str(tmp_path / "cache"))
    assert os.stat(path).st_mtime == 1000


def test_bad_hash_raises_and_leaves_nothing(tmp_path):
    url, _ = _src(tmp_path)
    cache = tmp_path / "cache"
    with pytest.raises(F.HashMismatch) as e:
        F.fetch(F.Dep("wheel:x", url, "0" * 64, "wheel"), str(cache))
    assert "src.bin" in str(e.value)
    assert os.listdir(str(cache)) == []


def test_corrupt_cache_is_redownloaded(tmp_path):
    url, sha = _src(tmp_path)
    dep = F.Dep("wheel:x", url, sha, "wheel")
    path = F.fetch(dep, str(tmp_path / "cache"))
    with open(path, "wb") as f:
        f.write(b"garbage")
    path2 = F.fetch(dep, str(tmp_path / "cache"))
    assert open(path2, "rb").read() == b"payload"


def test_fetch_all_returns_names(tmp_path):
    url, sha = _src(tmp_path)
    lock = tmp_path / "x.lock"
    lock.write_text("wheel:x\t%s\t%s\twheel\n" % (url, sha))
    res = F.fetch_all(str(lock), str(tmp_path / "cache"))
    assert list(res) == ["wheel:x"] and os.path.isfile(res["wheel:x"])


def test_real_lock_is_well_formed():
    deps = F.read_lock(LOCK)
    assert {d.name for d in deps} == EXPECTED_NAMES
    for d in deps:
        assert re.fullmatch(r"[0-9a-f]{64}", d.sha256), d.name
        assert d.kind in ("python-embed", "wheel", "ucrt", "toolchain")
        assert d.url.startswith("https://"), d.name
    with open(LOCK) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                assert len(line.rstrip("\n").split("\t")) == 4


def test_download_has_a_timeout(tmp_path, monkeypatch):
    import urllib.request
    url, sha = _src(tmp_path)
    seen = {}
    real = urllib.request.urlopen

    def spy(target, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout", args[1] if len(args) > 1 else None)
        return real(target, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    F.fetch(F.Dep("wheel:x", url, sha, "wheel"), str(tmp_path / "cache"))
    assert seen["timeout"] == 60
