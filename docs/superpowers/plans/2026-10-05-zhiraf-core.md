# Жираф.Корректор — ядро без окна: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** библиотека `zhiraf` (без Qt), которая открывает .docx/.doc/.odt/.txt, делит текст на предложения, проверяет его готовым движком в фоновом процессе с прогрессом, ведёт разбор пометок (принять, пропустить, в словарь, вручную, отменить) и сохраняет исправленную копию с нетронутым оформлением; плюс консольная команда `python -m zhiraf.cli check <файл>`.

**Architecture:** окно (план 2) будет только показывать то, что говорит это ядро. Документ любого формата превращается в одну модель (абзацы из фрагментов с начертанием); сохранение «на месте» меняет в исходном XML только символы принятых исправлений. Проверка идёт в отдельном процессе (`multiprocessing`, spawn) через новый потоковый метод движка `Checker.stream`, этапы в порядке «правила → запятые → окончания → SAGE». Разбор пометок — чистый Python-класс `ReviewSession`, позиции пометок хранятся в координатах исходного текста.

**Tech Stack:** Python 3.7-совместимый код (разработка и тесты на 3.8), lxml 4.9.3, olefile 0.47, comtypes 1.2.1 (только Windows), движок `engine/spellcheck` (onnxruntime 1.14.1, tokenizers 0.19.1, pymorphy3 2.0.2), pytest 7.4.4, vermin 1.6.0.

**Spec:** `docs/superpowers/specs/2026-10-04-zhiraf-korrektor-design.md` (разделы 3, 5, 6, 7, 9, 10, 11). Это первый из трёх планов: 1 — ядро (этот), 2 — окно на Qt, 3 — сборка папки для Windows 7.

## Global Constraints

- Весь код программы и движка совместим с Python 3.7.9 (встраиваемый Python на Windows 7); проверяется `vermin --target=3.7-`.
- Ни одной строки сетевого кода: модули `socket`, `ssl`, `urllib`, `http`, `ftplib`, `smtplib`, `poplib`, `imaplib`, `telnetlib`, `xmlrpc`, `requests`, `asyncio`, `selectors`, `QtNetwork` не импортируются кодом `app/zhiraf` и `engine/spellcheck` (тест).
- Версии библиотек закреплены: numpy 1.21.6, onnxruntime 1.14.1, tokenizers 0.19.1, psutil 5.9.8, pymorphy3 2.0.2, DAWG-Python 0.7.2, pymorphy3-dicts-ru 2.4.417150.4580142, lxml 4.9.3, olefile 0.47, comtypes 1.2.1.
- **Оригинал документа никогда не перезаписывается**: исправленная копия — «Имя (исправлено).ext» рядом.
- Временные файлы — только в `%LOCALAPPDATA%\Жираф.Корректор\tmp` (на Linux `~/.cache/zhiraf-korrektor/tmp`, в тестах `$ZHIRAF_HOME/tmp`), удаляются после работы и при каждом запуске.
- В профиле пользователя (`%APPDATA%\Жираф.Корректор`) — только словарь (по слову на строку), настройки и список недавних документов (путь, дата, счётчики); никакого текста документов и найденных ошибок.
- Сообщения для человека — по-русски, без технических слов; комментарии в коде — по-английски, как в `engine/`.
- Пороги и уровни пометок — из `engine/spellcheck/checker.py` («ошибка» ≥ 0.9, «проверьте» ≥ 0.3); уровни «error» и «check».
- Git: работа в ветке `feat/1-app-core`, коммиты `{type}: {description}` по-английски, каждый коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`; каждую git-команду выполнять отдельно.

## Review Focus

1. Исправление задевает табуляцию, разрыв строки или поле Word — такое исправление не применяется и попадает в `SaveReport.skipped`, файл не портится (тест в задаче 6).
2. Документ Word с режимом исправлений (удалённый текст `w:del`, перемещения `w:moveFrom`) и надписями (вложенные абзацы в `w:txbxContent`) — удалённый текст не проверяется и не правится, текст надписей не смешивается с абзацем (тесты в задачах 5 и 6).
3. Преобразование .doc не удалось (LibreOffice упал или завис, Word выдал ошибку) — понятная `DocumentError`, временная папка удалена (тест в задаче 9).
4. Пометка следующего этапа приходит на место, которое человек уже исправил или пропустил, — она отбрасывается и не всплывает снова (тест в задаче 13).
5. Процесс проверки умер молча (убит из-за нехватки памяти) — `CheckJob` сообщает об ошибке, программа не ждёт вечно (тест в задаче 12).

---

## Файлы

```
app/
  requirements-dev.txt          закреплённые версии для разработки (Python 3.8 на Linux)
  pytest.ini
  zhiraf/
    __init__.py                 корень программы, путь к движку и моделям
    storage.py                  словарь, настройки, недавние, временная папка
    segment.py                  деление абзаца на предложения с позициями
    eta.py                      прогресс и время до конца
    worker.py                   фоновый процесс проверки (CheckJob)
    review.py                   разбор пометок (ReviewSession)
    cli.py                      консольная команда
    documents/
      __init__.py
      model.py                  Document, Paragraph, Span, Replacement, SaveReport, ошибки
      slots.py                  «ячейки текста» и применение исправления к ним (общее для .docx/.odt)
      package.py                чтение и запись zip-пакета без изменения остальных частей
      txt_format.py
      docx_format.py
      odt_format.py
      doc_format.py             .doc: Word/LibreOffice и запасное извлечение текста
      opener.py                 open_document / save_document / close_document
  tests/
    conftest.py, fakes.py, docfactory.py, test_*.py
engine/spellcheck/checker.py    + потоковый метод stream(), порядок этапов, фабрики моделей, строгий режим
```

---

### Task 1: Окружение разработки и каркас пакета

**Files:**
- Create: `app/requirements-dev.txt`, `app/pytest.ini`, `app/zhiraf/__init__.py`, `app/tests/conftest.py`, `app/tests/test_constraints.py`
- Modify: `.gitignore` (добавить `venv-app/`)

**Interfaces:**
- Produces: `zhiraf.ROOT` (корень проекта), `zhiraf.ENGINE_DIR`, `zhiraf.models_dir()`; импорт `zhiraf` кладёт движок в `sys.path`, после чего работает `import spellcheck`. Фикстуры `zhiraf_home` (автоматическая, своя папка профиля на тест) и `models_dir` (папка с маленьким `vocab.tsv`).

- [ ] **Step 1: Создать ветку**

```bash
git -C /home/general/vm/win7 checkout -b feat/1-app-core
```

- [ ] **Step 2: Записать закреплённые версии и настройки pytest**

`app/requirements-dev.txt`:
```
numpy==1.21.6
onnxruntime==1.14.1
tokenizers==0.19.1
psutil==5.9.8
pymorphy3==2.0.2
DAWG-Python==0.7.2
pymorphy3-dicts-ru==2.4.417150.4580142
lxml==4.9.3
olefile==0.47
pytest==7.4.4
vermin==1.6.0
```

`app/pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    slow: uses the real models (minutes)
    soffice: needs LibreOffice (soffice) on PATH
addopts = -m "not slow"
```

Добавить строку `venv-app/` в `/home/general/vm/win7/.gitignore`.

- [ ] **Step 3: Создать окружение Python 3.8**

```bash
UV_PYTHON_INSTALL_DIR=/home/general/vm/win7/uv-python /home/general/vm/win7/spike/venv/bin/uv venv --python 3.8 /home/general/vm/win7/venv-app
```
```bash
/home/general/vm/win7/spike/venv/bin/uv pip install --python /home/general/vm/win7/venv-app/bin/python -r /home/general/vm/win7/app/requirements-dev.txt
```
Expected: установка без ошибок (все версии есть в виде колёс для cp38 manylinux).

- [ ] **Step 4: Каркас пакета**

`app/zhiraf/__init__.py`:
```python
"""Жираф.Корректор: the program around the spellcheck engine.

Every module must run on the embeddable Python 3.7 of Windows 7 (checked by vermin in tests).
Layout (development and the shipped folder alike): <root>/app/zhiraf, <root>/engine/spellcheck,
models in <root>/models (shipped) or <root>/engine/models (development).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE_DIR = os.path.join(ROOT, "engine")
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)


def models_dir():
    """Folder with sage/, commas/, forms/ and vocab.tsv."""
    override = os.environ.get("ZHIRAF_MODELS")
    if override:
        return override
    shipped = os.path.join(ROOT, "models")
    return shipped if os.path.isdir(shipped) else os.path.join(ENGINE_DIR, "models")
```

`app/zhiraf/documents/__init__.py`: пустой файл с докстрингом `"""Document formats: read into one model, save corrected copies."""`.

`app/tests/conftest.py`:
```python
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
```

- [ ] **Step 5: Написать тесты ограничений (они должны пройти уже сейчас — это охрана на будущее)**

`app/tests/test_constraints.py`:
```python
import ast
import os
import subprocess
import sys

import zhiraf

FORBIDDEN = {"socket", "ssl", "urllib", "urllib2", "http", "httplib", "ftplib", "smtplib", "poplib", "imaplib",
             "telnetlib", "xmlrpc", "requests", "asyncio", "websocket", "websockets", "selectors"}
SOURCE_DIRS = [os.path.join(zhiraf.ROOT, "app", "zhiraf"), os.path.join(zhiraf.ENGINE_DIR, "spellcheck")]


def python_files():
    for top in SOURCE_DIRS:
        for folder, _, names in os.walk(top):
            for name in names:
                if name.endswith(".py"):
                    yield os.path.join(folder, name)


def imported_names(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield node.module + "." + alias.name


def test_sources_import_no_network_modules():
    bad = []
    for path in python_files():
        for name in imported_names(path):
            if name.split(".")[0] in FORBIDDEN or "QtNetwork" in name:
                bad.append((os.path.relpath(path, zhiraf.ROOT), name))
    assert bad == []


def test_forbidden_import_is_caught(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("import socket\nfrom urllib import request\n", encoding="utf-8")
    names = set(imported_names(str(sample)))
    assert "socket" in names and "urllib.request" in names


def test_sources_run_on_python37():
    result = subprocess.run([sys.executable, "-m", "vermin", "--target=3.7-", "--violations", "--no-tips"]
                            + SOURCE_DIRS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert result.returncode == 0, result.stdout
```

- [ ] **Step 6: Запустить тесты**

Все команды pytest — из папки `/home/general/vm/win7/app`:
```bash
../venv-app/bin/python -m pytest tests/test_constraints.py -v
```
Expected: 3 passed. Если vermin нашёл конструкцию новее 3.7 в `engine/spellcheck`, переписать её в стиле 3.7 и запустить снова.

- [ ] **Step 7: Commit**

```bash
git -C /home/general/vm/win7 add .gitignore app
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add app package skeleton with network and python 3.7 guards" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Профиль пользователя — словарь, настройки, недавние, временная папка

**Files:**
- Create: `app/zhiraf/storage.py`
- Test: `app/tests/test_storage.py`

**Interfaces:**
- Produces: `data_dir() -> str`, `tmp_dir() -> str`, `clean_tmp() -> None`; `Dictionary(path=None)`: `__contains__(word) -> bool` (без учёта регистра), `add(word)`, `remove(word)`, `words() -> list[str]`, `export(path)`, `import_from(path) -> int` (сколько новых); `Settings(path=None)`: `settings[key]`, `set(key, value)`, ключи `show_checks`, `strict_mode`, `remember_recent`; `Recent(settings, path=None)`: `items() -> list[dict]` (новые первыми; `{"path", "opened_at", "stats"}`), `touch(path, stats=None)`, `clear()`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_storage.py`:
```python
import os

from zhiraf import storage


def test_dictionary_ignores_case_and_survives_restart():
    d = storage.Dictionary()
    d.add("ИСПДн")
    assert "испдн" in d and "ИСПДН" in d and " ИСПДн " in d
    assert "ИСПДн" in storage.Dictionary()
    assert storage.Dictionary().words() == ["ИСПДн"]


def test_dictionary_remove():
    d = storage.Dictionary()
    d.add("фаззинг")
    d.remove("ФАЗЗИНГ")
    assert "фаззинг" not in storage.Dictionary()


def test_dictionary_export_and_import_merge(tmp_path):
    a = storage.Dictionary(str(tmp_path / "a.txt"))
    for w in ("ИСПДн", "КИИ"):
        a.add(w)
    a.export(str(tmp_path / "отдел.txt"))
    b = storage.Dictionary(str(tmp_path / "b.txt"))
    b.add("КИИ")
    assert b.import_from(str(tmp_path / "отдел.txt")) == 1
    assert b.words() == ["ИСПДн", "КИИ"]


def test_dictionary_file_holds_one_word_per_line():
    d = storage.Dictionary()
    d.add("Б")
    d.add("а")
    assert open(d.path, encoding="utf-8").read() == "а\nБ\n"


def test_settings_defaults_and_persistence():
    s = storage.Settings()
    assert s["show_checks"] is True and s["strict_mode"] is False and s["remember_recent"] is True
    s.set("strict_mode", True)
    assert storage.Settings()["strict_mode"] is True


def test_settings_survive_a_damaged_file():
    s = storage.Settings()
    with open(s.path, "w", encoding="utf-8") as f:
        f.write("{не json")
    assert storage.Settings()["show_checks"] is True


def test_recent_newest_first_without_duplicates(tmp_path):
    r = storage.Recent(storage.Settings())
    r.touch(str(tmp_path / "a.docx"), {"fixed": 1})
    r.touch(str(tmp_path / "b.docx"))
    r.touch(str(tmp_path / "a.docx"))
    items = storage.Recent(storage.Settings()).items()
    assert [os.path.basename(i["path"]) for i in items] == ["a.docx", "b.docx"]
    assert items[0]["stats"] == {"fixed": 1}  # counters are kept when the file is opened again


def test_recent_is_limited_and_clearable(tmp_path):
    r = storage.Recent(storage.Settings())
    for n in range(storage.MAX_RECENT + 5):
        r.touch(str(tmp_path / ("%d.docx" % n)))
    assert len(r.items()) == storage.MAX_RECENT
    r.clear()
    assert storage.Recent(storage.Settings()).items() == []


def test_recent_not_written_when_disabled(tmp_path):
    s = storage.Settings()
    s.set("remember_recent", False)
    storage.Recent(s).touch(str(tmp_path / "secret.docx"))
    assert storage.Recent(s).items() == []


def test_clean_tmp_removes_leftovers():
    leftover = os.path.join(storage.tmp_dir(), "copy.docx")
    open(leftover, "w").close()
    storage.clean_tmp()
    assert os.path.isdir(storage.tmp_dir()) and not os.path.exists(leftover)


def test_folders_follow_profile_override(zhiraf_home):
    assert storage.data_dir() == str(zhiraf_home)
    assert storage.tmp_dir() == os.path.join(str(zhiraf_home), "tmp")
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_storage.py -v
```
Expected: FAIL — `ImportError: cannot import name 'storage'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/storage.py`:
```python
"""What the program remembers in the user's profile: dictionary, settings, recent documents, temp files.

