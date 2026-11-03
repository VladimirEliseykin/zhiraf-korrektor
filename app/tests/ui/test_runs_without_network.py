"""The program works with every network module blocked, in the window process and in the spawned check.

The blocker is a sys.meta_path finder installed by a sitecustomize.py on PYTHONPATH, so the child process that does
the check inherits it. It blocks by module NAME (on Windows the folder simply has no such files; the real proof that
removing them is safe is the run on Windows)."""
import os
import shutil
import subprocess
import sys

import pytest

SOFFICE = shutil.which("soffice")
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = os.path.dirname(APP)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from build.prune import FORBIDDEN_QT, FORBIDDEN_STDLIB  # noqa: E402
from docfactory import P, R, make_docx, make_odt, OP  # noqa: E402

# Imports that are tried and answered with ImportError on purpose. hashlib looks for _hashlib first and falls back
# to the built-in hash modules (on Windows they live inside python37.dll).
TOLERATED_ATTEMPTS = {"_hashlib"}

SITECUSTOMIZE = '''
import fnmatch, os, sys

STDLIB = %(stdlib)r
QT = %(qt)r


def _blocked(name):
    for forbidden in STDLIB:
        if name == forbidden or name.startswith(forbidden + "."):
            return True
    last = name.rsplit(".", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(last, pattern.lower()) for pattern in QT)


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if _blocked(name):
            with open(os.environ["BLOCK_LOG"], "a") as log:
                log.write(name + "\\n")
            raise ImportError("blocked network module: " + name)
        return None


sys.meta_path.insert(0, Blocker())
'''

SNEAKY = "import http.client\n\ndef make_factories():\n    raise SystemExit('unreachable')\n"


def to_doc(docx, outdir):
    """A real .doc made by LibreOffice (done here, in the unblocked test process)."""
    profile = "file://" + str(outdir / "lo-profile")
    subprocess.run([SOFFICE, "--headless", "--norestore", "-env:UserInstallation=" + profile,
                    "--convert-to", "doc:MS Word 97", "--outdir", str(outdir), docx], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.splitext(docx)[0] + ".doc"


def write_blocker(site):
    site.mkdir(exist_ok=True)
    patterns = [p for p in FORBIDDEN_QT if "*" in p and "/" not in p and not p.startswith("*")]
    modules = [m for m in FORBIDDEN_STDLIB if not m.endswith(".dll")]
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE % {"stdlib": modules, "qt": patterns}, encoding="utf-8")


@pytest.fixture
def inputs(tmp_path, full_models_dir):
    src = tmp_path / "in"
    src.mkdir()
    text1, text2 = "Работа с информации ведётся.", "Документ определяющий порядок утверждён."
    files = [make_docx(src / "a.docx", P(R(text1)), P(R(text2))),
             make_odt(src / "b.odt", OP(text1) + OP(text2))]
    txt = src / "c.txt"
    txt.write_text(text1 + "\n\n" + text2 + "\n", encoding="utf-8")
    files.append(str(txt))
    if SOFFICE:
        files.append(to_doc(make_docx(src / "d.docx", P(R(text1)), P(R(text2))), src))
    out = tmp_path / "out"
    out.mkdir()
    return files, str(out), full_models_dir


def run_blocked(tmp_path, files, out, models, factories="fakes:make_factories", extra_path=None, extra_import=None):
    site = tmp_path / "site"
    write_blocker(site)
    log = tmp_path / "blocked.log"
    parts = [str(site)] + ([extra_path] if extra_path else []) + [APP, os.path.join(APP, "tests")]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(parts), BLOCK_LOG=str(log), DRIVER_MODELS=models,
               DRIVER_FILES=os.pathsep.join(files), DRIVER_OUT=out, DRIVER_FACTORIES=factories,
               QT_QPA_PLATFORM="offscreen")
    if extra_import:
        env["DRIVER_EXTRA_IMPORT"] = extra_import
    result = subprocess.run(["timeout", "240", sys.executable, os.path.join(HERE, "network_driver.py")],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    attempts = set(log.read_text().split()) if log.exists() else set()
    return result, attempts


def test_blocker_blocks_what_it_should(tmp_path):
    site = tmp_path / "site"
    write_blocker(site)
    code = ("import sys\nfor n in ('ssl', 'http.client', 'urllib.request', 'asyncio', 'PySide2.QtNetwork', "
            "'PySide2.QtWebEngineWidgets'):\n    try:\n        __import__(n)\n    except ImportError:\n        continue\n"
            "    sys.exit('not blocked: ' + n)\nimport socket, urllib.parse, json, PySide2.QtCore\nprint('fine')")
    env = dict(os.environ, PYTHONPATH=str(site), BLOCK_LOG=str(tmp_path / "log"))
    result = subprocess.run(["timeout", "60", sys.executable, "-c", code], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 0 and "fine" in result.stdout, result.stdout


def test_the_window_works_with_the_network_blocked(tmp_path, inputs):
    files, out, models = inputs
    result, attempts = run_blocked(tmp_path, files, out, models)
    assert result.returncode == 0, result.stdout
    assert "DRIVER OK" in result.stdout and "ImportError" not in result.stdout
    assert attempts <= TOLERATED_ATTEMPTS, "the program tried to import: %s" % sorted(attempts - TOLERATED_ATTEMPTS)
    for name in ("saved.pdf", "saved.odt", "saved.txt"):
        assert os.path.getsize(os.path.join(out, name)) > 0
    assert os.path.exists(os.path.join(os.path.dirname(files[0]), "a (исправлено).docx"))


def test_a_forbidden_import_in_the_window_process_fails_the_run(tmp_path, inputs):
    files, out, models = inputs
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "sneaky.py").write_text("import ssl\n", encoding="utf-8")
    result, attempts = run_blocked(tmp_path, files, out, models, extra_path=str(extra), extra_import="sneaky")
    assert result.returncode != 0 and "ImportError" in result.stdout and "ssl" in attempts


def test_a_forbidden_import_in_the_spawned_check_fails_the_run(tmp_path, inputs):
    files, out, models = inputs
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "sneaky.py").write_text(SNEAKY, encoding="utf-8")
    result, attempts = run_blocked(tmp_path, files, out, models, factories="sneaky:make_factories",
                                   extra_path=str(extra))
    assert result.returncode != 0 and "http" in attempts
