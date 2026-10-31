import json
import os
import subprocess
import sys
import time

import pytest

from docfactory import P, R, make_docx

APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEAVY = ["onnxruntime", "tokenizers", "spellcheck.checker", "spellcheck.sage", "torch"]
FIRST = "Работа с информации ведётся."
SECOND = "Документ определяющий порядок утверждён."

LIGHT_SCRIPT = r'''
import json, os, sys
sys.path.insert(0, %(tests)r)
from PySide2.QtWidgets import QApplication
app = QApplication([])
from zhiraf.ui.main_window import MainWindow
HEAVY = %(heavy)r
def loaded(names):
    return sorted(n for n in names if n in sys.modules)
w = MainWindow(%(models)r, factories="fakes:make_factories")
w.show()
out = {"created": loaded(HEAVY), "qt": loaded(["PySide2.QtNetwork", "PySide2.QtWebEngineWidgets", "PySide2.QtQml"])}
w.open_path(%(doc)r)
import time
end = time.time() + 90
while time.time() < end and not (w.controller is not None and w.controller.state == "done"):
    app.processEvents(); time.sleep(0.02)
out["state"] = w.controller.state if w.controller else None
out["checked"] = loaded(HEAVY)
out["qt_after"] = loaded(["PySide2.QtNetwork", "PySide2.QtWebEngineWidgets", "PySide2.QtQml"])
w.close()
print("RESULT" + json.dumps(out))
'''


def env_for(tmp_path, **extra):
    env = dict(os.environ)
    env.update({"QT_QPA_PLATFORM": "offscreen", "ZHIRAF_HOME": str(tmp_path / "home"),
                "GLIBC_TUNABLES": "glibc.rtld.execstack=2",
                "PYTHONPATH": os.pathsep.join([APP_DIR, os.path.join(APP_DIR, "tests")])})
    env.update(extra)
    return env


def run_window_script(tmp_path, models):
    doc = make_docx(tmp_path / "a.docx", P(R(FIRST)), P(R(SECOND)))
    script = LIGHT_SCRIPT % {"tests": os.path.join(APP_DIR, "tests"), "heavy": HEAVY, "models": str(models),
                             "doc": str(doc)}
    done = subprocess.run([sys.executable, "-c", script], env=env_for(tmp_path), cwd=APP_DIR, timeout=180,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert done.returncode == 0, done.stderr
    line = next(l for l in done.stdout.splitlines() if l.startswith("RESULT"))
    return json.loads(line[len("RESULT"):])


@pytest.fixture(scope="module")
def window_result(tmp_path_factory, request):
    tmp = tmp_path_factory.mktemp("guard")
    folder = tmp / "models"
    folder.mkdir()
    (folder / "vocab.tsv").write_text("информация\t10\nдокумент\t10\n", encoding="utf-8")
    for name in ("sage", "commas", "forms", "spell"):
        (folder / name).mkdir()
    return run_window_script(tmp, folder)


def test_window_process_stays_light(window_result):
    assert window_result["created"] == []
    assert window_result["state"] == "done"
    assert window_result["checked"] == []


def test_no_network_qt_modules_loaded(window_result):
    assert window_result["qt"] == [] and window_result["qt_after"] == []


def test_second_launch_is_refused(tmp_path):
    env = env_for(tmp_path, ZHIRAF_TEST_NO_DIALOG="1")
    first = subprocess.Popen([sys.executable, "-m", "zhiraf.ui"], env=env, cwd=APP_DIR,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        lock = tmp_path / "home" / "запущено.lock"
        end = time.time() + 60
        while time.time() < end and not lock.exists():
            assert first.poll() is None, first.stderr.read()
            time.sleep(0.1)
        assert lock.exists()
        started = time.time()
        second = subprocess.run([sys.executable, "-m", "zhiraf.ui"], env=env, cwd=APP_DIR, timeout=30,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        assert second.returncode == 0 and time.time() - started < 15
        assert "Жираф.Корректор уже открыт" in second.stderr
        assert first.poll() is None   # the first copy keeps running
    finally:
        first.terminate()
        try:
            first.wait(10)
        except subprocess.TimeoutExpired:
            first.kill()
            first.wait()


CRASH_SCRIPT = r'''
import sys, time
from PySide2.QtWidgets import QApplication
app = QApplication([])
from zhiraf.ui.app import log_error_detail
from zhiraf.ui.main_window import MainWindow
w = MainWindow(%(models)r, factories="fakes:make_crashing_factories", log_detail=log_error_detail)
w.show()
w.open_path(%(doc)r)
end = time.time() + 90
while time.time() < end and not (w.controller is not None and w.controller.state == "failed"):
    app.processEvents(); time.sleep(0.02)
print("STATE", w.controller.state if w.controller else None)
w.close()
'''


def test_no_document_text_in_log_after_crash(tmp_path):
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "vocab.tsv").write_text("информация\t10\nдокумент\t10\n", encoding="utf-8")
    for name in ("sage", "commas", "forms", "spell"):
        (folder / name).mkdir()
    doc = make_docx(tmp_path / "a.docx", P(R(FIRST)), P(R(SECOND)))
    script = CRASH_SCRIPT % {"models": str(folder), "doc": str(doc)}
    done = subprocess.run([sys.executable, "-c", script], env=env_for(tmp_path), cwd=APP_DIR, timeout=180,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    assert done.returncode == 0, done.stderr
    assert "STATE failed" in done.stdout
    log = tmp_path / "home" / "журнал.txt"
    assert log.exists()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1 and " · " in lines[-1]   # a new line, so the check below is not vacuous
    everything = log.read_text(encoding="utf-8") + done.stdout + done.stderr
    for word in [w for w in (FIRST + " " + SECOND).replace(".", "").split() if len(w) > 3]:
        assert word not in everything, word


ENTRY_SCRIPT = r'''
import runpy, sys
import zhiraf.ui.app as app
calls = []
app.main = lambda argv=None: calls.append(1) or 0
try:
    runpy.run_path(%(path)r, run_name=%(name)r)
except SystemExit:
    pass
print("CALLS", len(calls))
'''


def run_entry(tmp_path, name):
    path = os.path.join(APP_DIR, "zhiraf", "ui", "__main__.py")
    done = subprocess.run([sys.executable, "-c", ENTRY_SCRIPT % {"path": path, "name": name}],
                          env=env_for(tmp_path), cwd=APP_DIR, timeout=60, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_importing_entry_point_as_spawned_child_does_not_start_the_program(tmp_path):
    assert "CALLS 0" in run_entry(tmp_path, "__mp_main__")


def test_running_entry_point_as_main_starts_the_program(tmp_path):
    assert "CALLS 1" in run_entry(tmp_path, "__main__")