Never document text: the dictionary holds single words, the recent list file paths and counters.
"""
import json
import os
import shutil
import sys
import time

APP_NAME = "Жираф.Корректор"
DEFAULT_SETTINGS = {"show_checks": True, "strict_mode": False, "remember_recent": True}
MAX_RECENT = 20


def _base(kind):
    override = os.environ.get("ZHIRAF_HOME")
    if override:
        return override if kind == "data" else os.path.join(override, "tmp")
    if sys.platform == "win32":
        root = os.environ.get("APPDATA" if kind == "data" else "LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, APP_NAME) if kind == "data" else os.path.join(root, APP_NAME, "tmp")
    if kind == "data":
        return os.path.join(os.path.expanduser("~"), ".local", "share", "zhiraf-korrektor")
    return os.path.join(os.path.expanduser("~"), ".cache", "zhiraf-korrektor", "tmp")


def data_dir():
    path = _base("data")
    os.makedirs(path, exist_ok=True)
    return path


def tmp_dir():
    path = _base("tmp")
    os.makedirs(path, exist_ok=True)
    return path


def clean_tmp():
    """Temp copies of documents must not outlive the program, also after a crash."""
    shutil.rmtree(_base("tmp"), ignore_errors=True)
    tmp_dir()


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return default  # a damaged file must not stop the program


class Dictionary:
    """The user's words: never flagged again. One word per line, compared without case."""

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "словарь.txt")
        self._words = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8-sig") as f:
                for line in f:
                    self._remember(line.strip())

    def _remember(self, word):
        if word:
            self._words.setdefault(word.lower(), word)

    def __contains__(self, word):
        return word.strip().lower() in self._words

    def __len__(self):
        return len(self._words)

    def words(self):
        return sorted(self._words.values(), key=str.lower)

    def add(self, word):
        self._remember(word.strip())
        self._save()

    def remove(self, word):
        self._words.pop(word.strip().lower(), None)
        self._save()

    def export(self, path):
        _write_atomic(path, "\n".join(self.words()) + "\n")

    def import_from(self, path):
        before = len(self._words)
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                self._remember(line.strip())
        self._save()
        return len(self._words) - before

    def _save(self):
        _write_atomic(self.path, "\n".join(self.words()) + "\n")


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "настройки.json")
        self._values = dict(DEFAULT_SETTINGS)
        stored = _read_json(self.path, {})
        if isinstance(stored, dict):
            self._values.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})

    def __getitem__(self, key):
        return self._values[key]

    def set(self, key, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        self._values[key] = value
        _write_atomic(self.path, json.dumps(self._values, ensure_ascii=False, indent=1))


class Recent:
    """Recently opened documents: path, time and counters; no text, no findings."""

    def __init__(self, settings, path=None):
        self.settings = settings
        self.path = path or os.path.join(data_dir(), "недавние.json")
        items = _read_json(self.path, [])
        self._items = items if isinstance(items, list) else []

    def items(self):
        return list(self._items)

    def touch(self, path, stats=None):
        if not self.settings["remember_recent"]:
            return
        key = os.path.normcase(os.path.abspath(path))
        old = [i for i in self._items if os.path.normcase(os.path.abspath(i["path"])) == key]
        self._items = [i for i in self._items if i not in old]
        kept = old[0].get("stats", {}) if old else {}
        self._items.insert(0, {"path": os.path.abspath(path), "opened_at": time.time(), "stats": stats or kept})
        del self._items[MAX_RECENT:]
        self._save()

    def clear(self):
        self._items = []
        self._save()

    def _save(self):
        _write_atomic(self.path, json.dumps(self._items, ensure_ascii=False, indent=1))
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_storage.py -v
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/storage.py app/tests/test_storage.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add user profile storage for dictionary, settings and recent documents" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Деление абзаца на предложения

**Files:**
- Create: `app/zhiraf/segment.py`
- Test: `app/tests/test_segment.py`

**Interfaces:**
- Produces: `split_sentences(text: str) -> list[tuple[int, int]]` — границы предложений в символах абзаца, без пробелов по краям; объединение всех отрезков покрывает весь непробельный текст.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_segment.py`:
```python
from zhiraf.segment import split_sentences


def parts(text):
    return [text[s:e] for s, e in split_sentences(text)]


def test_two_sentences():
    assert parts("Первое предложение. Второе предложение.") == ["Первое предложение.", "Второе предложение."]


def test_question_exclamation_and_ellipsis():
    assert parts("Кто виноват? Не мы! Посмотрим… Вот так.") == ["Кто виноват?", "Не мы!", "Посмотрим…", "Вот так."]


def test_abbreviations_do_not_split():
    text = "Приказ от 1 марта 2025 г. Минфина, т. е. ведомства, и т.д. Согласно ст. 5 Закона всё верно."
    assert parts(text) == [text]


def test_initials_do_not_split():
    assert parts("Отчёт подписал А. С. Иванов. Он согласен.") == ["Отчёт подписал А. С. Иванов.", "Он согласен."]


def test_numbered_heading_is_not_a_sentence():
    assert parts("1. Общие положения настоящего регламента.") == ["1. Общие положения настоящего регламента."]
    assert parts("2.1. Термины. Далее текст.") == ["2.1. Термины.", "Далее текст."]


def test_no_split_before_lowercase():
    assert parts("Сумма 5 тыс. руб. уплачена.") == ["Сумма 5 тыс. руб. уплачена."]


def test_closing_quote_stays_with_sentence():
    assert parts("Он сказал: «Готово.» Мы ушли.") == ["Он сказал: «Готово.»", "Мы ушли."]


def test_offsets_skip_surrounding_whitespace():
    text = "  Раз.   Два.  "
    assert split_sentences(text) == [(2, 6), (9, 13)]


def test_text_without_final_period():
    assert parts("Перечень мер защиты информации") == ["Перечень мер защиты информации"]


def test_empty_and_blank():
    assert split_sentences("") == [] and split_sentences("   ") == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_segment.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.segment'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/segment.py`:
```python
"""Split a paragraph into sentences with their offsets: the engine checks one sentence at a time."""
import re

ABBREVIATIONS = {
    "т", "е", "д", "п", "г", "гг", "ст", "пп", "ч", "им", "рис", "табл", "см", "др", "руб", "тыс", "млн", "млрд",
    "стр", "ул", "кв", "тел", "прим", "вып", "гл", "разд", "подп", "абз", "обл", "корп", "пер", "проф", "акад",
    "доц", "канд", "экз", "шт", "коп", "мин", "сек", "изд", "т.е", "т.д", "т.п", "т.к", "т.н", "н.э", "и.о",
}
BREAK = re.compile(r"[.!?…]+[»\"”)\]]*\s+")
NEXT_STARTS = re.compile(r"[«\"(]?[А-ЯЁA-Z0-9]")
NUMBER_OR_MARKER = re.compile(r"^(\d+(\.\d+)*\.?|[а-яa-z]\)|[IVXLC]+\.?)$")


def _skip_space(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def split_sentences(text):
    """Sentence spans (start, end) in text, surrounding whitespace excluded."""
    spans = []
    start = _skip_space(text, 0)
    for m in BREAK.finditer(text):
        if m.start() < start or not NEXT_STARTS.match(text, m.end()):
            continue
        head = text[start:m.start()]
        if NUMBER_OR_MARKER.match(head.strip()):
            continue  # "1." or "2.1." starts a heading, it is not a sentence of its own
        if m.group(0).rstrip().rstrip("»\"”)]") == ".":
            words = head.split()
            last = words[-1].lstrip("«\"(").lower() if words else ""
            if last in ABBREVIATIONS or (len(last) == 1 and last.isalpha()):
                continue  # "г.", "т. е.", initials "А. С."
        end = m.start() + len(m.group(0).rstrip())
        spans.append((start, end))
        start = _skip_space(text, m.end())
    tail = text[start:].rstrip()
    if tail:
        spans.append((start, start + len(tail)))
    return spans
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_segment.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/segment.py app/tests/test_segment.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add sentence segmentation with offsets" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Модель документа, обычный текст и открытие по формату

**Files:**
- Create: `app/zhiraf/documents/model.py`, `app/zhiraf/documents/txt_format.py`, `app/zhiraf/documents/opener.py`
- Test: `app/tests/test_model.py`

**Interfaces:**
- Produces (`documents.model`): `Span(text, bold=False, italic=False, underline=False)`; `Paragraph(spans, style="normal", table=None, has_image=False)` с `.text`; стили `normal | title | h1 | h2 | h3 | list`, `table = (номер таблицы, строка, столбец)`; `Document(paragraphs, kind, path=None, editable=True, saved_as=None, notice=None, source=None)`; `Replacement(paragraph, start, end, text)` — в координатах ИСХОДНОГО текста абзаца, `text=""` удаляет; `SaveReport(path, applied, skipped=[])`; `apply_replacements(text, replacements) -> str`; `group_by_paragraph(replacements) -> dict[int, list]`; `corrected_path(path, ext=None) -> str`; исключения `DocumentError(message)` и `UnsupportedFormat(DocumentError)`.
- Produces (`documents.opener`): `open_document(path) -> Document`, `save_document(doc, replacements, dst=None) -> SaveReport`, `close_document(doc)`; словари `READERS` (расширение → функция чтения) и `SAVERS` (`doc.kind` → функция сохранения `(doc, replacements, dst) -> SaveReport`), которые дополняют задачи 5–9.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_model.py`:
```python
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
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_model.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.documents.opener'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/documents/model.py`:
```python
"""One model for every document format: paragraphs made of formatted spans."""
import collections
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


class DocumentError(Exception):
    """A file that cannot be opened or saved; the message is shown to the user as is."""


class UnsupportedFormat(DocumentError):
    pass


@dataclass
class Span:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class Paragraph:
    spans: List[Span]
    style: str = "normal"                       # normal | title | h1 | h2 | h3 | list
    table: Optional[Tuple[int, int, int]] = None  # (table number, row, column) for text in a table cell
    has_image: bool = False

    @property
    def text(self):
        return "".join(s.text for s in self.spans)


@dataclass
class Document:
    paragraphs: List[Paragraph]
    kind: str                       # docx | odt | doc | txt | paste
    path: Optional[str] = None
    editable: bool = True           # False: an opened file changes only through marks
    saved_as: Optional[str] = None  # extension of the corrected copy
    notice: Optional[str] = None    # what the user must know (e.g. .doc saved as .docx)
    source: Any = None              # format-specific data for saving in place


@dataclass
class Replacement:
    """Characters [start, end) of a paragraph's ORIGINAL text become text ("" deletes, start == end inserts)."""
    paragraph: int
    start: int
    end: int
    text: str


@dataclass
class SaveReport:
    path: str
    applied: int
    skipped: List[Replacement] = field(default_factory=list)  # fixes that could not be placed safely


def apply_replacements(text, replacements):
    for r in sorted(replacements, key=lambda r: (r.start, r.end), reverse=True):
        text = text[:r.start] + r.text + text[r.end:]
    return text


def group_by_paragraph(replacements):
    groups = collections.OrderedDict()
    for r in replacements:
        groups.setdefault(r.paragraph, []).append(r)
    return groups


def corrected_path(path, ext=None):
    folder, name = os.path.split(path)
    stem, old_ext = os.path.splitext(name)
    ext = "." + (ext or old_ext.lstrip("."))
    candidate = os.path.join(folder, "%s (исправлено)%s" % (stem, ext))
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, "%s (исправлено %d)%s" % (stem, n, ext))
        n += 1
    return candidate
```

`app/zhiraf/documents/txt_format.py`:
```python
"""Plain text: one line is one paragraph; encoding and line endings are kept on saving."""
from .model import Document, Paragraph, SaveReport, Span, apply_replacements, group_by_paragraph

BOM = b"\xef\xbb\xbf"


def read_txt(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(BOM):
        encoding = "utf-8-sig"
    else:
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "cp1251"
    text = raw.decode(encoding, "replace")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    doc = Document([Paragraph([Span(line)]) for line in lines], kind="txt", path=path, editable=False, saved_as="txt")
    doc.source = {"encoding": encoding, "newline": newline}
    return doc


def save_txt(doc, replacements, dst):
    groups = group_by_paragraph(replacements)
    lines = [apply_replacements(p.text, groups.get(i, [])) for i, p in enumerate(doc.paragraphs)]
    with open(dst, "w", encoding=doc.source["encoding"], newline="") as f:
        f.write(doc.source["newline"].join(lines))
    return SaveReport(dst, len(replacements))
```

`app/zhiraf/documents/opener.py`:
```python
"""Open any supported document into the model and save its corrected copy next to it."""
import os
import shutil

from . import txt_format
from .model import DocumentError, UnsupportedFormat, corrected_path

READERS = {".txt": txt_format.read_txt}
SAVERS = {"txt": txt_format.save_txt}


def open_document(path):
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if reader is None:
        raise UnsupportedFormat("Формат «%s» не поддерживается. Можно открыть .docx, .doc, .odt и .txt."
                                % (ext or "без расширения"))
    if not os.path.exists(path):
        raise DocumentError("Файл не найден: %s" % path)
    return reader(path)


def save_document(doc, replacements, dst=None):
    dst = dst or corrected_path(doc.path, doc.saved_as)
    if doc.path and os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(doc.path)):
        raise DocumentError("Исходный документ не перезаписывается — выберите другое имя.")
    try:
        return SAVERS[doc.kind](doc, replacements, dst)
    except PermissionError:
        raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе."
                            % os.path.basename(dst))


def close_document(doc):
    """Remove temp copies made for this document (a .doc converted to .docx)."""
    source = doc.source if isinstance(doc.source, dict) else {}
    if source.get("tmpdir"):
        shutil.rmtree(source["tmpdir"], ignore_errors=True)
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_model.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents app/tests/test_model.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add document model, plain text format and opener" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Чтение .docx

**Files:**
- Create: `app/zhiraf/documents/slots.py`, `app/zhiraf/documents/docx_format.py`, `app/tests/docfactory.py`
- Modify: `app/zhiraf/documents/opener.py` (зарегистрировать `.docx`)
- Test: `app/tests/test_docx_read.py`

**Interfaces:**
- Consumes: `model.Document/Paragraph/Span/DocumentError`.
- Produces (`documents.slots`): `Slot` (поля `text`, свойство `editable`, метод `write(text)` меняет и `text`, и исходный XML), `FixedSlot(text)` (табуляция, разрыв строки — нередактируемый).
- Produces (`documents.docx_format`): `read_docx(path) -> Document` (`kind="docx"`, `editable=False`, `saved_as="docx"`); `iter_paragraphs(body)` — пары `(w:p, table)` в порядке документа (одинаковый обход при чтении и сохранении — по нему абзац номер i в модели находит свой w:p); `paragraph_slots(p) -> (list[Slot], has_image)`; `write_docx_package(path, body_xml, styles_xml=None, extra=None)` — минимальный .docx (для тестов и запасного сохранения в задаче 9); `PARSER` — безопасный XML-парсер.
- Produces (`tests/docfactory.py`): `R(text, bold=False, italic=False, underline=False)`, `P(*runs, style=None, numbered=False)`, `TAB`, `BR`, `table(rows)`, `make_docx(path, *paragraphs, styles_xml=None)`, `PNG` (байты картинки, кладётся в пакет).

- [ ] **Step 1: Помощник для создания .docx в тестах и падающие тесты**

`app/tests/docfactory.py`:
```python
"""Build small Word and ODF documents for tests, with the XML shapes Word itself writes."""
import zipfile
from xml.sax.saxutils import escape

from zhiraf.documents import docx_format

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
TAB = "<w:r><w:tab/></w:r>"
BR = "<w:r><w:br/></w:r>"


def R(text, bold=False, italic=False, underline=False):
    props = "".join(tag for tag, on in (("<w:b/>", bold), ("<w:i/>", italic), ('<w:u w:val="single"/>', underline)) if on)
    rpr = "<w:rPr>%s</w:rPr>" % props if props else ""
    return '<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr, escape(text))


def P(*runs, style=None, numbered=False):
    ppr = ""
    if style or numbered:
        ppr = "<w:pPr>%s%s</w:pPr>" % ('<w:pStyle w:val="%s"/>' % style if style else "",
                                        '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' if numbered else "")
    return "<w:p>%s%s</w:p>" % (ppr, "".join(runs))


def table(rows):
    cells = lambda row: "".join("<w:tc><w:tcPr/>%s</w:tc>" % cell for cell in row)
    return "<w:tbl><w:tblPr/>%s</w:tbl>" % "".join("<w:tr>%s</w:tr>" % cells(row) for row in rows)


def make_docx(path, *paragraphs, styles_xml=None):
    docx_format.write_docx_package(str(path), "".join(paragraphs), styles_xml=styles_xml,
                                   extra={"word/media/image1.png": PNG})
    return str(path)


def zip_entries(path):
    with zipfile.ZipFile(str(path)) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}
