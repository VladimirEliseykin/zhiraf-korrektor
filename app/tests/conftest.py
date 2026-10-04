import os
import shutil
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # the app folder: "import zhiraf"
sys.path.insert(0, HERE)                    # test helpers: "import fakes", "import docfactory"

import zhiraf  # noqa: E402,F401  (puts the engine on sys.path)

SOFFICE = shutil.which("soffice")
needs_soffice = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice is not installed")


@pytest.fixture(autouse=True)
def zhiraf_home(tmp_path, monkeypatch):
    """Every test gets its own profile folder: dictionary, settings, recent list, temp files."""
    home = tmp_path / "profile"
    monkeypatch.setenv("ZHIRAF_HOME", str(home))
    return home


@pytest.fixture
def models_dir(tmp_path):
    """A models folder for fake models: only the frequency list the rules need."""
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / "vocab.tsv").write_text("информация\t10\nдокумент\t10\n", encoding="utf-8")
    return str(folder)
