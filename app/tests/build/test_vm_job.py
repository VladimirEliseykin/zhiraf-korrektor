import json
import os
import py_compile

from build import prune
from build.vm import make_job


def test_forbidden_rules_follow_prune_and_skip_dlls():
    rules = make_job.forbidden_rules()
    assert "ssl" in rules["stdlib"] and "_hashlib" in rules["stdlib"]
    assert not any(name.endswith(".dll") for name in rules["stdlib"])
    assert "PySide2.QtNetwork" in rules["qt"] and "PySide2.QtQml" in rules["qt"]
    assert not any("/" in name or "*" in name or "Qt5" in name for name in rules["qt"])
    # socket stays in the folder (multiprocessing needs it), so it must not be reported as a violation
    assert "socket" not in rules["stdlib"]
    assert len(rules["stdlib"]) == len([n for n in prune.FORBIDDEN_STDLIB if not n.endswith(".dll")])


def test_job_folder_is_complete(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    for name in make_job.SAMPLES:
        (samples / name).write_bytes(b"x")
    job = tmp_path / "job"
    make_job.make_job(str(job), str(samples))
    for name in ("run.cmd", "win_check.py", "forbidden.json", "id.txt"):
        assert (job / name).is_file()
    assert sorted(os.listdir(str(job / "work"))) == sorted(make_job.SAMPLES)
    assert json.loads((job / "forbidden.json").read_text(encoding="utf-8"))["qt"]
    py_compile.compile(str(job / "win_check.py"), doraise=True)


def test_run_cmd_uses_only_ascii_paths():
    text = open(os.path.join(os.path.dirname(make_job.__file__), "run.cmd"), "rb").read()
    text.decode("ascii")