```

`app/tests/test_docx_read.py`:
```python
from docfactory import BR, P, R, TAB, make_docx, table
from zhiraf.documents import opener
from zhiraf.documents.docx_format import read_docx
from zhiraf.documents.model import DocumentError

import pytest


def test_paragraph_text_and_formatting(tmp_path):
    path = make_docx(tmp_path / "a.docx", P(R("Важный ", bold=True), R("текст", italic=True), R(" и всё")))
    doc = read_docx(path)
    assert doc.kind == "docx" and doc.editable is False and doc.saved_as == "docx"
    p = doc.paragraphs[0]
    assert p.text == "Важный текст и всё"
    assert [(s.text, s.bold, s.italic) for s in p.spans] == [("Важный ", True, False), ("текст", False, True),
                                                             (" и всё", False, False)]


def test_runs_with_same_format_merge_into_one_span(tmp_path):
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Раз"), R("два"))))
    assert len(doc.paragraphs[0].spans) == 1


def test_headings_lists_and_tables(tmp_path):
    path = make_docx(tmp_path / "a.docx",
                     P(R("Введение"), style="Heading1"),
                     P(R("Пункт"), numbered=True),
                     table([[P(R("Ячейка А")), P(R("Ячейка Б"))]]),
                     P(R("После таблицы")))
    doc = read_docx(path)
    assert [(p.text, p.style, p.table) for p in doc.paragraphs] == [
        ("Введение", "h1", None), ("Пункт", "list", None),
        ("Ячейка А", "normal", (0, 0, 0)), ("Ячейка Б", "normal", (0, 0, 1)), ("После таблицы", "normal", None)]


def test_heading_found_by_style_name_for_russian_word(tmp_path):
    styles = ('<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="Заголовок 2"/></w:style></w:styles>')
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Раздел"), style="2"), styles_xml=styles))
    assert doc.paragraphs[0].style == "h2"


def test_tabs_and_breaks_are_part_of_the_text(tmp_path):
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("А"), TAB, R("Б"), BR, R("В"))))
    assert doc.paragraphs[0].text == "А\tБ\nВ"


def test_deleted_and_moved_text_is_not_read(tmp_path):
    deleted = '<w:del w:id="1" w:author="x"><w:r><w:delText>удалено </w:delText></w:r></w:del>'
    moved = '<w:moveFrom w:id="2" w:author="x"><w:r><w:t>перенесено </w:t></w:r></w:moveFrom>'
    inserted = '<w:ins w:id="3" w:author="x">%s</w:ins>' % R("вставлено ")
    doc = read_docx(make_docx(tmp_path / "a.docx", P(deleted, moved, inserted, R("текст"))))
    assert doc.paragraphs[0].text == "вставлено текст"


def test_text_box_text_does_not_join_the_paragraph(tmp_path):
    box = ('<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox><w:txbxContent>'
           + P(R("в надписи")) + "</w:txbxContent></v:textbox></v:shape></w:pict></w:r>")
    doc = read_docx(make_docx(tmp_path / "a.docx", P(R("Основной "), box, R("текст"))))
    assert doc.paragraphs[0].text == "Основной текст"
    assert doc.paragraphs[0].has_image is True


def test_hyperlink_text_is_read(tmp_path):
    link = '<w:hyperlink w:anchor="x">%s</w:hyperlink>' % R("ссылка")
    assert read_docx(make_docx(tmp_path / "a.docx", P(R("Это "), link))).paragraphs[0].text == "Это ссылка"


def test_broken_file_gives_user_message(tmp_path):
    bad = tmp_path / "плохой.docx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(DocumentError) as e:
        read_docx(str(bad))
    assert "плохой.docx" in str(e.value)


def test_opener_knows_docx(tmp_path):
    assert opener.open_document(make_docx(tmp_path / "a.docx", P(R("Текст")))).paragraphs[0].text == "Текст"
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_docx_read.py -v
```
Expected: FAIL — `ImportError: cannot import name 'docx_format'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/documents/slots.py`:
```python
"""Pieces of a paragraph's text as stored in a file: editable text nodes and fixed characters.

Saving a fix "in place" means rewriting only the text nodes the fix covers; a fix that would cross
a fixed character (a tab, a line break, a field) is refused rather than risk damaging the file.
"""


class Slot:
    """Editable text stored in some XML node; subclasses know where."""
    editable = True

    def __init__(self, text):
        self.text = text

    def write(self, text):
        raise NotImplementedError


class FixedSlot(Slot):
    """A character the file stores as an element (tab, line break): shown, never edited."""
    editable = False

    def write(self, text):
        raise RuntimeError("fixed text cannot be edited")
```

`app/zhiraf/documents/docx_format.py`:
```python
"""Word .docx: read into the document model (saving: task 6).

lxml, not xml.etree: etree renames namespace prefixes on output, and Word rejects a file whose
mc:Ignorable prefixes no longer match their declarations.
"""
import os
import re
import zipfile
from xml.sax.saxutils import escape

from lxml import etree

from .model import Document, DocumentError, Paragraph, Span
from .slots import FixedSlot, Slot

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_XML = "word/document.xml"
STYLES_XML = "word/styles.xml"
HEADING_NAME = re.compile(r"^(heading|заголовок)\s*(\d)$", re.I)
# documents come from outside: no entity expansion, no external DTDs
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


def q(tag):
    return "{%s}%s" % (W, tag)


IMAGE_TAGS = {q("drawing"), q("pict"), q("object")}
DELETED = {q("del"), q("moveFrom")}


class TextSlot(Slot):
    """The text of one w:t element."""

    def __init__(self, element, run):
        Slot.__init__(self, element.text or "")
        self.element = element
        self.run = run

    def write(self, text):
        self.text = text
        self.element.text = text
        if text != text.strip():
            self.element.set(XML_SPACE, "preserve")


class DocxFixed(FixedSlot):
    def __init__(self, text, run):
        FixedSlot.__init__(self, text)
        self.run = run


def _owner_paragraph(el):
    while el is not None and el.tag != q("p"):
        el = el.getparent()
    return el


def _deleted(el, p):
    """Inside tracked deleted or moved-away text of this paragraph."""
    el = el.getparent()
    while el is not None and el is not p:
        if el.tag in DELETED:
            return True
        el = el.getparent()
    return False


def paragraph_slots(p):
    """Text slots of a w:p in reading order and whether it holds a picture; text boxes are left out."""
    slots, image = [], False
    for el in p.iter():
        tag = el.tag
        if el is p or not isinstance(tag, str):
            continue
        if tag in IMAGE_TAGS:
            if _owner_paragraph(el.getparent()) is p:
                image = True
            continue
        run = el.getparent()
        if run is None or run.tag != q("r") or _owner_paragraph(run) is not p or _deleted(el, p):
            continue
        if tag == q("t"):
            slots.append(TextSlot(el, run))
        elif tag == q("tab"):
            slots.append(DocxFixed("\t", run))
        elif tag in (q("br"), q("cr")):
            slots.append(DocxFixed("\n", run))
        elif tag == q("noBreakHyphen"):
            slots.append(DocxFixed("-", run))
    return slots, image


def iter_paragraphs(body):
    """(w:p, table position or None) in document order; cells of tables (also nested) included."""
    tables = [0]

    def walk(container, position):
        for child in container:
            if child.tag == q("p"):
                yield child, position
            elif child.tag == q("tbl"):
                number = tables[0]
                tables[0] += 1
                for r, tr in enumerate(child.findall(q("tr"))):
                    for c, tc in enumerate(tr.findall(q("tc"))):
                        for item in walk(tc, (number, r, c)):
                            yield item
            elif child.tag == q("sdt"):
                content = child.find(q("sdtContent"))
                if content is not None:
                    for item in walk(content, position):
                        yield item
            elif child.tag in (q("customXml"), q("ins")):
                for item in walk(child, position):
                    yield item

    return walk(body, None)


def _flag(rpr, tag):
    el = rpr.find(q(tag)) if rpr is not None else None
    if el is None:
        return False
    return el.get(q("val"), "true").lower() not in ("0", "false", "none")


def _run_format(run):
    rpr = run.find(q("rPr"))
    return _flag(rpr, "b"), _flag(rpr, "i"), _flag(rpr, "u")


def _style_names(styles_xml):
    names = {}
    if styles_xml:
        root = etree.fromstring(styles_xml, PARSER)
        for style in root.iter(q("style")):
            name = style.find(q("name"))
            if style.get(q("styleId")) and name is not None:
                names[style.get(q("styleId"))] = name.get(q("val"), "")
    return names


def _paragraph_style(p, names):
    ppr = p.find(q("pPr"))
    if ppr is None:
        return "normal"
    style = ppr.find(q("pStyle"))
    style_id = style.get(q("val"), "") if style is not None else ""
    name = names.get(style_id, style_id).strip()
    m = HEADING_NAME.match(name) or HEADING_NAME.match(style_id)
    if m:
        return "h%d" % min(int(m.group(2)), 3)
    if name.lower() in ("title", "название"):
        return "title"
    if ppr.find(q("numPr")) is not None or name.lower().startswith(("list", "список")):
        return "list"
    return "normal"


def load_package(path):
    """(document root element, styles xml bytes or None); DocumentError with a user message."""
    try:
        with zipfile.ZipFile(path) as z:
            document = z.read(DOCUMENT_XML)
            styles = z.read(STYLES_XML) if STYLES_XML in z.namelist() else None
        return etree.fromstring(document, PARSER), styles
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError, OSError):
        raise DocumentError("Не удалось открыть «%s»: файл повреждён или защищён паролем." % os.path.basename(path))


def read_docx(path):
    root, styles = load_package(path)
    names = _style_names(styles)
    paragraphs = []
    for p, position in iter_paragraphs(root.find(q("body"))):
        slots, image = paragraph_slots(p)
        spans = []
        for slot in slots:
            fmt = _run_format(slot.run)
            if spans and (spans[-1].bold, spans[-1].italic, spans[-1].underline) == fmt:
                spans[-1].text += slot.text
            else:
                spans.append(Span(slot.text, *fmt))
        paragraphs.append(Paragraph(spans, _paragraph_style(p, names), position, image))
    return Document(paragraphs, kind="docx", path=path, editable=False, saved_as="docx")


CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Default Extension="png" ContentType="image/png"/>'
                 '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument'
                 '.wordprocessingml.document.main+xml"/>'
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument'
                 '.wordprocessingml.styles+xml"/></Types>')
PACKAGE_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'officeDocument" Target="word/document.xml"/></Relationships>')
DOCUMENT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                 'styles" Target="styles.xml"/></Relationships>')
DEFAULT_STYLES = ('<w:styles xmlns:w="%s"><w:style w:type="paragraph" w:styleId="Heading1">'
                  '<w:name w:val="heading 1"/></w:style></w:styles>' % W)
DOCUMENT_TEMPLATE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<w:document xmlns:w="%s" '
                     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                     'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                     'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14">'
                     '<w:body>%%s<w:sectPr/></w:body></w:document>' % W)


def write_docx_package(path, body_xml, styles_xml=None, extra=None):
    """A minimal valid .docx with the given w:body content."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", PACKAGE_RELS)
        z.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
        z.writestr(DOCUMENT_XML, DOCUMENT_TEMPLATE % body_xml)
        z.writestr(STYLES_XML, styles_xml or DEFAULT_STYLES)
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def plain_paragraphs_xml(texts):
    """w:p elements for plain paragraphs (used when a .doc can only be saved as a new .docx)."""
    return "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(t) for t in texts)
```

В `app/zhiraf/documents/opener.py` добавить импорт и регистрацию:
```python
from . import docx_format, txt_format

READERS = {".txt": txt_format.read_txt, ".docx": docx_format.read_docx}
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_docx_read.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents app/tests/docfactory.py app/tests/test_docx_read.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: read docx into the document model" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Сохранение .docx «на месте»

**Files:**
- Create: `app/zhiraf/documents/package.py`
- Modify: `app/zhiraf/documents/slots.py` (добавить `apply_to_slots`), `app/zhiraf/documents/docx_format.py` (добавить `save_docx`), `app/zhiraf/documents/opener.py` (зарегистрировать сохранение)
- Test: `app/tests/test_docx_save.py`

**Interfaces:**
- Consumes: `docx_format.iter_paragraphs`, `paragraph_slots`, `PARSER`, `q`; `model.Replacement/SaveReport/group_by_paragraph/DocumentError`.
- Produces: `slots.apply_to_slots(slots, start, end, text) -> bool` (False — исправление отказано: мешает нередактируемый символ или не к чему прикрепить вставку); `package.read_package(path) -> (infos, blobs)`, `package.write_package(dst, infos, blobs)` (все части, кроме изменённых, переписываются как есть, в том же порядке и со сжатием); `docx_format.save_docx(doc, replacements, dst) -> SaveReport`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_docx_save.py`:
```python
from docfactory import BR, P, R, TAB, make_docx, table, zip_entries
from zhiraf.documents import opener
from zhiraf.documents.docx_format import read_docx, save_docx
from zhiraf.documents.model import Replacement


def saved(tmp_path, *paragraphs, reps):
    src = make_docx(tmp_path / "src.docx", *paragraphs)
    report = save_docx(read_docx(src), reps, str(tmp_path / "out.docx"))
    return src, report, read_docx(report.path)


def test_replacement_inside_one_run(tmp_path):
    _, report, out = saved(tmp_path, P(R("Работа с информации ведётся.")), reps=[Replacement(0, 9, 19, "информацией")])
    assert report.applied == 1 and report.skipped == []
    assert out.paragraphs[0].text == "Работа с информацией ведётся."


def test_replacement_across_runs_keeps_first_run_format(tmp_path):
    _, _, out = saved(tmp_path, P(R("Так ", bold=True), R("же был")), reps=[Replacement(0, 0, 6, "Также")])
    p = out.paragraphs[0]
    assert p.text == "Также был"
    assert (p.spans[0].text, p.spans[0].bold) == ("Также", True)


def test_comma_insertion_joins_previous_word_run(tmp_path):
    _, _, out = saved(tmp_path, P(R("Документ", bold=True), R(" определяющий порядок")),
                      reps=[Replacement(0, 8, 8, ",")])
    assert out.paragraphs[0].text == "Документ, определяющий порядок"
    assert out.paragraphs[0].spans[0].text == "Документ,"


def test_comma_deletion(tmp_path):
    _, _, out = saved(tmp_path, P(R("Однако, промокод")), reps=[Replacement(0, 6, 7, "")])
    assert out.paragraphs[0].text == "Однако промокод"


def test_several_fixes_in_one_paragraph(tmp_path):
    text = "Так же сотрудники с информации работают"
    _, report, out = saved(tmp_path, P(R(text)),
                           reps=[Replacement(0, 0, 6, "Также"), Replacement(0, 20, 30, "информацией"),
                                 Replacement(0, 17, 17, ",")])
    assert report.applied == 3
    assert out.paragraphs[0].text == "Также сотрудники, с информацией работают"


def test_fix_crossing_a_tab_or_break_is_refused(tmp_path):
    reps = [Replacement(0, 0, 3, "АБВ"), Replacement(1, 0, 3, "АБВ")]
    _, report, out = saved(tmp_path, P(R("А"), TAB, R("Б")), P(R("А"), BR, R("Б")), reps=reps)
    assert report.applied == 0 and report.skipped == reps
    assert [p.text for p in out.paragraphs] == ["А\tБ", "А\nБ"]


def test_table_cell_and_paragraph_numbering(tmp_path):
    _, _, out = saved(tmp_path, P(R("До")), table([[P(R("с информации"))]]), P(R("После")),
                      reps=[Replacement(1, 2, 12, "информацией")])
    assert [p.text for p in out.paragraphs] == ["До", "с информацией", "После"]


def test_deleted_text_is_never_edited(tmp_path):
    deleted = '<w:del w:id="1" w:author="x"><w:r><w:delText>старое</w:delText></w:r></w:del>'
    src, _, _ = saved(tmp_path, P(deleted, R("новое")), reps=[Replacement(0, 0, 5, "свежее")])
    xml = zip_entries(tmp_path / "out.docx")["word/document.xml"].decode("utf-8")
    assert "<w:delText>старое</w:delText>" in xml and "свежее" in xml


def test_other_parts_and_namespaces_are_kept(tmp_path):
    src, report, _ = saved(tmp_path, P(R("Так же")), P(R("Не трогать")), reps=[Replacement(0, 0, 6, "Также")])
    before, after = zip_entries(src), zip_entries(report.path)
    assert list(before) == list(after)
    for name in before:
        if name != "word/document.xml":
            assert before[name] == after[name]
    xml = after["word/document.xml"].decode("utf-8")
    assert 'mc:Ignorable="w14"' in xml and "xmlns:w14=" in xml
    assert '<w:t xml:space="preserve">Не трогать</w:t>' in xml


def test_leading_space_is_preserved(tmp_path):
    _, _, out = saved(tmp_path, P(R("А"), R("б в")), reps=[Replacement(0, 1, 2, " Б")])
    assert out.paragraphs[0].text == "А Б в"


def test_save_document_names_the_copy(tmp_path):
    src = make_docx(tmp_path / "Приказ.docx", P(R("Так же")))
    report = opener.save_document(opener.open_document(src), [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith("Приказ (исправлено).docx")
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_docx_save.py -v
```
Expected: FAIL — `ImportError: cannot import name 'save_docx'`.

- [ ] **Step 3: Реализация**

В конец `app/zhiraf/documents/slots.py`:
```python
def _char_map(slots):
    """For every character of the paragraph: (slot index, offset inside the slot)."""
    chars = []
    for index, slot in enumerate(slots):
        chars.extend((index, k) for k in range(len(slot.text)))
    return chars


def apply_to_slots(slots, start, end, text):
    """Put text in place of characters [start, end) of the paragraph.

    False when a fixed character is in the way or an insertion has no editable text to join.
    An insertion (start == end, a comma) joins the text before it: the end of the previous word.
    A replacement across several text nodes goes into the first one; the others give up their part.
    """
    chars = _char_map(slots)
    if start == end:
        for pos, after in ((start - 1, True), (start, False)):
            if 0 <= pos < len(chars) and slots[chars[pos][0]].editable:
                index, k = chars[pos]
                k += 1 if after else 0
                slot = slots[index]
                slot.write(slot.text[:k] + text + slot.text[k:])
                return True
        return False
    if start < 0 or end > len(chars):
        return False
    touched = sorted({chars[i][0] for i in range(start, end)})
    if any(not slots[i].editable for i in range(touched[0], touched[-1] + 1)):
        return False
    first, last = touched[0], touched[-1]
    k0, k1 = chars[start][1], chars[end - 1][1] + 1
    if first == last:
        slot = slots[first]
        slot.write(slot.text[:k0] + text + slot.text[k1:])
        return True
    slots[first].write(slots[first].text[:k0] + text)
    for i in range(first + 1, last):
        slots[i].write("")
    slots[last].write(slots[last].text[k1:])
    return True
```

`app/zhiraf/documents/package.py`:
```python
"""Zip packages (.docx, .odt): rewrite changed parts, copy every other part as it was."""
import os
import zipfile

from .model import DocumentError


def read_package(path):
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            return infos, {i.filename: z.read(i.filename) for i in infos}
    except (zipfile.BadZipFile, OSError):
        raise DocumentError("Не удалось прочитать «%s»: файл повреждён или занят." % os.path.basename(path))


def write_package(dst, infos, blobs):
    """Same entries in the same order with the same compression (ODF needs 'mimetype' first, stored)."""
    tmp = dst + ".part"
    with zipfile.ZipFile(tmp, "w") as z:
        for info in infos:
            z.writestr(info, blobs[info.filename])
    os.replace(tmp, dst)
```

В конец `app/zhiraf/documents/docx_format.py`:
```python
from .model import SaveReport, group_by_paragraph  # noqa: E402
from .package import read_package, write_package  # noqa: E402
from .slots import apply_to_slots  # noqa: E402


def save_docx(doc, replacements, dst):
    """Copy the original package; only characters of the fixes change in word/document.xml."""
    infos, blobs = read_package(doc.path)
    root = etree.fromstring(blobs[DOCUMENT_XML], PARSER)
    paragraphs = [p for p, _ in iter_paragraphs(root.find(q("body")))]
    applied, skipped = 0, []
    for index, reps in group_by_paragraph(replacements).items():
        slots, _ = paragraph_slots(paragraphs[index])
        for r in sorted(reps, key=lambda r: (r.start, r.end), reverse=True):
            if apply_to_slots(slots, r.start, r.end, r.text):
                applied += 1
            else:
                skipped.append(r)
    blobs[DOCUMENT_XML] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    write_package(dst, infos, blobs)
    return SaveReport(dst, applied, sorted(skipped, key=lambda r: (r.paragraph, r.start)))
```
(Импорты перенести в начало файла к остальным, если линтер возражает: `from .model import Document, DocumentError, Paragraph, SaveReport, Span, group_by_paragraph`, `from .package import read_package, write_package`, `from .slots import FixedSlot, Slot, apply_to_slots`.)

В `app/zhiraf/documents/opener.py`:
```python
SAVERS = {"txt": txt_format.save_txt, "docx": docx_format.save_docx}
```

- [ ] **Step 4: Тесты проходят (и тесты чтения тоже)**

```bash
../venv-app/bin/python -m pytest tests/test_docx_save.py tests/test_docx_read.py tests/test_model.py -v
```
Expected: all passed (11 + 10 + 8).

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents app/tests/test_docx_save.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: save corrected docx copies in place" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: .odt — чтение и сохранение «на месте»

**Files:**
- Create: `app/zhiraf/documents/odt_format.py`
- Modify: `app/tests/docfactory.py` (добавить `make_odt`), `app/zhiraf/documents/opener.py`
- Test: `app/tests/test_odt.py`

**Interfaces:**
- Consumes: `slots.Slot/FixedSlot/apply_to_slots`, `package.read_package/write_package`, `docx_format.PARSER`.
- Produces: `read_odt(path) -> Document` (`kind="odt"`, `saved_as="odt"`), `save_odt(doc, replacements, dst) -> SaveReport`; в тестах `make_odt(path, body_xml, auto_styles="")`, `OP(*parts, style=None)` (абзац), `OH(text, level)` (заголовок), `OSPAN(text, style)`.

- [ ] **Step 1: Помощник .odt и падающие тесты**

В конец `app/tests/docfactory.py`:
```python
ODF = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
}
ODF_DECL = " ".join('xmlns:%s="%s"' % kv for kv in ODF.items())
BOLD_STYLE = ('<style:style style:name="T1" style:family="text">'
              '<style:text-properties fo:font-weight="bold"/></style:style>')


def OP(*parts, style=None):
    attr = ' text:style-name="%s"' % style if style else ""
    return "<text:p%s>%s</text:p>" % (attr, "".join(parts))


def OH(text, level):
    return '<text:h text:outline-level="%d">%s</text:h>' % (level, escape(text))


def OSPAN(text, style):
    return '<text:span text:style-name="%s">%s</text:span>' % (style, escape(text))


def make_odt(path, body_xml, auto_styles=BOLD_STYLE):
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content %s office:version="1.2">'
               '<office:automatic-styles>%s</office:automatic-styles><office:body><office:text>%s'
               '</office:text></office:body></office:document-content>' % (ODF_DECL, auto_styles, body_xml))
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest '
                'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '</manifest:manifest>')
    with zipfile.ZipFile(str(path), "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        z.writestr("META-INF/manifest.xml", manifest, zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", content, zipfile.ZIP_DEFLATED)
        z.writestr("Pictures/image1.png", PNG, zipfile.ZIP_DEFLATED)
    return str(path)
```

`app/tests/test_odt.py`:
```python
import zipfile

from docfactory import OH, OP, OSPAN, make_odt, zip_entries
from zhiraf.documents import opener
from zhiraf.documents.model import Replacement
from zhiraf.documents.odt_format import read_odt, save_odt


def test_read_text_headings_lists_tables_and_bold(tmp_path):
    body = (OH("Введение", 1) + OP("Текст ", OSPAN("важный", "T1"), " конец")
            + '<text:list><text:list-item>' + OP("Пункт") + "</text:list-item></text:list>"
            + '<table:table><table:table-row><table:table-cell>' + OP("Ячейка")
            + "</table:table-cell></table:table-row></table:table>")
    doc = read_odt(make_odt(tmp_path / "a.odt", body))
    assert [(p.text, p.style, p.table) for p in doc.paragraphs] == [
        ("Введение", "h1", None), ("Текст важный конец", "normal", None), ("Пункт", "list", None),
        ("Ячейка", "normal", (0, 0, 0))]
    assert [(s.text, s.bold) for s in doc.paragraphs[1].spans] == [("Текст ", False), ("важный", True),
                                                                   (" конец", False)]


def test_spaces_tabs_and_breaks(tmp_path):
    doc = read_odt(make_odt(tmp_path / "a.odt", OP('А<text:s text:c="2"/>Б<text:tab/>В<text:line-break/>Г')))
    assert doc.paragraphs[0].text == "А  Б\tВ\nГ"


def test_footnote_text_is_not_part_of_the_paragraph(tmp_path):
    note = '<text:note text:note-class="footnote"><text:note-body>' + OP("сноска") + "</text:note-body></text:note>"
    assert read_odt(make_odt(tmp_path / "a.odt", OP("Текст", note, " дальше"))).paragraphs[0].text == "Текст дальше"


def test_save_in_place_across_span_and_tail(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP(OSPAN("Так ", "T1"), "же был"))
    report = save_odt(read_odt(src), [Replacement(0, 0, 6, "Также")], str(tmp_path / "out.odt"))
    out = read_odt(report.path)
    assert report.applied == 1 and out.paragraphs[0].text == "Также был"
    assert (out.paragraphs[0].spans[0].text, out.paragraphs[0].spans[0].bold) == ("Также", True)


def test_fix_across_a_tab_is_refused(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("А<text:tab/>Б"))
    report = save_odt(read_odt(src), [Replacement(0, 0, 3, "АБВ")], str(tmp_path / "out.odt"))
    assert report.applied == 0 and len(report.skipped) == 1


def test_package_order_and_mimetype_kept(tmp_path):
    src = make_odt(tmp_path / "a.odt", OP("Так же"))
    report = opener.save_document(opener.open_document(src), [Replacement(0, 0, 6, "Также")])
    with zipfile.ZipFile(report.path) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    before, after = zip_entries(src), zip_entries(report.path)
    assert list(before) == list(after) and before["Pictures/image1.png"] == after["Pictures/image1.png"]
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_odt.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.documents.odt_format'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/documents/odt_format.py`:
```python
"""OpenDocument .odt: read into the document model and save corrected copies in place.

Text of an ODF paragraph lives in element .text and in the .tail of child elements; spaces may be
<text:s text:c="n"/>, tabs <text:tab/>, breaks <text:line-break/> - those are fixed slots.
"""
import os

from lxml import etree

from .docx_format import PARSER
from .model import Document, Paragraph, SaveReport, Span, group_by_paragraph
from .package import read_package, write_package
from .slots import FixedSlot, Slot, apply_to_slots

TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
FO = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
DRAW = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
CONTENT_XML = "content.xml"
STYLES_XML = "styles.xml"


def t(tag):
    return "{%s}%s" % (TEXT, tag)


def tb(tag):
    return "{%s}%s" % (TABLE, tag)


class NodeSlot(Slot):
    """The .text or .tail of an element."""

    def __init__(self, owner, attr, fmt):
        Slot.__init__(self, getattr(owner, attr) or "")
        self.owner, self.attr, self.fmt = owner, attr, fmt

    def write(self, text):
        self.text = text
        setattr(self.owner, self.attr, text)


class OdtFixed(FixedSlot):
    def __init__(self, text, fmt):
        FixedSlot.__init__(self, text)
        self.fmt = fmt


def _text_styles(*roots):
    """style name -> (bold, italic, underline) with None for 'not set'."""
    styles = {}
    for root in roots:
        if root is None:
            continue
        for st in root.iter("{%s}style" % STYLE):
            props = st.find("{%s}text-properties" % STYLE)
            if props is None:
                continue
            weight = props.get("{%s}font-weight" % FO)
            italic = props.get("{%s}font-style" % FO)
            underline = props.get("{%s}text-underline-style" % STYLE)
            styles[st.get("{%s}name" % STYLE)] = (
                None if weight is None else (weight == "bold" or weight.isdigit() and int(weight) >= 600),
                None if italic is None else italic == "italic",
                None if underline is None else underline != "none")
    return styles


def _format(el, inherited, styles):
    own = styles.get(el.get(t("style-name")))
    if not own:
        return inherited
    return tuple(o if o is not None else i for o, i in zip(own, inherited))


def paragraph_slots(p, styles):
    slots, image = [], [False]

    def add(owner, attr, fmt):
        if getattr(owner, attr):
            slots.append(NodeSlot(owner, attr, fmt))

    def walk(el, fmt):
        add(el, "text", fmt)
        for child in el:
            if not isinstance(child.tag, str):
                add(child, "tail", fmt)
                continue
            if child.tag in (t("span"), t("a")):
                walk(child, _format(child, fmt, styles))
            elif child.tag == t("s"):
                slots.append(OdtFixed(" " * int(child.get(t("c"), "1")), fmt))
            elif child.tag == t("tab"):
                slots.append(OdtFixed("\t", fmt))
            elif child.tag == t("line-break"):
                slots.append(OdtFixed("\n", fmt))
            elif child.tag == "{%s}frame" % DRAW:
                image[0] = True
            add(child, "tail", fmt)  # notes, bookmarks, frames: their content is not paragraph text

    walk(p, _format(p, (False, False, False), styles))
    return slots, image[0]


def _nearest(el, tag):
    el = el.getparent()
    while el is not None and el.tag != tag:
        el = el.getparent()
    return el


def iter_paragraphs(office_text):
    """(text:p or text:h, table position or None, in a list) in document order."""
    tables = [0]

    def walk(container, position, in_list):
        for child in container:
            if child.tag in (t("p"), t("h")):
                yield child, position, in_list
            elif child.tag == t("list"):
                for item in child:
                    for found in walk(item, position, True):
                        yield found
            elif child.tag == tb("table"):
                number = tables[0]
                tables[0] += 1
                rows = [r for r in child.iter(tb("table-row")) if _nearest(r, tb("table")) is child]
                for r, row in enumerate(rows):
                    for c, cell in enumerate(row.findall(tb("table-cell"))):
                        for found in walk(cell, (number, r, c), False):
                            yield found
            elif child.tag == t("section"):
                for found in walk(child, position, in_list):
                    yield found

    return walk(office_text, None, False)


def _roots(blobs):
    content = etree.fromstring(blobs[CONTENT_XML], PARSER)
    styles = etree.fromstring(blobs[STYLES_XML], PARSER) if STYLES_XML in blobs else None
    return content, _text_styles(content, styles)


def _body(content):
    return content.find("{%s}body/{%s}text" % (OFFICE, OFFICE))


def read_odt(path):
    _, blobs = read_package(path)
    content, styles = _roots(blobs)
    paragraphs = []
    for p, position, in_list in iter_paragraphs(_body(content)):
        slots, image = paragraph_slots(p, styles)
        spans = []
        for slot in slots:
            fmt = tuple(bool(x) for x in slot.fmt)
            if spans and (spans[-1].bold, spans[-1].italic, spans[-1].underline) == fmt:
                spans[-1].text += slot.text
            else:
                spans.append(Span(slot.text, *fmt))
        if p.tag == t("h"):
            style = "h%d" % min(int(p.get(t("outline-level"), "1")), 3)
        else:
            style = "list" if in_list else "normal"
        paragraphs.append(Paragraph(spans, style, position, image))
    return Document(paragraphs, kind="odt", path=path, editable=False, saved_as="odt")


def save_odt(doc, replacements, dst):
    infos, blobs = read_package(doc.path)
    content, styles = _roots(blobs)
    paragraphs = [p for p, _, _ in iter_paragraphs(_body(content))]
    applied, skipped = 0, []
    for index, reps in group_by_paragraph(replacements).items():
        slots, _ = paragraph_slots(paragraphs[index], styles)
        for r in sorted(reps, key=lambda r: (r.start, r.end), reverse=True):
            if apply_to_slots(slots, r.start, r.end, r.text):
                applied += 1
            else:
                skipped.append(r)
    blobs[CONTENT_XML] = etree.tostring(content, xml_declaration=True, encoding="UTF-8")
    write_package(dst, infos, blobs)
    return SaveReport(dst, applied, sorted(skipped, key=lambda r: (r.paragraph, r.start)))
```

В `app/zhiraf/documents/opener.py`:
```python
from . import docx_format, odt_format, txt_format

READERS = {".txt": txt_format.read_txt, ".docx": docx_format.read_docx, ".odt": odt_format.read_odt}
SAVERS = {"txt": txt_format.save_txt, "docx": docx_format.save_docx, "odt": odt_format.save_odt}
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_odt.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents app/tests/docfactory.py app/tests/test_odt.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: read and save odt documents in place" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Текст из .doc без офисных программ

**Files:**
- Create: `app/zhiraf/documents/doc_format.py`
- Test: `app/tests/test_doc_text.py`

**Interfaces:**
- Produces: `extract_doc_text(path) -> list[str]` — абзацы основного текста документа Word 97–2003 (без колонтитулов и сносок): поля оставляют только видимый результат, ячейки таблиц — отдельные абзацы; `DocumentError` с понятным сообщением для не-Word файла и для защищённого паролем.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_doc_text.py`:
```python
import os
import subprocess

import pytest
from conftest import SOFFICE, needs_soffice
from docfactory import P, R, make_docx, table
from zhiraf.documents.doc_format import extract_doc_text
from zhiraf.documents.model import DocumentError


def to_doc(docx, outdir):
    profile = "file://" + str(outdir / "lo-profile")
    subprocess.run([SOFFICE, "--headless", "--norestore", "-env:UserInstallation=" + profile,
                    "--convert-to", "doc:MS Word 97", "--outdir", str(outdir), docx], check=True, timeout=180,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.splitext(docx)[0] + ".doc"


@needs_soffice
def test_paragraphs_and_table_cells(tmp_path):
    docx = make_docx(tmp_path / "a.docx", P(R("Первый абзац с информацией.")), P(R("Второй абзац.")),
                     table([[P(R("Ячейка А")), P(R("Ячейка Б"))]]))
    texts = [t for t in extract_doc_text(to_doc(docx, tmp_path)) if t.strip()]
    assert texts[:2] == ["Первый абзац с информацией.", "Второй абзац."]
    assert "Ячейка А" in texts and "Ячейка Б" in texts


@needs_soffice
def test_hyperlink_field_keeps_only_visible_text(tmp_path):
    link = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> HYPERLINK '
            '"http://example.org" </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + R("ссылка") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>')
    docx = make_docx(tmp_path / "a.docx", P(R("Это "), link, R(" здесь.")))
    texts = extract_doc_text(to_doc(docx, tmp_path))
    assert "Это ссылка здесь." in texts
    assert not any("HYPERLINK" in t for t in texts)


def test_not_a_word_file(tmp_path):
    bad = tmp_path / "не_ворд.doc"
    bad.write_bytes(b"plain text, not OLE")
    with pytest.raises(DocumentError) as e:
        extract_doc_text(str(bad))
    assert "не_ворд.doc" in str(e.value)
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_doc_text.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.documents.doc_format'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/documents/doc_format.py`:
```python
"""Word 97-2003 .doc.

With Word or LibreOffice on the computer a .doc is converted to .docx and back (task 9), keeping all
formatting. Without them only the text can be read: extract_doc_text follows the piece table of the
binary format ([MS-DOC]: FIB -> Clx -> PlcPcd) and keeps the visible text of the main document.
"""
import os
import struct

import olefile

from .model import DocumentError

FIB_FLAGS, FIB_CCP_TEXT, FIB_FC_CLX = 0x000A, 0x004C, 0x01A2
FLAG_ENCRYPTED, FLAG_TABLE1 = 0x0100, 0x0200
FIELD_BEGIN, FIELD_SEPARATE, FIELD_END = "\x13", "\x14", "\x15"
PARAGRAPH_ENDS = {"\r", "\x07", "\x0c"}         # paragraph, table cell / row, page or section break
DROPPED = {"\x01", "\x02", "\x08", "\x1f", "\x05"}  # picture, footnote mark, drawing, soft hyphen, comment
REPLACED = {"\x0b": "\n", "\x1e": "-", "\xa0": "\xa0"}


def _fail(path, why):
    return DocumentError("Не удалось открыть «%s»: %s." % (os.path.basename(path), why))


def _streams(path):
    try:
        ole = olefile.OleFileIO(path)
    except (OSError, IOError):
        raise _fail(path, "это не документ Word или файл повреждён")
    try:
        if not ole.exists("WordDocument"):
            raise _fail(path, "это не документ Word")
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, FIB_FLAGS)[0]
        if flags & FLAG_ENCRYPTED:
            raise _fail(path, "документ защищён паролем")
        name = "1Table" if flags & FLAG_TABLE1 else "0Table"
        if not ole.exists(name):
            raise _fail(path, "файл повреждён")
        return word, ole.openstream(name).read()
    finally:
        ole.close()


def _pieces(word, clx, path):
    i = 0
    while i < len(clx) and clx[i] == 0x01:             # Prc: direct formatting, skipped
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise _fail(path, "не удалось найти текст документа")
    size = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + size]
    n = (size - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        count = cps[k + 1] - cps[k]
        if fc & 0x40000000:                            # 8-bit (cp1252) piece
            start = (fc & 0x3FFFFFFF) // 2
            yield word[start:start + count].decode("cp1252", "replace")
        else:                                          # UTF-16 piece: Cyrillic text lives here
            yield word[fc:fc + 2 * count].decode("utf-16-le", "replace")


def _paragraphs(text):
    paragraphs, current, fields = [], [], []           # fields: "code" or "result" per open field
    for ch in text:
        if ch == FIELD_BEGIN:
            fields.append("code")
        elif ch == FIELD_SEPARATE:
            if fields:
                fields[-1] = "result"
        elif ch == FIELD_END:
            if fields:
                fields.pop()
        elif "code" in fields or ch in DROPPED:
            continue
        elif ch in PARAGRAPH_ENDS:
            paragraphs.append("".join(current))
            current = []
        else:
            current.append(REPLACED.get(ch, ch))
    if current:
        paragraphs.append("".join(current))
    return paragraphs


def extract_doc_text(path):
    word, table = _streams(path)
    ccp_text = struct.unpack_from("<i", word, FIB_CCP_TEXT)[0]
    fc_clx, lcb_clx = struct.unpack_from("<II", word, FIB_FC_CLX)
    text = "".join(_pieces(word, table[fc_clx:fc_clx + lcb_clx], path))
    return _paragraphs(text[:ccp_text])                # main document only: no headers, footnotes
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_doc_text.py -v
```
Expected: 3 passed (на машине разработки LibreOffice есть).

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents/doc_format.py app/tests/test_doc_text.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: extract text from doc files without office software" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: .doc через Word или LibreOffice, запасной путь — .docx

**Files:**
- Modify: `app/zhiraf/documents/doc_format.py`, `app/zhiraf/documents/opener.py`
- Test: `app/tests/test_doc_convert.py`

**Interfaces:**
- Consumes: `docx_format.read_docx/save_docx/write_docx_package/plain_paragraphs_xml`, `storage.tmp_dir`, `model.*`.
- Produces: `ConversionError`; классы `LibreOffice(soffice_path)` и `Word()` с методами `to_docx(src, outdir) -> str` и `to_doc(src_docx, dst) -> None`; `find_converter() -> Word | LibreOffice | None`; `open_doc(path, converter="auto") -> Document` (`kind="doc"`; с конвертером `saved_as="doc"`, `source={"docx", "converter", "tmpdir"}`; без него `saved_as="docx"`, `notice` с объяснением, `source={"text_only": True}`); `save_doc(doc, replacements, dst) -> SaveReport`. `opener.close_document` удаляет `tmpdir`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_doc_convert.py`:
```python
import os
import shutil

import pytest
from conftest import SOFFICE, needs_soffice
from docfactory import P, R, make_docx
from test_doc_text import to_doc
from zhiraf import storage
from zhiraf.documents import doc_format, opener
from zhiraf.documents.docx_format import read_docx
from zhiraf.documents.model import DocumentError, Replacement


@needs_soffice
def test_doc_round_trip_through_libreoffice(tmp_path):
    src = to_doc(make_docx(tmp_path / "Приказ.docx", P(R("Так же был ограничен размер."))), tmp_path)
    doc = doc_format.open_doc(src, converter=doc_format.LibreOffice(SOFFICE))
    assert doc.kind == "doc" and doc.saved_as == "doc" and doc.notice is None
    assert doc.paragraphs[0].text == "Так же был ограничен размер."
    report = opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith("Приказ (исправлено).doc") and report.applied == 1
    assert "Также был ограничен размер." in doc_format.extract_doc_text(report.path)
    tmpdir = doc.source["tmpdir"]
    opener.close_document(doc)
    assert not os.path.exists(tmpdir)


@needs_soffice
def test_without_office_text_is_saved_as_docx(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Так же был"))), tmp_path)
    doc = doc_format.open_doc(src, converter=None)
    assert doc.saved_as == "docx" and "как .docx" in doc.notice
    report = opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith(".docx")
    assert read_docx(report.path).paragraphs[0].text == "Также был"


class FailingConverter:
    name = "Сломанный"

    def to_docx(self, src, outdir):
        raise doc_format.ConversionError("timeout")


@needs_soffice
def test_failed_conversion_gives_message_and_cleans_temp(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Текст"))), tmp_path)
    with pytest.raises(DocumentError) as e:
        doc_format.open_doc(src, converter=FailingConverter())
    assert "a.doc" in str(e.value)
    assert os.listdir(storage.tmp_dir()) == []


def test_find_converter_uses_libreoffice_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/lo/soffice" if name == "soffice" else None)
    found = doc_format.find_converter()
    assert isinstance(found, doc_format.LibreOffice) and found.soffice == "/opt/lo/soffice"


def test_find_converter_none_without_office(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(doc_format, "_word_installed", lambda: False)
    monkeypatch.setattr(doc_format, "_installed_soffice", lambda: None)
    assert doc_format.find_converter() is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_doc_convert.py -v
```
Expected: FAIL — `AttributeError: module 'zhiraf.documents.doc_format' has no attribute 'open_doc'`.

- [ ] **Step 3: Реализация**

Дописать в `app/zhiraf/documents/doc_format.py` (импорты — к остальным в начало файла):
```python
import pathlib
import shutil
import subprocess
import sys
import tempfile

from .. import storage
from .docx_format import plain_paragraphs_xml, read_docx, save_docx, write_docx_package
from .model import Document, Paragraph, SaveReport, Span, apply_replacements, group_by_paragraph

NO_OFFICE_NOTICE = ("На компьютере нет Word и LibreOffice: оформление этого .doc сохранить не получится, "
                    "исправленная версия будет сохранена как .docx.")
WD_FORMAT_DOC, WD_FORMAT_DOCX = 0, 16


class ConversionError(Exception):
    pass


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


class LibreOffice:
    name = "LibreOffice"

    def __init__(self, soffice):
        self.soffice = soffice

    def _convert(self, src, target, outdir):
        profile = tempfile.mkdtemp(dir=storage.tmp_dir())  # never touch a LibreOffice the user has open
        cmd = [self.soffice, "--headless", "--norestore", "--nologo",
               "-env:UserInstallation=" + pathlib.Path(profile).as_uri(), "--convert-to", target, "--outdir", outdir, src]
        try:
            subprocess.run(cmd, check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **_no_window())
        except (subprocess.SubprocessError, OSError) as e:
            raise ConversionError(type(e).__name__)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + "." + target.split(":")[0])
        if not os.path.exists(out):
            raise ConversionError("no output")
        return out

    def to_docx(self, src, outdir):
        return self._convert(src, "docx", outdir)

    def to_doc(self, src_docx, dst):
        outdir = tempfile.mkdtemp(dir=storage.tmp_dir())
        try:
            shutil.move(self._convert(src_docx, "doc:MS Word 97", outdir), dst)
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


class Word:
    """Microsoft Word through COM, invisible to the user."""
    name = "Microsoft Word"

    def _save_as(self, src, dst, file_format):
        try:
            import comtypes.client
            word = comtypes.client.CreateObject("Word.Application")
        except Exception as e:  # COM errors are many and version-specific
            raise ConversionError(type(e).__name__)
        try:
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(os.path.abspath(src), False, True, False)  # no prompts, read-only, not in recent
            try:
                try:
                    document.SaveAs2(os.path.abspath(dst), file_format)
                except AttributeError:
                    document.SaveAs(os.path.abspath(dst), file_format)  # Word 2007
            finally:
                document.Close(False)
        except ConversionError:
            raise
        except Exception as e:
            raise ConversionError(type(e).__name__)
        finally:
            word.Quit()

    def to_docx(self, src, outdir):
        dst = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".docx")
        self._save_as(src, dst, WD_FORMAT_DOCX)
        return dst

    def to_doc(self, src_docx, dst):
        self._save_as(src_docx, dst, WD_FORMAT_DOC)


def _word_installed():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        return True
    except OSError:
        return False


def _installed_soffice():
    if sys.platform != "win32":
        return None
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramW6432")):
        for folder in ("LibreOffice", "LibreOffice 7", "LibreOffice 6", "OpenOffice 4", "OpenOffice.org 3"):
            exe = os.path.join(base or "", folder, "program", "soffice.exe")
            if base and os.path.exists(exe):
                return exe
    return None


def find_converter():
    """Word first (best fidelity), then LibreOffice; None when neither is installed."""
    if _word_installed():
        return Word()
    soffice = shutil.which("soffice") or _installed_soffice()
    return LibreOffice(soffice) if soffice else None


def open_doc(path, converter="auto"):
    if converter == "auto":
        converter = find_converter()
    if converter is None:
        texts = extract_doc_text(path)
        doc = Document([Paragraph([Span(t)]) for t in texts], kind="doc", path=path, editable=False,
                       saved_as="docx", notice=NO_OFFICE_NOTICE)
        doc.source = {"text_only": True}
        return doc
    tmpdir = tempfile.mkdtemp(dir=storage.tmp_dir())
    try:
        docx = converter.to_docx(path, tmpdir)
        inner = read_docx(docx)
    except (ConversionError, DocumentError):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise DocumentError("Не удалось открыть «%s» через %s. Попробуйте пересохранить его как .docx."
                            % (os.path.basename(path), converter.name))
    doc = Document(inner.paragraphs, kind="doc", path=path, editable=False, saved_as="doc")
    doc.source = {"docx": docx, "converter": converter, "tmpdir": tmpdir}
    return doc


def save_doc(doc, replacements, dst):
    if doc.source.get("text_only"):
        groups = group_by_paragraph(replacements)
        texts = [apply_replacements(p.text, groups.get(i, [])) for i, p in enumerate(doc.paragraphs)]
        if not dst.lower().endswith(".docx"):
            dst = os.path.splitext(dst)[0] + ".docx"
        write_docx_package(dst, plain_paragraphs_xml(texts))
        return SaveReport(dst, len(replacements))
    inner = Document(doc.paragraphs, kind="docx", path=doc.source["docx"])
    fixed = os.path.join(doc.source["tmpdir"], "исправлено.docx")
    report = save_docx(inner, replacements, fixed)
    if dst.lower().endswith(".docx"):
        shutil.copyfile(fixed, dst)
    else:
        try:
            doc.source["converter"].to_doc(fixed, dst)
        except ConversionError:
            raise DocumentError("Не удалось сохранить «%s» через %s. Сохраните как .docx."
                                % (os.path.basename(dst), doc.source["converter"].name))
    return SaveReport(dst, report.applied, report.skipped)
```

В `app/zhiraf/documents/opener.py`:
```python
from . import doc_format, docx_format, odt_format, txt_format

READERS = {".txt": txt_format.read_txt, ".docx": docx_format.read_docx, ".odt": odt_format.read_odt,
           ".doc": doc_format.open_doc}
SAVERS = {"txt": txt_format.save_txt, "docx": docx_format.save_docx, "odt": odt_format.save_odt,
          "doc": doc_format.save_doc}
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_doc_convert.py tests/test_doc_text.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/documents app/tests/test_doc_convert.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: open and save doc via word or libreoffice with docx fallback" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Потоковая проверка в движке

**Files:**
- Modify: `engine/spellcheck/checker.py` (класс `Checker`)
- Create: `app/tests/fakes.py`
- Test: `app/tests/test_engine_stream.py`

**Interfaces:**
- Consumes: существующие `comma_findings`, `form_findings`, `merge`, `rules`, `sage`, `EditTagger`, `prepare`.
- Produces (`spellcheck.checker`): `STAGES = ("rules", "commas", "forms", "sage")`; `STAGE_COST = {"rules": 0.003, "commas": 0.1, "forms": 0.1, "sage": 0.5}` (секунд на предложение на Windows 7); `visible_level(level, strict) -> str | None`; `Checker(models_dir, threads=2, process=None, factories=None, strict=False)`; `Checker.stream(sentences, context=None, stages=STAGES, should_stop=None)` — генератор `(stage, sentence_index, findings)`, по одному на каждое предложение и этап, позиции в символах исходного предложения; `Checker.check_document(...)` — прежнее поведение (объединённые находки). `factories` — словарь `{"sage": () -> obj.correct(text) -> str, "commas"/"forms": () -> obj.predict(text) -> list[dict]}`.
- Produces (`tests/fakes.py`): `FakeTagger(comma_after=(), forms=None, delay=0.0)`, `FakeSage(fixes=None)`, `make_factories()`, `make_slow_factories()`, `make_broken_factories()`.

- [ ] **Step 1: Подставные модели и падающие тесты**

`app/tests/fakes.py`:
```python
"""Stand-ins for the neural models: fast, deterministic, no model files."""
import time

from spellcheck.text import words_of


class FakeTagger:
    def __init__(self, comma_after=(), forms=None, delay=0.0):
        self.comma_after = set(comma_after)
        self.forms = forms or {}
        self.delay = delay

    def predict(self, text):
        if self.delay:
            time.sleep(self.delay)
        out = []
        for m in words_of(text):
            word = m.group(0)
            add = 0.95 if word in self.comma_after else 0.0
            label, p = self.forms.get(word, ("KEEP", 0.99))
            out.append({"comma": {"KEEP": 1.0 - add, "ADD": add, "DEL": 0.0}, "form": label, "form_p": p,
                        "form_keep_p": p if label == "KEEP" else 1.0 - p})
        return out


class FakeSage:
    def __init__(self, fixes=None):
        self.fixes = fixes or {}

    def correct(self, text):
        for wrong, right in self.fixes.items():
            text = text.replace(wrong, right)
        return text


def make_factories():
    return {"commas": lambda: FakeTagger(comma_after={"Документ"}),
            "forms": lambda: FakeTagger(forms={"информации": ("case:ablt", 0.95)}),
            "sage": lambda: FakeSage({"инфомационной": "информационной"})}


def make_slow_factories():
    factories = make_factories()
    factories["commas"] = lambda: FakeTagger(delay=0.3)
    return factories


def _broken():
    raise RuntimeError("model files are missing")


def make_broken_factories():
    factories = make_factories()
    factories["commas"] = _broken
    return factories
```

`app/tests/test_engine_stream.py`:
```python
from fakes import make_factories
from spellcheck.checker import STAGES, Checker, visible_level

SENTENCES = ["Так же был ограничен размер файлов.",
             "Документ определяющий порядок утверждён.",
             "Работа с информации ведётся.",
             "- Защита инфомационной системы обеспечена."]


def checker(models_dir, strict=False):
    return Checker(models_dir, factories=make_factories(), strict=strict)


def test_stages_run_in_order_one_result_per_sentence(models_dir):
    order = [(stage, i) for stage, i, _ in checker(models_dir).stream(SENTENCES)]
    assert order == [(s, i) for s in STAGES for i in range(len(SENTENCES))]


def test_findings_of_each_stage(models_dir):
    found = {}
    for stage, i, items in checker(models_dir).stream(SENTENCES):
        found.setdefault((stage, i), []).extend((f["rule"], f["level"], f["fix"]) for f in items)
    assert ("RULE_TAKZHE", "error", "Также") in found[("rules", 0)]
    assert ("MODEL_COMMA", "error", ",") in found[("commas", 1)]
    assert ("MODEL_FORM", "error", "информацией") in found[("forms", 2)]
    assert ("SAGE_TYPO", "error", "информационной") in found[("sage", 3)]


def test_positions_count_the_list_marker(models_dir):
    sage = [f for stage, i, items in checker(models_dir).stream(SENTENCES) if stage == "sage" for f in items]
    s = SENTENCES[3]
    assert [s[f["start"]:f["end"]] for f in sage] == ["инфомационной"]


def test_stop_ends_the_stream(models_dir):
    seen = []
    for stage, i, _ in checker(models_dir).stream(SENTENCES, should_stop=lambda: len(seen) >= 2):
        seen.append((stage, i))
    assert seen == [("rules", 0), ("rules", 1)]


def test_check_document_still_merges(models_dir):
    merged = checker(models_dir).check_document(SENTENCES)
    assert [f["rule"] for f in merged[0]] == ["RULE_TAKZHE"]


def test_strict_level_shows_only_in_strict_mode():
    assert visible_level("strict", False) is None
    assert visible_level("strict", True) == "check"
    assert visible_level("error", False) == "error" and visible_level("check", True) == "check"
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_engine_stream.py -v
```
Expected: FAIL — `ImportError: cannot import name 'STAGES' from 'spellcheck.checker'`.

- [ ] **Step 3: Реализация**

В `engine/spellcheck/checker.py` после констант порогов добавить:
```python
STAGES = ("rules", "commas", "forms", "sage")  # value per second of waiting: rules are instant, SAGE is slowest
STAGE_COST = {"rules": 0.003, "commas": 0.1, "forms": 0.1, "sage": 0.5}  # s/sentence, Windows 7 VM (job5)


def visible_level(level, strict):
    """'strict' findings (a rule that also hits legitimate capitals) are shown as 'check' only in strict mode."""
    if level == "strict":
        return "check" if strict else None
    return level
```

Заменить класс `Checker` целиком на:
```python
class Checker:
    def __init__(self, models_dir, threads=2, process=None, factories=None, strict=False):
        self.models_dir = models_dir
        self.threads = threads
        self.strict = strict
        self.lexicon = rules.Lexicon(None, os.path.join(models_dir, "vocab.tsv"))
        self.process = process  # psutil.Process for memory statistics, optional
        self.stats = {}
        self.factories = factories or {
            "sage": lambda: sage.Sage(os.path.join(models_dir, "sage"), threads),
            "commas": lambda: EditTagger(os.path.join(models_dir, "commas"), threads),
            "forms": lambda: EditTagger(os.path.join(models_dir, "forms"), threads),
        }

    def _stage(self, name, started):
        rss = self.process.memory_info().rss // 2 ** 20 if self.process else None
        self.stats[name] = {"seconds": round(time.perf_counter() - started, 1), "rss_mb": rss}

    def _stage_function(self, stage, sentences, context):
        if stage == "rules":
            ctx = rules.DocContext(context if context is not None else sentences, self.lexicon)
            return lambda body: [dict(f, rule="RULE_" + f["rule"]) for f in rules.check(body, self.lexicon, ctx)]
        model = self.factories[stage]()
        if stage == "sage":
            return lambda body: sage.findings(body, model.correct(body), self.lexicon)
        to_findings = comma_findings if stage == "commas" else form_findings
        return lambda body: to_findings(body, model.predict(body))

    def stream(self, sentences, context=None, stages=STAGES, should_stop=None):
        """Yield (stage, sentence index, findings) for every sentence and stage as soon as it is checked.

        Stages run one after another and load their model only for their own pass, so at most one
        model is in memory. Positions are chars of the original sentence (list marker included).
        """
        prepared = [prepare(s) for s in sentences]
        for stage in stages:
            started = time.perf_counter()
            check = self._stage_function(stage, sentences, context)
            for i, (marker, body) in enumerate(prepared):
                if should_stop is not None and should_stop():
                    return
                found = []
                for f in check(body):
                    level = visible_level(f["level"], self.strict)
                    if level is not None:
                        found.append(dict(f, level=level, start=f["start"] + len(marker), end=f["end"] + len(marker)))
                yield stage, i, found
            check = None  # release the model before the next one is loaded
            gc.collect()
            self._stage(stage, started)

    def check_document(self, sentences, context=None, stages=STAGES):
        """Merged findings for each sentence (evaluation, batch runs)."""
        found = [[] for _ in sentences]
        for _, i, items in self.stream(sentences, context, stages):
            found[i].extend(items)
        return [merge(f) for f in found]
```

- [ ] **Step 4: Тесты проходят; замеры движка по-прежнему работают**

```bash
../venv-app/bin/python -m pytest tests/test_engine_stream.py tests/test_constraints.py -v
```
Expected: 9 passed.

```bash
/home/general/vm/win7/venv-train/bin/python /home/general/vm/win7/engine/run_check.py /home/general/vm/win7/engine/models /home/general/vm/win7/payload5/testdocs.json /tmp/claude-1000/check-after-stream.json 2
```
Expected: в сводке `"errors": 33, "checks": 40` — как до изменения (порядок этапов не влияет на объединённый результат).

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add engine/spellcheck/checker.py app/tests/fakes.py app/tests/test_engine_stream.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: stream engine findings stage by stage with injectable models" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Прогресс и время до конца

**Files:**
- Create: `app/zhiraf/eta.py`
- Test: `app/tests/test_eta.py`

**Interfaces:**
- Produces: `Progress(n_sentences, stages, cost, clock=time.monotonic)`: `start()`, `sentence_done(stage)`, `fraction() -> float` (0..1, доля работы с весами этапов), `remaining_seconds() -> float | None` (None, пока мерить рано: прошло меньше 2 с или ничего не сделано), `finish_at(now=None) -> float | None` (время эпохи окончания).

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_eta.py`:
```python
import pytest

from zhiraf.eta import Progress

COST = {"rules": 0.0, "commas": 1.0, "sage": 3.0}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_fraction_weighs_stages_by_cost():
    p = Progress(10, ("rules", "commas", "sage"), COST, Clock())
    p.start()
    for _ in range(10):
        p.sentence_done("commas")
    assert p.fraction() == pytest.approx(10 / 40)


def test_remaining_uses_measured_speed():
    clock = Clock()
    p = Progress(10, ("commas", "sage"), COST, clock)
    p.start()
    for _ in range(10):
        p.sentence_done("commas")
    clock.now = 20.0  # twice as slow as the prior cost said
    assert p.remaining_seconds() == pytest.approx(60.0)
    assert p.finish_at(now=1000.0) == pytest.approx(1060.0)


def test_unknown_before_measuring():
    clock = Clock()
    p = Progress(5, ("commas",), COST, clock)
    assert p.remaining_seconds() is None
    p.start()
    p.sentence_done("commas")
    clock.now = 1.0
    assert p.remaining_seconds() is None


def test_done_and_empty_document():
    clock = Clock()
    p = Progress(0, ("commas",), COST, clock)
    p.start()
    assert p.fraction() == 1.0
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_eta.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.eta'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/eta.py`:
```python
"""How much of the check is done and when it will end, measured on this very computer."""
import time

MIN_SECONDS = 2.0  # before that the speed is noise (models are still loading)


class Progress:
    def __init__(self, n_sentences, stages, cost, clock=time.monotonic):
        self.n = n_sentences
        self.stages = list(stages)
        self.cost = dict(cost)
        self.clock = clock
        self.done = {s: 0 for s in self.stages}
        self.started = None

    def start(self):
        self.started = self.clock()

    def sentence_done(self, stage):
        self.done[stage] += 1

    def _units(self, counts):
        return sum(self.cost[s] * counts[s] for s in self.stages)

    def _total(self):
        return self._units({s: self.n for s in self.stages})

    def fraction(self):
        total = self._total()
        if total <= 0:
            return 1.0
        return min(1.0, self._units(self.done) / total)

    def remaining_seconds(self):
        done = self._units(self.done)
        if self.started is None or done <= 0:
            return None
        elapsed = self.clock() - self.started
        if elapsed < MIN_SECONDS:
            return None
        return max(0.0, (self._total() - done) * elapsed / done)

    def finish_at(self, now=None):
        remaining = self.remaining_seconds()
        if remaining is None:
            return None
        return (time.time() if now is None else now) + remaining
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_eta.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/eta.py app/tests/test_eta.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add check progress with measured time estimate" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Фоновый процесс проверки

**Files:**
- Create: `app/zhiraf/worker.py`
- Test: `app/tests/test_worker.py`

**Interfaces:**
- Consumes: `spellcheck.checker.Checker/STAGES/STAGE_COST`, `eta.Progress`.
- Produces: `CheckJob(models_dir, sentences, context=None, stages=None, strict=False, threads=2, factories=None)` — `factories` строка `"модуль:функция"`, возвращающая словарь фабрик (для тестов); методы `start()`, `poll(timeout=0.0) -> list[tuple]`, `stop()`, `close()`; поля `progress: Progress`, `finished: bool`, `error: tuple | None` (`(вид, текст)`, вид `memory` или `crash`), `stats: dict | None`. Сообщения: `("findings", stage, index, findings)`, `("done", stats)`, `("error", kind, text)`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_worker.py`:
```python
import time

from zhiraf.worker import CheckJob

SENTENCES = ["Так же был ограничен размер.", "Документ определяющий порядок утверждён.", "Работа с информации ведётся."]


def run(job, limit=60):
    job.start()
    messages, deadline = [], time.time() + limit
    while not job.finished and time.time() < deadline:
        messages += job.poll(timeout=0.2)
    job.close()
    assert job.finished, "the check did not finish in time"
    return messages


def test_all_stages_report_every_sentence(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_factories")
    messages = run(job)
    findings = [m for m in messages if m[0] == "findings"]
    assert len(findings) == 4 * len(SENTENCES)
    assert messages[-1][0] == "done" and job.error is None
    assert job.progress.fraction() == 1.0
    rules = [f["rule"] for m in findings if m[1] == "forms" for f in m[3]]
    assert rules == ["MODEL_FORM"]


def test_stop_finishes_early(models_dir):
    job = CheckJob(models_dir, SENTENCES * 5, factories="fakes:make_slow_factories")
    job.start()
    seen = []
    deadline = time.time() + 60
    while not job.finished and time.time() < deadline:
        for m in job.poll(timeout=0.1):
            seen.append(m)
            if m[0] == "findings" and m[1] == "commas":
                job.stop()
    job.close()
    commas = [m for m in seen if m[0] == "findings" and m[1] == "commas"]
    assert job.finished and 1 <= len(commas) < 15


def test_model_failure_is_reported(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_broken_factories")
    messages = run(job)
    assert job.error[0] == "crash" and messages[-1][0] == "error"


def test_silent_death_is_noticed(models_dir):
    job = CheckJob(models_dir, SENTENCES * 20, factories="fakes:make_slow_factories")
    job.start()
    job.poll(timeout=1.0)
    job._process.kill()  # as the OS does when memory runs out
    deadline = time.time() + 20
    while not job.finished and time.time() < deadline:
        job.poll(timeout=0.2)
    job.close()
    assert job.finished and job.error[0] == "crash"
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_worker.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.worker'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/worker.py`:
```python
"""The check runs in its own process: the window stays responsive and model memory is really freed."""
import importlib
import multiprocessing
import queue as queue_module
import traceback

from .eta import Progress

SILENT_DEATH = ("crash", "Проверка неожиданно прервалась (возможно, не хватило памяти).")


def _resolve(spec):
    module, function = spec.split(":")
    return getattr(importlib.import_module(module), function)


def _run(models_dir, sentences, context, stages, strict, threads, factories_spec, out, stop):
    try:
        import zhiraf  # noqa: F401  (puts the engine on sys.path in this process)
        from spellcheck.checker import Checker
        factories = _resolve(factories_spec)() if factories_spec else None
        checker = Checker(models_dir, threads, strict=strict, factories=factories)
        for stage, index, items in checker.stream(sentences, context, stages, should_stop=stop.is_set):
            out.put(("findings", stage, index, items))
        out.put(("done", checker.stats))
    except MemoryError:
        out.put(("error", "memory", "Не хватило памяти для проверки."))
    except Exception:
        out.put(("error", "crash", traceback.format_exc(limit=6)))


class CheckJob:
    def __init__(self, models_dir, sentences, context=None, stages=None, strict=False, threads=2, factories=None):
        import zhiraf  # noqa: F401
        from spellcheck.checker import STAGE_COST, STAGES
        self.stages = tuple(stages or STAGES)
        ctx = multiprocessing.get_context("spawn")
        self._queue = ctx.Queue()
        self._stop = ctx.Event()
        args = (models_dir, list(sentences), None if context is None else list(context), self.stages, strict,
                threads, factories, self._queue, self._stop)
        self._process = ctx.Process(target=_run, args=args, daemon=True)
        self.progress = Progress(len(sentences), self.stages, STAGE_COST)
        self.finished = False
        self.error = None
        self.stats = None

    def start(self):
        self.progress.start()
        self._process.start()

    def _note(self, message):
        if message[0] == "findings":
            self.progress.sentence_done(message[1])
        elif message[0] == "done":
            self.finished, self.stats = True, message[1]
        elif message[0] == "error":
            self.finished, self.error = True, (message[1], message[2])

    def _drain(self, timeout):
        messages = []
        try:
            message = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
            while True:
                self._note(message)
                messages.append(message)
                message = self._queue.get_nowait()
        except queue_module.Empty:
            pass
        return messages

    def poll(self, timeout=0.0):
        messages = self._drain(timeout)
        if not messages and not self.finished and not self._process.is_alive():
            messages = self._drain(0.5)  # the last messages may still be in the pipe
            if not self.finished:
                self.finished, self.error = True, SILENT_DEATH
                messages.append(("error",) + SILENT_DEATH)
        return messages

    def stop(self):
        self._stop.set()

    def close(self):
        self._process.join(timeout=5)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_worker.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/worker.py app/tests/test_worker.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: run checks in a background process with progress and stop" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Разбор пометок

**Files:**
- Create: `app/zhiraf/review.py`
- Test: `app/tests/test_review.py`

**Interfaces:**
- Consumes: `documents.model.Replacement/apply_replacements`; словарь — любой объект с `__contains__(word)` и `add(word)` (`storage.Dictionary`).
- Produces: константы статусов `OPEN, ACCEPTED, MANUAL, SKIPPED, DICTIONARY`; `Mark` (поля `id, paragraph, start, end, level, rule, fix, message, original, status, applied`; свойства `rank`, `can_add_to_dictionary`); `Edit(paragraph, start, end, text)` — изменение ТЕКУЩЕГО текста абзаца, которое окно повторяет у себя; `ReviewSession(paragraphs, dictionary=None)`:
  - `add_findings(paragraph, offset, findings) -> list[Mark]` — находки предложения, начинающегося с `offset` в исходном тексте абзаца;
  - `marks`, `current`, `open_marks()`, `go_next()`, `go_prev()`, `select(mark_id)`;
  - `accept() -> list[Edit]`, `manual(text) -> list[Edit]`, `skip() -> list[Edit]`, `add_to_dictionary() -> str | None`, `accept_all_errors() -> list[Edit]`, `undo() -> list[Edit]`;
  - `text(paragraph) -> str`, `span(mark) -> (start, end)` в текущем тексте, `to_current(paragraph, pos, exclude=None) -> int`;
  - `counts() -> {"errors", "checks", "fixed", "skipped", "dictionary", "total"}`, `replacements() -> list[Replacement]`, `replace_paragraph(paragraph, new_text)`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_review.py`:
```python
from zhiraf.review import ACCEPTED, DICTIONARY, MANUAL, OPEN, SKIPPED, ReviewSession
from zhiraf.storage import Dictionary

TEXT = "Так же сотрудники с информации работают"


def f(start, end, fix, level="error", rule="MODEL_FORM", message="m"):
    return {"start": start, "end": end, "fix": fix, "level": level, "rule": rule, "message": message}


def session(text=TEXT, dictionary=None):
    s = ReviewSession([text, "Второй абзац текста"], dictionary)
    s.add_findings(0, 0, [f(0, 6, "Также", rule="RULE_TAKZHE"), f(17, 17, ",", rule="MODEL_COMMA"),
                          f(20, 30, "информацией")])
    return s


def test_marks_are_ordered_and_first_is_current():
    s = session()
    assert [(m.start, m.end) for m in s.marks] == [(0, 6), (17, 17), (20, 30)]
    assert s.current is s.marks[0] and s.marks[0].original == "Так же"


def test_accept_moves_on_and_shifts_later_marks():
    s = session()
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(0, 6, "Также")]
    assert s.current is s.marks[1]
    assert s.span(s.marks[1]) == (16, 16)
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(16, 16, ",")]
    edits = s.accept()
    assert [(e.start, e.end, e.text) for e in edits] == [(20, 30, "информацией")]
    assert s.text(0) == "Также сотрудники, с информацией работают"
    assert s.current is None and s.counts()["fixed"] == 3


def test_skip_marks_and_counts():
    s = session()
    s.skip()
    assert s.marks[0].status == SKIPPED and s.current is s.marks[1]
    c = s.counts()
    assert (c["errors"], c["skipped"], c["total"]) == (2, 1, 3)


def test_manual_fix_and_replacements_in_original_coordinates():
    s = session()
    s.go_next()
    s.go_next()
    s.manual("сведениями")
    assert s.marks[2].status == MANUAL and s.text(0) == "Так же сотрудники с сведениями работают"
    assert [(r.paragraph, r.start, r.end, r.text) for r in s.replacements()] == [(0, 20, 30, "сведениями")]


def test_undo_reverts_text_and_status():
    s = session()
    s.accept()
    s.accept()
    edits = s.undo()
    assert [(e.start, e.end, e.text) for e in edits] == [(16, 17, "")]
    assert s.marks[1].status == OPEN and s.current is s.marks[1]
    assert s.text(0) == "Также сотрудники с информации работают"


def test_accept_all_errors_is_one_undo_step():
    s = session()
    s.add_findings(1, 0, [f(0, 6, "Вторый", level="check")])
    edits = s.accept_all_errors()
    assert len(edits) == 3 and s.text(0) == "Также сотрудники, с информацией работают"
    assert s.counts()["checks"] == 1 and s.current is s.marks[3]
    s.undo()
    assert s.text(0) == TEXT and s.counts()["errors"] == 3


def test_navigation_wraps_and_skips_handled():
    s = session()
    s.go_next()
    s.skip()
    assert s.current.start == 20
    assert s.go_next().start == 0      # wraps to the first still open
    assert s.go_prev().start == 20


def test_add_to_dictionary_resolves_same_word_everywhere(tmp_path):
    d = Dictionary(str(tmp_path / "d.txt"))
    s = ReviewSession(["Слово ИСПДн и опять ИСПДн тут"], d)
    s.add_findings(0, 0, [f(6, 11, None, level="check", rule="RULE_TYPO"), f(20, 25, None, level="check", rule="RULE_TYPO")])
    assert s.add_to_dictionary() == "ИСПДн"
    assert "испдн" in d and [m.status for m in s.marks] == [DICTIONARY, DICTIONARY]


def test_dictionary_words_are_not_marked(tmp_path):
    d = Dictionary(str(tmp_path / "d.txt"))
    d.add("ИСПДн")
    s = ReviewSession(["Система ИСПДн работает"], d)
    assert s.add_findings(0, 0, [f(8, 13, None, level="check", rule="RULE_TYPO")]) == []


def test_comma_marks_cannot_go_to_dictionary():
    s = session()
    s.go_next()
    assert s.current.rule == "MODEL_COMMA" and s.add_to_dictionary() is None


def test_late_finding_on_a_handled_place_is_dropped():
    s = session()
    s.accept()                                    # "Так же" -> "Также"
    s.skip()                                      # the comma
    late = s.add_findings(0, 0, [f(0, 3, "Как", rule="SAGE_TYPO"), f(17, 17, ",", rule="MODEL_COMMA")])
    assert late == [] and len(s.marks) == 3


def test_better_finding_replaces_open_one_in_the_same_place():
    s = ReviewSession(["с информации работают"])
    s.add_findings(0, 0, [f(2, 12, "информацией", level="check")])
    s.add_findings(0, 0, [f(2, 12, "информацией", level="error", rule="SAGE_TYPO")])
    assert [(m.level, m.rule) for m in s.marks] == [("error", "SAGE_TYPO")] and s.current is s.marks[0]


def test_offsets_of_a_later_sentence():
    s = ReviewSession(["Первое предложение. Так же второе."])
    s.add_findings(0, 20, [f(0, 6, "Также", rule="RULE_TAKZHE")])
    assert s.marks[0].original == "Так же"


def test_replace_paragraph_forgets_its_marks():
    s = session()
    s.accept()
    s.replace_paragraph(0, "Совсем новый текст")
    assert s.marks == [] and s.current is None and s.text(0) == "Совсем новый текст"
    assert s.undo() == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_review.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'zhiraf.review'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/review.py`:
```python
"""Reviewing one document's marks: what is open, accepted, skipped; navigation; undo.

Pure Python, no Qt: the window shows what this session says and calls its methods.
Mark positions are kept in the coordinates of the ORIGINAL paragraph text (the text the check ran
on); the current text is the original with the accepted fixes applied.
"""
from dataclasses import dataclass
from typing import Optional

from .documents.model import Replacement, apply_replacements

OPEN, ACCEPTED, MANUAL, SKIPPED, DICTIONARY = "open", "accepted", "manual", "skipped", "dictionary"
APPLIED = (ACCEPTED, MANUAL)
LEVEL_RANK = {"error": 2, "check": 1}
SOURCE_RANK = {"SAGE": 3, "RULE": 2, "MODEL": 1}
DICTIONARY_RULES = {"RULE_TYPO", "RULE_MIXED_SCRIPT", "RULE_LATIN_HYPHEN", "RULE_NE_JOIN", "SAGE_TYPO", "SAGE_JOIN"}


@dataclass
class Mark:
    id: int
    paragraph: int
    start: int
    end: int
    level: str
    rule: str
    fix: Optional[str]
    message: str
    original: str
    status: str = OPEN
    applied: Optional[str] = None

    @property
    def rank(self):
        return LEVEL_RANK[self.level], SOURCE_RANK.get(self.rule.split("_")[0], SOURCE_RANK["RULE"])

    @property
    def can_add_to_dictionary(self):
        return self.rule in DICTIONARY_RULES and bool(self.original.strip())


@dataclass
class Edit:
    """A change of the CURRENT paragraph text that the window repeats in its view."""
    paragraph: int
    start: int
    end: int
    text: str


def _overlaps(a_start, a_end, b_start, b_end):
    if a_start == a_end and b_start == b_end:
        return a_start == b_start
    if a_start == a_end:
        return b_start < a_start < b_end   # an insertion meets a span only strictly inside it
    if b_start == b_end:
        return a_start < b_start < a_end
    return a_start < b_end and b_start < a_end


def _key(mark):
    return mark.paragraph, mark.start, mark.end, mark.id


class ReviewSession:
    def __init__(self, paragraphs, dictionary=None):
        self.originals = list(paragraphs)
        self.dictionary = dictionary
        self.marks = []
        self.current = None
        self._next_id = 1
        self._undo = []  # groups of (mark, previous status, previous applied)

    # --- findings arriving from the check ---

    def add_findings(self, paragraph, offset, findings):
        added = []
        text = self.originals[paragraph]
        for f in findings:
            if f.get("level") not in LEVEL_RANK:
                continue
            start, end = offset + f["start"], offset + f["end"]
            original = text[start:end]
            if self.dictionary is not None and original.strip() and original.strip() in self.dictionary:
                continue
            clash = [m for m in self.marks if m.paragraph == paragraph and _overlaps(start, end, m.start, m.end)]
            if any(m.status != OPEN for m in clash):
                continue  # the reader has already decided about this place
            mark = Mark(self._next_id, paragraph, start, end, f["level"], f["rule"], f.get("fix"),
                        f.get("message", ""), original)
            if any(m.rank >= mark.rank for m in clash):
                continue
            self._next_id += 1
            for m in clash:
                if self.current is m:
                    self.current = mark
                self.marks.remove(m)
            self.marks.append(mark)
            added.append(mark)
        self.marks.sort(key=_key)
        if self.current is None:
            self.current = next((m for m in self.marks if m.status == OPEN), None)
        return added

    # --- navigation ---

    def open_marks(self):
        return [m for m in self.marks if m.status == OPEN]

    def go_next(self):
        opens = self.open_marks()
        if not opens:
            self.current = None
        elif self.current is None:
            self.current = opens[0]
        else:
            after = [m for m in opens if _key(m) > _key(self.current)]
            self.current = after[0] if after else opens[0]
        return self.current

    def go_prev(self):
        opens = self.open_marks()
        if not opens:
            self.current = None
        elif self.current is None:
            self.current = opens[-1]
        else:
            before = [m for m in opens if _key(m) < _key(self.current)]
            self.current = before[-1] if before else opens[-1]
        return self.current

    def select(self, mark_id):
        mark = next((m for m in self.marks if m.id == mark_id), None)
        if mark is not None and mark.status == OPEN:
            self.current = mark
        return mark

    # --- decisions ---

    def _change(self, marks, status, texts):
        group, edits = [], []
        for mark, text in zip(marks, texts):
            if status in APPLIED:
                start = self.to_current(mark.paragraph, mark.start)
                edits.append(Edit(mark.paragraph, start, start + mark.end - mark.start, text))
            group.append((mark, mark.status, mark.applied))
            mark.status, mark.applied = status, (text if status in APPLIED else None)
        if group:
            self._undo.append(group)
        return edits

    def accept(self):
        mark = self.current
        if mark is None or mark.fix is None:
            return []
        edits = self._change([mark], ACCEPTED, [mark.fix])
        self.go_next()
        return edits

    def manual(self, text):
        mark = self.current
        if mark is None:
            return []
        edits = self._change([mark], MANUAL, [text])
        self.go_next()
        return edits

    def skip(self):
        mark = self.current
        if mark is None:
            return []
        self._change([mark], SKIPPED, [None])
        self.go_next()
        return []

    def add_to_dictionary(self):
        mark = self.current
        if mark is None or not mark.can_add_to_dictionary:
            return None
        word = mark.original.strip()
        if self.dictionary is not None:
            self.dictionary.add(word)
        same = [m for m in self.marks
                if m.status == OPEN and m.can_add_to_dictionary and m.original.strip().lower() == word.lower()]
        self._change(same, DICTIONARY, [None] * len(same))
        self.go_next()
        return word

    def accept_all_errors(self):
        targets = [m for m in self.marks if m.status == OPEN and m.level == "error" and m.fix is not None]
        edits = self._change(targets, ACCEPTED, [m.fix for m in targets])
        if self.current is not None and self.current.status != OPEN:
            self.go_next()
        return edits

    def undo(self):
        if not self._undo:
            return []
        group = self._undo.pop()
        edits = []
        for mark, status, applied in reversed(group):
            if mark.status in APPLIED:
                start = self.to_current(mark.paragraph, mark.start, exclude=mark)
                edits.append(Edit(mark.paragraph, start, start + len(mark.applied), mark.original))
            mark.status, mark.applied = status, applied
        reopened = [m for m, _, _ in group if m.status == OPEN]
        if reopened:
            self.current = min(reopened, key=_key)
        return edits

    # --- text and positions ---

    def to_current(self, paragraph, pos, exclude=None):
        shift = 0
        for m in self.marks:
            if m.paragraph == paragraph and m.status in APPLIED and m is not exclude and m.end <= pos:
                shift += len(m.applied) - (m.end - m.start)
        return pos + shift

    def span(self, mark):
        start = self.to_current(mark.paragraph, mark.start, exclude=mark)
        length = len(mark.applied) if mark.status in APPLIED else mark.end - mark.start
        return start, start + length

    def text(self, paragraph):
        return apply_replacements(self.originals[paragraph],
                                  [r for r in self.replacements() if r.paragraph == paragraph])

    def replacements(self):
        return [Replacement(m.paragraph, m.start, m.end, m.applied) for m in self.marks if m.status in APPLIED]

    def counts(self):
        statuses = [(m.status, m.level) for m in self.marks]
        return {"errors": statuses.count((OPEN, "error")), "checks": statuses.count((OPEN, "check")),
                "fixed": sum(1 for s, _ in statuses if s in APPLIED),
                "skipped": sum(1 for s, _ in statuses if s == SKIPPED),
                "dictionary": sum(1 for s, _ in statuses if s == DICTIONARY), "total": len(statuses)}

    def replace_paragraph(self, paragraph, new_text):
        """The reader typed in this paragraph (pasted text only): its marks and their history go away."""
        self.originals[paragraph] = new_text
        gone = [m for m in self.marks if m.paragraph == paragraph]
        self.marks = [m for m in self.marks if m.paragraph != paragraph]
        self._undo = [[e for e in group if e[0] not in gone] for group in self._undo]
        self._undo = [group for group in self._undo if group]
        if self.current in gone:
            self.current = None
            self.go_next()
```

- [ ] **Step 4: Тесты проходят**

```bash
../venv-app/bin/python -m pytest tests/test_review.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/review.py app/tests/test_review.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add review session with navigation, decisions and undo" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Консольная команда — всё ядро целиком

**Files:**
- Create: `app/zhiraf/cli.py`, `app/zhiraf/__main__.py`
- Test: `app/tests/test_cli.py`

**Interfaces:**
- Consumes: всё выше.
- Produces: `plan_sentences(paragraphs) -> (sentences, where)` (`where[i] = (абзац, начало предложения)`); `check_file(path, models, accept_errors=False, out=None, factories=None, stages=None, threads=2, report=None) -> dict` (`counts`, `saved`, `applied`, `not_applied`, `notice`); `main(argv=None) -> int`. Запуск: `python -m zhiraf.cli check <файл> [--accept-errors] [--out путь] [--models папка]`.

- [ ] **Step 1: Написать падающие тесты**

`app/tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Убедиться, что тесты падают**

```bash
../venv-app/bin/python -m pytest tests/test_cli.py -v
```
Expected: FAIL — `ImportError: cannot import name 'cli'`.

- [ ] **Step 3: Реализация**

`app/zhiraf/cli.py`:
```python
"""Check a document from the command line (and the whole core end to end):

    python -m zhiraf.cli check <file> [--accept-errors] [--out path] [--models folder]
"""
import argparse
import sys
import time

from . import models_dir as default_models_dir
from . import storage
from .documents.model import DocumentError
from .documents.opener import close_document, open_document, save_document
from .review import ReviewSession
from .segment import split_sentences
from .worker import CheckJob


def plan_sentences(paragraphs):
    sentences, where = [], []
    for index, text in enumerate(paragraphs):
        for start, end in split_sentences(text):
            sentences.append(text[start:end])
            where.append((index, start))
    return sentences, where


def check_file(path, models, accept_errors=False, out=None, factories=None, stages=None, threads=2, report=None):
    storage.clean_tmp()
    settings = storage.Settings()
    doc = open_document(path)
    try:
        paragraphs = [p.text for p in doc.paragraphs]
        sentences, where = plan_sentences(paragraphs)
        session = ReviewSession(paragraphs, storage.Dictionary())
        job = CheckJob(models, sentences, context=sentences, stages=stages, strict=settings["strict_mode"],
                       threads=threads, factories=factories)
        job.start()
        try:
            while not job.finished:
                for message in job.poll(timeout=0.5):
                    if message[0] == "findings":
                        paragraph, offset = where[message[2]]
                        session.add_findings(paragraph, offset, message[3])
                if report is not None:
                    report(job.progress)
        finally:
            job.close()
        if job.error is not None:
            raise RuntimeError(job.error[1])
        if accept_errors:
            session.accept_all_errors()
        saved = save_document(doc, session.replacements(), out)
        counts = session.counts()
        storage.Recent(settings).touch(path, {"fixed": counts["fixed"], "skipped": counts["skipped"],
                                              "handled": counts["total"] - counts["errors"] - counts["checks"],
                                              "total": counts["total"]})
        return {"counts": counts, "saved": saved.path, "applied": saved.applied,
                "not_applied": len(saved.skipped), "notice": doc.notice}
    finally:
        close_document(doc)


def _progress_line(progress):
    remaining = progress.remaining_seconds()
    tail = "" if remaining is None else " · осталось ≈ %d мин" % max(1, round(remaining / 60))
    sys.stderr.write("\rПроверено %d%%%s   " % (round(progress.fraction() * 100), tail))
    sys.stderr.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zhiraf")
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser("check", help="проверить документ и сохранить исправленную копию")
    check.add_argument("path")
    check.add_argument("--accept-errors", action="store_true", help="принять все уверенные исправления")
    check.add_argument("--out", default=None)
    check.add_argument("--models", default=None)
    check.add_argument("--factories", default=None, help=argparse.SUPPRESS)  # tests: fake models
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help()
        return 1
    started = time.time()
    try:
        result = check_file(args.path, args.models or default_models_dir(), args.accept_errors, args.out,
                            factories=args.factories, report=_progress_line)
    except DocumentError as e:
        sys.stderr.write("\n%s\n" % e)
        return 2
    c = result["counts"]
    sys.stderr.write("\n")
    print("Ошибки: %d · Проверить: %d · Исправлено: %d · Пропущено: %d" % (c["errors"], c["checks"], c["fixed"],
                                                                          c["skipped"]))
    if result["not_applied"]:
        print("Не удалось применить исправлений: %d (мешает табуляция или разрыв строки)" % result["not_applied"])
    if result["notice"]:
        print(result["notice"])
    print("Сохранено: %s (%.0f с)" % (result["saved"], time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`app/zhiraf/__main__.py`:
```python
import sys

from .cli import main

sys.exit(main())
```

- [ ] **Step 4: Тесты проходят — весь набор**

```bash
../venv-app/bin/python -m pytest -v
```
Expected: все тесты, кроме помеченных `slow`, проходят.

- [ ] **Step 5: Проверка на настоящих моделях**

```bash
../venv-app/bin/python -m pytest -m slow -v
```
Expected: 1 passed (примерно минута: загрузка SAGE и двух моделей).

```bash
../venv-app/bin/python -m zhiraf.cli check "/home/general/Downloads/05-Tekhnicheskiy_proekt.docx" --accept-errors --out /tmp/claude-1000/tp-check.docx
```
Expected: прогресс «Проверено N% · осталось ≈ M мин», затем сводка «Ошибки … Исправлено …» и путь к копии. Если файла нет в Downloads, взять любой из `~/Downloads/*.docx`. Открыть результат в LibreOffice (`soffice /tmp/claude-1000/tp-check.docx`) и убедиться глазами, что оформление на месте.

- [ ] **Step 6: Commit**

```bash
git -C /home/general/vm/win7 add app/zhiraf/cli.py app/zhiraf/__main__.py app/tests/test_cli.py
```
```bash
git -C /home/general/vm/win7 commit -m "feat: add command line check that runs the whole core" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## После этого плана

- План 2 — окно на Qt (PySide2 5.15.2.1): стартовый экран, область текста с пометками, широкая карточка, строка состояния и прогресс, вставка с оформлением и «Скопировать с оформлением», «Сохранить как» (.docx/.odt/.pdf/.txt), словарь и настройки, F1. Окно использует только интерфейсы этого плана: `open_document/save_document/close_document`, `plan_sentences`, `CheckJob`, `ReviewSession`, `storage.*`.
- План 3 — сборка папки «Жираф.Корректор» для Windows 7 (встраиваемый Python, колёса, библиотеки Visual C++, модели, запускатель .exe), проверка отсутствия сетевого кода в собранной папке и сквозной прогон в виртуальной машине.
