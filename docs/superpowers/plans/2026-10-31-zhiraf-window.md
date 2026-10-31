# Жираф.Корректор — окно на Qt (план 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Окно программы на PySide2 поверх готового ядра (план 1): стартовый экран, текст с пометками, широкая карточка, строка состояния с прогрессом, вставка и открытие документов, сохранение, словарь и настройки, F1.

**Architecture:** Окно (`app/zhiraf/ui/`) не знает форматов и моделей: оно показывает то, что говорит `ReviewSession`, и вызывает её методы. Проверка идёт в дочернем процессе (`CheckJob`), окно раз в 50 мс забирает сообщения таймером Qt в главном потоке — отдельных потоков для проверки нет. Единственный поток окна — открытие файла (`OpenTask`, QThread), потому что `.doc` через Word/LibreOffice бывает долгим. Формат структуры документа (заголовок, ячейка таблицы, пункт списка) идёт в движок необязательным списком `structure` рядом с предложениями; без него движок работает как раньше.

**Tech Stack:** Python 3.7 (Win7) / 3.8 (venv-app здесь), PySide2 5.15.2.1 (QtCore, QtGui, QtWidgets, QtSvg, QtPrintSupport; QtNetwork запрещён), pytest-qt 4.2.0 с `QT_QPA_PLATFORM=offscreen`, lxml (уже есть).

**Spec:** `docs/superpowers/specs/2026-10-04-zhiraf-korrektor-design.md` (разделы 4, 5, 6, 7, 9, 10). Ядро: `docs/superpowers/plans/2026-10-05-zhiraf-core.md`, код в `app/zhiraf/`. Работать в отдельном worktree `/home/general/vm/win7-window`, ветка `feat/23-window` от `main`. Все команды — из `app/`, интерпретатор `../venv-app/bin/python`.

## Global Constraints

- Весь код `app/zhiraf/**` совместим с Python 3.7 (тест `test_sources_run_on_python37` через vermin уже проверяет и папку `ui/`): без `:=`, без позиционных-только параметров, без `list[int]`.
- PySide2 закреплён: `PySide2==5.15.2.1` и `shiboken2==5.15.2.1` (проверено: есть колёса `cp37 win_amd64` и `cp38 manylinux1`; Qt 5.15 работает на Windows 7). PySide2 для Linux и для Windows ставится одной командой из `requirements-gui.txt`.
- Ни строки сетевого кода: нельзя импортировать `QtNetwork`, `QtWebEngine*`, `QtQml`, `QtMultimedia`; `QLocalServer` тоже нельзя (он в QtNetwork). Существующий AST-тест `test_sources_import_no_network_modules` обязан проходить; в Task 3 он расширяется на эти имена.
- Текст документов не пишется на диск, кроме файлов, которые человек сам сохраняет, и временных копий в `tmp`. Журнал (`журнал.txt`) содержит только имя класса исключения и `файл:строка:функция` (`worker.safe_error_detail`), никогда текст документа, никогда `str(exc)`.
- Окно остаётся лёгким: процесс окна не импортирует `onnxruntime`, `tokenizers`, `numpy`, `spellcheck.checker` (модели грузит только дочерний процесс; пик движка ≈ 1,3 ГБ). Проверяется тестом в Task 14.
- Тексты интерфейса — по-русски, без технических слов (не «процесс», «поток», «исключение», «кэш», «парсинг»; говорить «проверка», «документ», «пометка»).
- Цвета: ночное небо `#56708f`, бумага `#f6f3ec`, чернила `#26303b`, лунный свет `#fbf7e9`, ошибка `#b9524a`, проверьте `#d9a521`, исправлено `#3f9a4e`, пропущено `#8792a2`.
- Значки статусов: ✕ ошибка (кирпичный), ⚠ проверить (жёлтый), ✓ исправлено (галочка в кружке, зелёный), ↷ пропущено (серый); текст подписи — цвета значка.
- Кнопка «Принять все ошибки» всегда на экране (убрать нельзя: ни настройкой, ни меню; при нуле ошибок она выключена, но видна), внутри неё значок «?», подсказка ровно: `Исправит все ошибки (сейчас N). Пометки «проверить» останутся.`
- Оригинал документа никогда не перезаписывается; копия «Имя (исправлено).ext» рядом с ним.
- Форматы: открывать `.docx .doc .odt .txt` (и вставка из буфера); интеграции с Word нет.

## Review Focus

Входы, которых нет в спеке, но которые встретит человек (тест каждого лежит в указанной задаче):

1. Пустая вставка или документ без единого предложения (только пробелы, пустой `.docx`): проверка не запускается, человек видит «В документе нет текста для проверки», а не вечный прогресс 0% — Task 9, Task 12.
2. Человек правит абзац вставленного текста, пока идёт проверка: запоздавшие пометки для этого абзаца отбрасываются (версия абзаца), абзац перепроверяется после основного прохода — Task 8.
3. Документ закрыли, открыли другой или закрыли окно, пока идёт проверка или открытие: дочерний процесс завершается, запоздавшие сообщения не попадают в новую сессию — Task 8, Task 12.
4. Сохранение не удалось (папка только для чтения, файл открыт в Word), «Сохранить как» на сам исходный файл, перезапись чужого файла: понятное сообщение/подтверждение, недописанных файлов не остаётся — Task 10, Task 12.
5. Очень длинный документ (3000 абзацев, 2000 пометок): «Принять все ошибки» и поток пометок не подвешивают окно (перерисовка по абзацам одним блоком, не более 500 сообщений за такт) — Task 5, Task 8.
6. Сбой дочернего процесса посреди проверки: найденное остаётся, «Проверка прервана» с кнопкой «Продолжить с этого места», продолжение не дублирует пометки — Task 8.
7. Абзацы с `\n`, `\t`, U+2028 и «Яблоко🍎» (символы вне BMP): позиции пометок совпадают с текстом абзаца (в блок пишется строка той же длины) — Task 5.

## File Structure

```
app/requirements-gui.txt            PySide2==5.15.2.1, shiboken2==5.15.2.1 (рантайм окна)
app/requirements-dev.txt            + pytest-qt==4.2.0 (в него же: -r requirements-gui.txt)
app/zhiraf/storage.py               (правка) откат при сбое записи; tmp по PID
app/zhiraf/segment.py               (правка) sentence_kinds
app/zhiraf/worker.py, cli.py        (правка) structure
engine/spellcheck/rules.py          (правка) kind у DocContext и check
engine/spellcheck/checker.py        (правка) structure в stream/check_document
app/zhiraf/ui/__init__.py
app/zhiraf/ui/theme.py              цвета, значки (SVG), стили, art_path
app/zhiraf/ui/runs.py               чистая модель показа: куски текста с форматом и пометкой
app/zhiraf/ui/editor.py             ReviewEditor — текст на «бумаге»
app/zhiraf/ui/card.py               MarkCard — широкая карточка, card_position
app/zhiraf/ui/status.py             StatusPanel, ProgressPanel, NoticeBar, progress_text
app/zhiraf/ui/controller.py         CheckController — жизнь проверки в окне
app/zhiraf/ui/loader.py             OpenTask — открытие файла в потоке
app/zhiraf/ui/clipboard.py          вставка с оформлением, «Скопировать с оформлением»
app/zhiraf/ui/export.py             final_paragraphs, сохранение в .docx/.odt/.pdf/.txt
app/zhiraf/ui/start_screen.py       StartScreen
app/zhiraf/ui/dialogs.py            HotkeysDialog, DictionaryDialog, SettingsDialog
app/zhiraf/ui/main_window.py        MainWindow
app/zhiraf/ui/app.py, __main__.py   запуск: один экземпляр, журнал, сообщения
app/tests/ui/…                      тесты окна (conftest.py с qapp-настройкой)
```

---

### Task 1: Запись в профиль не ломает работу; временные файлы по PID

Закрывает отложенное из плана 1: сбой записи словаря/настроек, общий `tmp` двух экземпляров.

**Files:**
- Modify: `app/zhiraf/storage.py` (`Dictionary.add/remove/import_from`, `Settings.set`, `tmp_dir`, `clean_tmp`, `_write_atomic`)
- Test: `app/tests/test_storage.py` (добавить)

**Interfaces:**
- Consumes: существующие `Dictionary`, `Settings`, `Recent`, `data_dir`.
- Produces: `Dictionary.add/remove/import_from` и `Settings.set` при `OSError` возвращают память в прежнее состояние и пробрасывают `OSError`; `tmp_dir()` -> `<tmp>/<pid>`; `clean_tmp()` удаляет папки умерших PID и свою, чужие живые не трогает (проверка `psutil.pid_exists`).

- [ ] **Step 1: Failing tests** в `test_storage.py`:
```python
def blocked_dictionary(tmp_path):
    path = tmp_path / "словарь.txt"
    path.mkdir()                      # a folder where the file should be: every write fails
    return Dictionary(str(path))

def test_dictionary_add_rolls_back_when_write_fails(tmp_path):
    d = blocked_dictionary(tmp_path)
    with pytest.raises(OSError):
        d.add("Жирафик")
    assert "Жирафик" not in d and len(d) == 0

def test_dictionary_remove_rolls_back_when_write_fails(tmp_path):
    path = tmp_path / "словарь.txt"
    path.write_text("Жирафик\n", encoding="utf-8")
    d = Dictionary(str(path))
    path.unlink(); path.mkdir()
    with pytest.raises(OSError):
        d.remove("Жирафик")
    assert "Жирафик" in d

def test_settings_set_rolls_back_when_write_fails(tmp_path):
    bad = tmp_path / "настройки.json"; bad.mkdir()
    s = Settings(str(bad))
    with pytest.raises(OSError):
        s.set("strict_mode", True)
    assert s["strict_mode"] is False

def test_tmp_dir_is_per_process_and_clean_keeps_a_live_neighbour(zhiraf_home):
    mine = storage.tmp_dir()
    assert os.path.basename(mine) == str(os.getpid())
    neighbour = os.path.join(os.path.dirname(mine), str(os.getppid()))   # a live process
    dead = os.path.join(os.path.dirname(mine), "999999999")
    for p in (neighbour, dead):
        os.makedirs(p, exist_ok=True)
    storage.clean_tmp()
    assert os.path.isdir(neighbour) and not os.path.exists(dead) and os.path.isdir(storage.tmp_dir())
```
- [ ] **Step 2:** `../venv-app/bin/python -m pytest tests/test_storage.py -v` — Expected: 4 новых FAIL.
- [ ] **Step 3: Implement.** `Dictionary`: в `add/remove/import_from` скопировать `self._words` до изменения, при `OSError` из `_save` вернуть копию и `raise`. `Settings.set`: то же со значением. `_base("tmp")` оставить корнем, `tmp_dir()` создаёт и возвращает `<корень>/<os.getpid()>`; `clean_tmp()` обходит подпапки корня: имя не число или `not psutil.pid_exists(int(name))` или равно своему PID — `shutil.rmtree(ignore_errors=True)`; затем `tmp_dir()`. Проверить `grep -rn "tmp_dir\|clean_tmp" zhiraf` — вызывающие (`doc_format`, `cli`) работают без правок.
- [ ] **Step 4:** `../venv-app/bin/python -m pytest -q` — Expected: всё зелёное.
- [ ] **Step 5: Commit**
```bash
git add app/zhiraf/storage.py app/tests/test_storage.py
```
```bash
git commit -m "fix: profile writes roll back on failure, temp folder per process" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Структура документа для движка

Новое требование: правила смотрят, где стоит предложение (заголовок, ячейка таблицы, пункт списка). Проверка согласованности регистра (`CAPITAL_MID`) считала заглавные в заголовках/таблицах/списках «непоследовательностью».

**Files:**
- Modify: `engine/spellcheck/rules.py` (`DocContext`, `check`), `engine/spellcheck/checker.py` (`_stage_function`, `stream`, `check_document`), `app/zhiraf/segment.py`, `app/zhiraf/worker.py` (`_run`, `CheckJob`), `app/zhiraf/cli.py`
- Test: `app/tests/test_spelling_rules.py`, `app/tests/test_engine_stream.py`, `app/tests/test_segment.py`, `app/tests/test_worker.py`, `app/tests/test_cli.py` (добавить)

**Interfaces:**
- Produces (движок): виды `rules.BODY = "body"`, `HEADING = "heading"`, `TABLE = "table"`, `LIST = "list"`. `DocContext(sentences=(), lexicon=None, kinds=None)`: `kinds` — список видов, параллельный `sentences`; в счётчики `lower`/`capital` попадают только предложения вида `body` (или `None`); слова-термины считаются по всем. `rules.check(text, lexicon, ctx=None, kind=None)`: при `kind` не `None` и не `body` блок регистра («CAPITAL_MID») пропускается. `Checker.stream(sentences, context=None, stages=STAGES, should_stop=None, start=None, on_step=None, structure=None, context_structure=None)`: `structure` параллелен `sentences`, `context_structure` — `context` (если `context is None`, берётся `structure`). `Checker.check_document(..., structure=None)`.
- Produces (приложение): `segment.sentence_kinds(paragraphs, where) -> List[str]` (`paragraphs` — `List[documents.model.Paragraph]`, `where` — второй результат `plan_sentences`): `table` если `p.table`, иначе `heading` для стилей `title/h1/h2/h3`, `list` для `list`, иначе `body`. `CheckJob(..., structure=None, context_structure=None)` пробрасывает их в `_run`.

- [ ] **Step 1: Failing tests.**
  - `test_spelling_rules.py`: «слово пишут строчным 3 раза в теле, а в 5 заголовках заглавным» — `DocContext(sentences, lexicon, kinds)` с `kinds=["heading"]*5+["body"]*3` не даёт `CAPITAL_MID` для заглавного в теле; без `kinds` поведение прежнее (тест фиксирует и это); `rules.check(text, lexicon, ctx, kind="heading")` возвращает без `CAPITAL_MID`, `kind="body"` — с ним (уровень `strict`).
  - `test_engine_stream.py`: `stream(sentences, structure=[...])` с фейковыми моделями даёт те же результаты, что без `structure`, для этапов `commas/forms/spell/sage`; для `rules` — нет `RULE_CAPITAL_MID` в предложениях вида `heading`.
  - `test_segment.py`: абзацы `[Paragraph([Span("Один. Два.")]), Paragraph([Span("Раздел")], style="h1"), Paragraph([Span("ячейка")], table=(0,1,1)), Paragraph([Span("пункт")], style="list")]` → `sentence_kinds == ["body","body","heading","table","list"]`.
  - `test_worker.py`: `CheckJob(models_dir, SENTENCES, structure=["body","heading","table"], factories="fakes:make_factories")` доходит до `done` без ошибок.
  - `test_cli.py`: `check_file` на .docx с заголовком и таблицей не падает и передаёт виды (достаточно проверки результата и `error is None`).
- [ ] **Step 2:** `../venv-app/bin/python -m pytest tests/test_spelling_rules.py tests/test_engine_stream.py tests/test_segment.py tests/test_worker.py tests/test_cli.py -q` — Expected: новые FAIL.
- [ ] **Step 3: Implement** по Interfaces. В `_stage_function` для этапа `rules` строить `DocContext(context or sentences, lexicon, kinds)` и вызывать `rules.check(body, lexicon, ctx, kind)`, где `kind = structure[i]` если `structure` задан. Остальные этапы `structure` игнорируют. Вызовы без новых параметров обязаны вести себя как раньше. В `cli.check_file` считать `kinds = sentence_kinds(doc.paragraphs, where)` и передавать `structure=kinds, context_structure=kinds`.
- [ ] **Step 4:** `../venv-app/bin/python -m pytest -q` — Expected: всё зелёное (включая тесты движка и vermin).
- [ ] **Step 5: Commit** (`feat: pass document structure to the engine`), файлы поимённо, отдельными командами.

---

### Task 3: Среда Qt, тема, значки

**Files:**
- Create: `app/requirements-gui.txt`, `app/zhiraf/ui/__init__.py`, `app/zhiraf/ui/theme.py`, `app/tests/ui/__init__.py`, `app/tests/ui/conftest.py`, `app/tests/ui/test_theme.py`
- Modify: `app/requirements-dev.txt`, `app/tests/test_constraints.py` (FORBIDDEN Qt-модули), `app/pytest.ini` (ничего, если не нужно)

**Interfaces:**
- Produces: `theme.COLORS: dict` (ключи `sky paper ink moon error check fixed skipped`), `theme.LEVEL_LABEL = {"error": "Ошибка", "check": "Проверьте"}`, `theme.icon(name, color=None, size=18) -> QIcon` (имена: `error check fixed skipped help`; SVG собираются из строк в модуле, рендер `QSvgRenderer`), `theme.status_color(name) -> str`, `theme.stylesheet() -> str`, `theme.art_path(name) -> str` (`<ROOT>/art/name`, если папка есть, иначе `<ROOT>/engine/art/name`).
- Produces (тесты): фикстуры `qapp` (из pytest-qt), в `tests/ui/conftest.py` до импорта PySide2: `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`; фикстура `session_of(texts)`-помощник не нужна здесь.

- [ ] **Step 1:** `requirements-gui.txt`: `PySide2==5.15.2.1` и `shiboken2==5.15.2.1`. В `requirements-dev.txt` добавить `-r requirements-gui.txt` и `pytest-qt==4.2.0`. В venv-app нет pip: `../venv-app/bin/python -m ensurepip` (если нет — `python3 -m pip install --target ../venv-app/lib/python3.8/site-packages -r requirements-dev.txt`). Проверить: `../venv-app/bin/python -c "import PySide2.QtWidgets, PySide2.QtSvg, PySide2.QtPrintSupport"` без ошибки. Если не хватает системных библиотек для offscreen (`libxkbcommon`, `libEGL`, `libfontconfig`) — поставить пакетами ОС, записать в `app/README-dev.md` одной строкой не нужно, достаточно сообщения в отчёте задачи.
- [ ] **Step 2: Failing test** `test_theme.py`:
```python
def test_palette_is_the_spec_palette():
    assert theme.COLORS["error"] == "#b9524a" and theme.COLORS["check"] == "#d9a521"
    assert theme.COLORS["fixed"] == "#3f9a4e" and theme.COLORS["skipped"] == "#8792a2"
    assert theme.COLORS["sky"] == "#56708f" and theme.COLORS["paper"] == "#f6f3ec"

def test_icons_render_for_every_status(qapp):
    for name in ("error", "check", "fixed", "skipped", "help"):
        pixmap = theme.icon(name, size=18).pixmap(18, 18)
        assert not pixmap.isNull()
        image = pixmap.toImage()
        assert any(image.pixelColor(x, y).alpha() > 0 for x in range(18) for y in range(18))

def test_art_path_finds_the_giraffe():
    assert os.path.isfile(theme.art_path("start.jpg"))
```
  Расширить `test_constraints.FORBIDDEN`-проверку: имена, содержащие `QtNetwork`, `QtWebEngine`, `QtQml`, `QtMultimedia`, `QLocalServer`, `QTcpSocket`; новый тест `test_forbidden_qt_names_are_caught` (как `test_forbidden_import_is_caught`).
- [ ] **Step 3:** Реализовать `theme.py`. Значки — простые SVG: ✕ (две линии), ⚠ (треугольник с «!»), ✓ в кружке, ↷ (дуга со стрелкой), «?» в кружке; цвет подставляется в строку.
- [ ] **Step 4:** `../venv-app/bin/python -m pytest tests/ui tests/test_constraints.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** (`feat: Qt environment, palette and icons`).

---

### Task 4: Модель показа — `runs.py` (без Qt)

Формат и позиции в одном месте: из абзаца модели и сессии получить куски текста для показа и итоговые прогоны для сохранения.

**Files:**
- Create: `app/zhiraf/ui/runs.py`, `app/tests/ui/test_runs.py`

**Interfaces:**
- Consumes: `documents.model.Paragraph/Span/Document`, `review.ReviewSession` (`marks`, `span(mark)`, `text(i)`, `to_current`), `review.OPEN/ACCEPTED/MANUAL/SKIPPED`.
- Produces:
  - `@dataclass Run: text: str; bold: bool=False; italic: bool=False; underline: bool=False; mark: Optional[Tuple[int, str, str]] = None` (`mark = (mark.id, mark.status, mark.level)`).
  - `display_range(session, mark) -> Tuple[int, int]` — диапазон в ТЕКУЩЕМ тексте абзаца; пустой диапазон (вставка запятой) расширяется на один символ слева (`start-1..start`), в начале абзаца — на один символ справа.
  - `paragraph_runs(paragraph: Paragraph, session: ReviewSession, index: int) -> List[Run]` — текст = `session.text(index)`; оформление каждого символа берётся из символа исходного текста, с которого начинается замена (для вставки — от предыдущего символа); метки накладываются для статусов `open/accepted/manual/skipped` (статус `dictionary` метки не имеет); соседние куски с одинаковым оформлением и меткой склеены.
  - `final_spans(paragraph, session, index) -> List[Span]` — то же без меток; `final_paragraphs(doc, session) -> List[Paragraph]` — копии абзацев со `style/table/has_image` исходных и итоговыми `spans`.

- [ ] **Step 1: Failing tests** (`test_runs.py`), строить `ReviewSession([text])` и `add_findings(0, 0, [{"start":..,"end":..,"fix":..,"level":"error","rule":"MODEL_FORM","message":"m"}])`:
  - `test_runs_keep_bold_of_the_replaced_word`: спаны `[Span("Работа "), Span("с информации", bold=True)]`, исправление «информации»→«информацией» принято; `final_spans` даёт `[Span("Работа "), Span("с информацией", bold=True)]`; `paragraph_runs` — кусок `информацией` с `mark == (id, "accepted", "error")` и `bold=True`.
  - `test_zero_width_mark_is_shown_on_previous_character`: вставка «,» после «Документ» в «Документ определяющий» — `display_range == (7, 8)`? до принятия: открыта метка `(7,7)` → `display_range == (6, 7)`; после принятия текст «Документ, …», метка на `(7, 8)` (`session.span(mark)`).
  - `test_zero_width_mark_at_paragraph_start`: вставка в позиции 0 → `(0, 1)`.
  - `test_dictionary_status_has_no_mark` и `test_skipped_keeps_mark_with_status_skipped`.
  - `test_final_paragraphs_keep_style_and_table`: абзац `style="h1"`, `table=(0,1,2)` сохраняются.
  - `test_emoji_positions`: «Яблоко🍎 сорт» — метка на «сорт» даёт `Run.text == "сорт"`.
- [ ] **Step 2:** `../venv-app/bin/python -m pytest tests/ui/test_runs.py -q` — FAIL (`ModuleNotFoundError`).
- [ ] **Step 3:** Реализовать. Алгоритм: массив оформлений по символам исходного текста из спанов; пройти исходный текст с отсортированными заменами (`session.replacements()` для абзаца), выдавая символы нового текста с оформлением по правилу выше; затем наложить метки по `display_range`.
- [ ] **Step 4:** `../venv-app/bin/python -m pytest tests/ui/test_runs.py -q` — PASS.
- [ ] **Step 5: Commit** (`feat: display model for marks and formatting`).

---

### Task 5: Область текста — `ReviewEditor`

**Files:**
- Create: `app/zhiraf/ui/editor.py`, `app/tests/ui/test_editor.py`

**Interfaces:**
- Consumes: `runs.paragraph_runs`, `runs.display_range`, `theme`, `review.ReviewSession`, `documents.model.Document`.
- Produces: `class ReviewEditor(QTextEdit)`:
  - `load(doc: Document, session: ReviewSession)` — по одному блоку на абзац (`document().blockCount() == len(doc.paragraphs)`), текст блока = `session.text(i)` с заменой `\n -> U+2028`, `\r -> " "` (длина не меняется); заголовки (`title/h1/h2/h3`) крупнее и жирные, пункты списка — маркированный список Qt (`createList`, без символов в тексте), ячейки таблицы — отступ и лёгкая заливка блока (символов не добавляется); картинка в абзаце — значок «рисунок» только в подсказке блока (текст не меняется). Режим просмотра: `setReadOnly(True)`.
  - `repaint_paragraphs(indexes: Iterable[int])` — переписывает содержимое указанных блоков из `paragraph_runs` одним `beginEditBlock/endEditBlock`; не трогает блок, в котором сейчас стоит курсор режима правки.
  - `show_current()` — рамка курсора вокруг `session.current` (ExtraSelection), прокрутка так, чтобы пометка была видна, сигнал `current_rect_changed(QRect)` (прямоугольник пометки в координатах viewport — для карточки).
  - Формат меток (свойство символа `MARK_PROP = QTextFormat.UserProperty + 1` со значением `status`, `BASE_UNDERLINE_PROP = +2`): ошибка — заливка `#b9524a` с прозрачностью и сплошное подчёркивание; проверьте — жёлтая заливка, пунктир; исправлено — зелёная заливка, подсказка «было: …» (при наведении, `QToolTip` через `event(QEvent.ToolTip)`); пропущено — серая заливка и подпись «пропущено» (рисуется в `paintEvent` над меткой только для видимых блоков).
  - `set_checked_until(paragraph: Optional[int])` — абзацы после указанного бледнеют наложением цвета бумаги (в `paintEvent`) и подписью «ещё проверяется» на границе; `None` — всё проверено.
  - Режим правки (только `doc.editable`, т.е. вставка): щелчок мышью по месту без пометки включает правку (`setReadOnly(False)`, сигнал `edit_mode_changed(True)`), `Esc` возвращает просмотр. Щелчок по метке: `mark_clicked(int)` (id) и остаётся просмотр. Изменение блока в режиме правки → через 700 мс бездействия `paragraph_edited(int)` для каждого изменённого абзаца после синхронизации: `doc.paragraphs[i].spans = spans_from_block(block)` (Task 9), `session.replace_paragraph(i, block text)` и снятие меток с блока (символы с `MARK_PROP` возвращаются к `BASE_UNDERLINE_PROP`/без заливки). Метод `flush_edits()` делает то же немедленно (перед сохранением).
  - `mark_at(position: int) -> Optional[int]`.
  - Колёсико/прокрутка — стандартные.

- [ ] **Step 1: Failing tests** (`qtbot`, офлайн):
```python
def make(texts, styles=None, editable=False):
    doc = Document([Paragraph([Span(t)], style=(styles or {}).get(i, "normal")) for i, t in enumerate(texts)],
                   kind="paste" if editable else "docx", editable=editable)
    session = ReviewSession(texts)
    return doc, session

def test_block_per_paragraph_and_text_equal_after_unsafe_characters(qtbot):
    doc, session = make(["Яблоко🍎 сорт", "a\nb\tc", "x y"])
    editor = ReviewEditor(); qtbot.addWidget(editor); editor.load(doc, session)
    assert editor.document().blockCount() == 3
    for i, block in enumerate(blocks(editor)):
        assert len(block.text()) == len(session.text(i))   # same length: positions match

def test_error_mark_has_fill_and_solid_underline(qtbot): ...   # charFormat at mark start: MARK_PROP == "open", underlineStyle SingleUnderline, background alpha > 0
def test_check_mark_is_dotted(qtbot): ...
def test_accept_repaints_text_and_green(qtbot):
    # session.accept(); editor.repaint_paragraphs([0]) -> block text has the fix, mark char format "accepted"
def test_skipped_has_grey_fill(qtbot): ...
def test_read_only_for_opened_document(qtbot): editor.isReadOnly()
def test_click_on_plain_text_of_paste_enters_edit_mode_and_esc_leaves(qtbot): ... qtbot.mouseClick(...); keyClick Escape
def test_typing_in_pasted_paragraph_drops_marks_and_bumps_version(qtbot):
    # enter edit mode, insert text at block 0, qtbot.waitSignal(editor.paragraph_edited); session.version(0) == 1; no MARK_PROP chars left in block 0
def test_set_checked_until_marks_unchecked_state(qtbot): editor.checked_until == 1 (атрибут), grab() не падает
def test_current_rect_is_inside_viewport(qtbot): signal payload inside viewport().rect()
def test_accept_all_two_thousand_marks_repaint_is_fast(qtbot):
    # 3000 paragraphs, 2000 error marks, accept_all_errors(), repaint_paragraphs(set of changed) < 5 s
```
  Помощники теста: `blocks(editor)` перечисляет `QTextBlock`; `char_format_at(editor, pos)` через `QTextCursor`.
- [ ] **Step 2:** `../venv-app/bin/python -m pytest tests/ui/test_editor.py -q` — FAIL.
- [ ] **Step 3:** Реализовать `editor.py`. Переписывание блока: курсор в начало блока, `movePosition(EndOfBlock, KeepAnchor)`, `removeSelectedText()`, затем `insertText(run.text, fmt)` на кусок; блоковый формат и список сохраняются. Отключать `setUndoRedoEnabled` на время программной записи (в режиме просмотра), включать для правки пользователя. Не вызывать `ensureCursorVisible` для остальных блоков.
- [ ] **Step 4:** `../venv-app/bin/python -m pytest tests/ui/test_editor.py -q` — PASS.
- [ ] **Step 5: Commit** (`feat: review editor with marks`).

---

### Task 6: Карточка пометки — `MarkCard`

**Files:**
- Create: `app/zhiraf/ui/card.py`, `app/tests/ui/test_card.py`

**Interfaces:**
- Consumes: `review.Mark` (`level`, `fix`, `original`, `message`, `can_add_to_dictionary`), `theme.icon/LEVEL_LABEL/COLORS`.
- Produces:
  - `card_position(viewport: QRect, anchor: QRect, size: QSize, gap: int = 8) -> QPoint` — карточка под пометкой, если помещается, иначе над ней; по горизонтали прижимается к полю `viewport` с отступом 12 (широкая карточка не вылезает за край).
  - `class MarkCard(QFrame)`: `show_mark(mark, before: str, after: str)` (`before/after` — до 20 символов текста вокруг пометки); сигналы `accept_clicked()`, `skip_clicked()`, `dictionary_clicked()`, `manual_submitted(str)`; кнопки `accept_button` («Принять (Enter)», выключена при `fix is None`), `skip_button` («Пропустить»), `dictionary_button` («В словарь», `isHidden()` если `not mark.can_add_to_dictionary`), `manual_button` («Исправить вручную» раскрывает поле `manual_edit`, предзаполненное `mark.original`; Enter в поле → `manual_submitted(text)`; Esc закрывает поле); строка подсказок «← → — к другой пометке · Ctrl+Z — отменить». Заголовок: значок + `LEVEL_LABEL[level]` цвета уровня; строка исправления — rich text «по ~~доступ~~ → по доступу» (`<s>` для старого, `<b>` для нового; для вставки запятой «нет запятой → ,»), справа объяснение `mark.message`.

- [ ] **Step 1: Failing tests:**
```python
def test_card_position_below_when_it_fits():
    p = card_position(QRect(0, 0, 800, 600), QRect(100, 100, 60, 20), QSize(700, 90))
    assert p.y() == 100 + 20 + 8 and 12 <= p.x() and p.x() + 700 <= 800 - 12

def test_card_position_above_near_bottom():
    p = card_position(QRect(0, 0, 800, 600), QRect(100, 560, 60, 20), QSize(700, 90))
    assert p.y() + 90 <= 560 - 8

def test_card_shows_error_with_fix(qtbot): level label «Ошибка», html contains "<s>", accept enabled
def test_card_check_without_fix_disables_accept(qtbot)
def test_dictionary_button_only_for_spelling_marks(qtbot)   # rule "MODEL_FORM" -> hidden, "RULE_TYPO" -> visible
def test_manual_edit_enter_emits_text(qtbot)                # waitSignal manual_submitted with ["информацией"]
def test_manual_edit_prefilled_with_original(qtbot)
```
  Метки для тестов строить через `ReviewSession.add_findings`.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** `../venv-app/bin/python -m pytest tests/ui/test_card.py -q` — PASS.
- [ ] **Step 5: Commit** (`feat: wide mark card`).

---

### Task 7: Строка состояния, прогресс, уведомление

**Files:**
- Create: `app/zhiraf/ui/status.py`, `app/tests/ui/test_status.py`

**Interfaces:**
- Produces:
  - `progress_text(fraction: float, remaining: Optional[float], now: float, state: str = "running") -> str`: `state="done"` или `fraction>=1` → «Проверка завершена»; `remaining is None` → «Проверено 3%»; `remaining < 30` → «Проверено 97%»; иначе «Проверено 42% · осталось ≈ 4 мин · готово к 18:52» (мин округляется вверх до целого, от 60 мин — «≈ 1 ч 20 мин»; время — локальное `HH:MM` от `now + remaining`); `state="stopped"` → «Проверка остановлена на 42%»; `state="failed"` → «Проверка прервана на 42%».
  - `class ProgressPanel(QWidget)`: `set_progress(fraction, remaining, now, state)`; рисует синюю полосу со светящейся «луной» на конце (`QPainter`), подпись `progress_text`.
  - `class StatusPanel(QWidget)`: `set_counts(counts: dict)` (ключи `errors checks fixed skipped`; подписи «ошибок: N», «проверить: N», «исправлено: N», «пропущено: N», каждая со значком и цветом уровня), `accept_all_button` (QPushButton «Принять все ошибки» со значком «?» ВНУТРИ кнопки — дочерний `QLabel` `help_badge` с `theme.icon("help")`; выключена при `errors == 0`, но `isVisible()` всегда), подсказка кнопки — ровно `Исправит все ошибки (сейчас %d). Пометки «проверить» останутся.`; сигнал `accept_all_clicked()`. Скрыть кнопку нечем: ни настройки, ни пункта меню для этого не добавлять.
  - `class NoticeBar(QFrame)`: `show_notice(text: str, action: Optional[str] = None)`, `clear()`, сигнал `action_clicked()`, кнопка действия `action_button` (например «Продолжить с этого места»).

- [ ] **Step 1: Failing tests:** `progress_text(0.42, 240, now)` содержит «Проверено 42%», «осталось ≈ 4 мин», «готово к » и точное время `time.strftime("%H:%M", time.localtime(now + 240))`; `progress_text(0.97, 10, now) == "Проверено 97%"`; `progress_text(0.5, None, now) == "Проверено 50%"`; `progress_text(0.1, 4800, now)` содержит «≈ 1 ч 20 мин»; `done`/`stopped`/`failed`; `StatusPanel`: после `set_counts({"errors": 3, ...})` `accept_all_button.toolTip() == "Исправит все ошибки (сейчас 3). Пометки «проверить» останутся."`, `accept_all_button.isEnabled()`; при 0 — `not isEnabled()` и `isVisible()` (виджет показан через `qtbot`); `help_badge.parent() is accept_all_button`; клик → сигнал; цвета подписей равны `theme.COLORS`; `NoticeBar`: `show_notice("Проверка прервана", "Продолжить с этого места")` показывает кнопку, клик → сигнал, `clear()` прячет.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS (`tests/ui/test_status.py`). **Step 5: Commit** (`feat: status bar, progress and notices`).

---

### Task 8: `CheckController` — проверка в окне

**Files:**
- Create: `app/zhiraf/ui/controller.py`, `app/tests/ui/test_controller.py`

**Interfaces:**
- Consumes: `worker.CheckJob` (`start/poll/stop/close`, `progress`, `finished`, `error`, `stopped`), `segment.plan_sentences/sentence_kinds`, `ReviewSession.add_findings/pop_removed/version`, `storage.Settings` (`show_checks`, `strict_mode`).
- Produces: `class CheckController(QObject)`:
  - `CheckController(session, get_paragraphs, models_dir, settings, factories=None, parent=None)`; `get_paragraphs() -> List[Paragraph]` (текущие абзацы документа).
  - Сигналы: `marks_changed(object)` — множество индексов абзацев, чьи пометки изменились (добавлены или вытеснены `pop_removed`); `progressed()`; `state_changed(str)` — `"running" | "stopped" | "failed" | "done"`; `checked_until(int)` — индекс последнего абзаца, дошедшего до последнего этапа (`job.stages[-1]`).
  - Свойства: `state` (`"idle"` до старта), `progress` (`Progress` или `None`), `error` (кортеж `(kind, user_message, detail)` или `None`), `has_text` (в документе есть хоть одно предложение).
  - Методы: `start() -> bool` (False и состояние `"done"`, если предложений нет — запуск не происходит), `stop()`, `resume()` (повтор с `resume_from=(stage, last_index+1)` для этапа, где оборвалось; уже пришедшие сообщения не дублируются), `recheck(dirty: Iterable[int])` (очередь абзацев; после основного прохода запускается второй `CheckJob` только по предложениям этих абзацев с `context=` всеми текущими предложениями), `close()` (останавливает и закрывает задание; после `close()` сообщения не применяются).
  - Таймер 50 мс; за такт `job.poll(0)` (не более 500 сообщений — лимит в самом `CheckJob`). Каждое сообщение `("findings", stage, idx, items)` → `session.add_findings(paragraph, offset, items, version=versions[paragraph])`, где `versions` снимаются при запуске задания (`session.version(p)`); при `settings["show_checks"] == False` пометки уровня `check` отфильтровываются до добавления. После `finished`: ошибка → `failed`; остановка → `stopped`; иначе очередь `recheck` не пуста → второй проход, иначе `done`.
  - `CheckJob` создаётся с `strict=settings["strict_mode"]`, `structure/context_structure` из `sentence_kinds` (Task 2).

- [ ] **Step 1: Failing tests** (`qtbot`, `models_dir` из conftest ядра, `factories="fakes:make_factories"`; общий помощник `finish(controller)` = `qtbot.waitUntil(lambda: controller.state in ("done","stopped","failed"), timeout=60000)`):
  - `test_check_finds_marks_and_reports_done`: тексты как в `test_worker.SENTENCES`; к концу в сессии есть метка `RULE_`/`MODEL_FORM`, `state == "done"`, `progress.fraction() == 1.0`, `marks_changed` приходил, `checked_until` дошёл до последнего абзаца.
  - `test_empty_document_does_not_start`: абзацы `["", "   "]` → `start() is False`, `state == "done"`, `has_text is False`, процесса нет.
  - `test_findings_for_edited_paragraph_are_dropped`: запустить медленные модели (`fakes:make_slow_factories`), после первого сообщения вызвать `session.replace_paragraph(0, "Новый текст")` → у абзаца 0 нет пометок прежнего текста.
  - `test_recheck_runs_after_main_pass_for_dirty_paragraphs`: `recheck([0])` после правки → после `done` у абзаца 0 пометки нового текста; число заданий — 2 (проверка через счётчик `controller.jobs_started`).
  - `test_stop_keeps_marks_and_resume_has_no_duplicates`: `stop()` после первых пометок → `state == "stopped"`, `resume()` → `done`; множество `(paragraph,start,end,rule)` без повторов.
  - `test_crash_gives_failed_with_message_and_resume`: фабрики из `fakes`, роняющие процесс (`fakes:make_crashing_factories` — добавить в `tests/fakes.py`, по образцу `_broken` из ядра) → `state == "failed"`, `error[1]` по-русски, пометки до сбоя сохранены; после `resume()` с исправными фабриками — `done`.
  - `test_close_stops_child_and_ignores_late_messages`: `close()` во время проверки → `controller.state` не меняется на `done`, процесс завершён (`job._process.is_alive() is False`).
  - `test_show_checks_off_hides_check_level`: `settings.set("show_checks", False)` → ни одной метки `level == "check"`.
  - `test_polling_handles_flood`: 3000 однострочных абзацев с быстрыми моделями — окно отвечает (`qtbot.wait(50)` между пакетами не ломается), `done` достигается.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. Для `resume`: запоминать `last[stage] = idx` из последнего принятого `findings`; `resume_from = (stage_in_progress, last[stage] + 1)`, где этап — первый, у которого `last` ещё не дошло до `n-1` (если сбой между этапами — `(next_stage, 0)`). **Step 4:** PASS (`tests/ui/test_controller.py`). **Step 5: Commit** (`feat: check controller`).

---

### Task 9: Открытие в потоке, вставка с оформлением

**Files:**
- Create: `app/zhiraf/ui/loader.py`, `app/zhiraf/ui/clipboard.py`, `app/tests/ui/test_loader.py`, `app/tests/ui/test_clipboard.py`

**Interfaces:**
- Consumes: `documents.opener.open_document`, `documents.model.*`, `storage.clean_tmp`.
- Produces:
  - `class OpenTask(QObject)`: `OpenTask(path, parent=None)`, `start()`; сигналы `opened(object)` (`Document`) и `failed(str)` (русское сообщение; для неожиданных исключений — «Не удалось открыть «имя»: файл повреждён.», без текста исключения); работает в `QThread`, `cancel()` — результат отбрасывается, поток завершается и ждётся в `close()`; один `OpenTask` за раз (окно держит ссылку).
  - `document_from_mime(mime: QMimeData) -> Optional[Document]` — HTML, если есть (теги `<img>` и `<script>` вырезаются регулярным выражением до `QTextDocument.setHtml`), иначе простой текст; `None`, если после обрезки пробелов пусто; `Document(kind="paste", editable=True, path=None, saved_as="docx")`.
  - `document_from_qtext(qdoc: QTextDocument) -> Document` — абзацы по блокам: спаны с жирным/курсивом/подчёркиванием (по `QTextFragment.charFormat()`), `style` из `blockFormat().headingLevel()` (1–3 → `h1..h3`) и `textList()` (`list`), `table=(номер, строка, столбец)` для блоков в ячейках; пустые абзацы остаются.
  - `spans_from_block(block: QTextBlock) -> List[Span]` — как выше для одного блока, символы с `MARK_PROP` берут подчёркивание из `BASE_UNDERLINE_PROP`; `U+2028` → `\n`.
  - `paragraphs_to_html(paragraphs: List[Paragraph]) -> str` и `copy_to_clipboard(paragraphs, clipboard: QClipboard)` — HTML (`<p>`, `<h1..3>`, `<ul><li>`, `<b><i><u>`, экранирование) и простой текст (абзацы через `\n`) одновременно.

- [ ] **Step 1: Failing tests:**
  - `test_clipboard.py`: HTML `<h1>Приказ</h1><p>Текст <b>жирный</b> и <i>курсив</i></p><ul><li>пункт</li></ul><table><tr><td>ячейка</td></tr></table>` → абзацы со стилями `h1`, `normal`, `list`, и абзац с `table == (0, 0, 0)`; спаны `Span("жирный", bold=True)`; `<img src="file:///etc/passwd">` — ни абзаца, ни `has_image`; пустой/пробельный буфер → `None`; простой текст с `\r\n` делится на абзацы; `paragraphs_to_html` экранирует `<`, `&`; `copy_to_clipboard` кладёт и `text/html`, и `text/plain` (читать через `qapp.clipboard().mimeData()`); `U+2028` в блоке → `\n` в спане.
  - `test_loader.py`: открытие `docfactory`-документа `.docx` даёт `opened` с `Document`; несуществующий файл — `failed` с «Файл не найден»; повреждённый файл — «файл повреждён» без трассировки; `cancel()` до результата — сигналов нет, поток закончился; `.txt` в cp1251 открывается.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS. **Step 5: Commit** (`feat: open in a thread, paste with formatting`).

---

### Task 10: Сохранение и «Скопировать с оформлением» — `export.py`

**Files:**
- Create: `app/zhiraf/ui/export.py`, `app/tests/ui/test_export.py`

**Interfaces:**
- Consumes: `runs.final_paragraphs`, `opener.save_document`, `docx_format.write_docx_package`, `model.SaveReport/DocumentError/corrected_path`, `clipboard.copy_to_clipboard`.
- Produces:
  - `FORMATS = [("Документ Word (*.docx)", "docx"), ("Документ ODF (*.odt)", "odt"), ("PDF (*.pdf)", "pdf"), ("Текст (*.txt)", "txt")]`.
  - `save_corrected_copy(doc, session, dst=None) -> SaveReport` — для открытого файла `save_document(doc, session.replacements(), dst)` (оформление байт в байт); для вставки (`doc.path is None`) без `dst` — `DocumentError("Укажите, куда сохранить документ.")`.
  - `save_as(doc, session, dst) -> SaveReport` — расширение `dst` берётся из имени; для открытого документа с тем же форматом (`ext == doc.saved_as`) — `save_document` (оформление сохраняется); иначе `export_paragraphs(final_paragraphs(doc, session), dst)`; запись исходного пути — `DocumentError("Исходный документ не перезаписывается — выберите другое имя.")`; неизвестное расширение — `DocumentError`.
  - `export_paragraphs(paragraphs, dst)` — `.docx` (собственный XML через `write_docx_package`: `w:b/w:i/w:u`, заголовки жирные крупнее, пункты списка с «• », ячейки таблицы — обычные абзацы), `.odt` (`QTextDocumentWriter(dst, b"ODF")` из `QTextDocument`, собранного по абзацам), `.pdf` (`QPrinter(QPrinter.HighResolution)`, `setOutputFormat(PdfFormat)`, A4, `QTextDocument.print_`), `.txt` (UTF-8 с BOM, `\r\n`). Запись во временный `dst + ".part"` и `os.replace`; при любом сбое `.part` удаляется; `OSError` → `DocumentError("Не удалось сохранить «имя»: нет доступа или файл открыт в другой программе.")`.
  - `needs_overwrite_confirmation(dst, doc) -> bool` — файл существует (и это не исходный).
  - `copy_corrected(doc, session, clipboard)` — `copy_to_clipboard(final_paragraphs(doc, session), clipboard)`.

- [ ] **Step 1: Failing tests:** (docfactory-документы; все результаты читать обратно ядром: `open_document`)
  - исправление в «жирном» слове: `.docx` → `save_corrected_copy` → текст принятого исправления есть, оформление абзаца цело (`open_document(saved).paragraphs[i].spans[...].bold`);
  - `save_as(doc_docx, session, "x.odt")` → открывается `read_odt`, текст равен итоговому; `.txt` — строки равны итоговым абзацам; `.pdf` — файл начинается с `%PDF`, размер > 0; `.docx` из вставки (`kind="paste"`) → открывается `read_docx`, жирный сохранён;
  - `save_as(doc, session, doc.path)` → `DocumentError` с «не перезаписывается»; `save_as` в папку без прав (`tmp_path` с `chmod 0o500`; пропуск, если тест запущен от root) → `DocumentError` по-русски и нет `*.part`;
  - `needs_overwrite_confirmation` истинно для существующего чужого файла, ложно для нового;
  - `copy_corrected` кладёт в буфер итоговый текст и HTML с `<b>`.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS. **Step 5: Commit** (`feat: save in any format and copy with formatting`).

---

### Task 11: Стартовый экран

**Files:**
- Create: `app/zhiraf/ui/start_screen.py`, `app/tests/ui/test_start_screen.py`

**Interfaces:**
- Consumes: `theme.art_path/COLORS`, `storage.Recent.items()` (элемент `{"path", "opened_at", "stats": {"fixed","skipped","handled","total"}}`).
- Produces: `class StartScreen(QWidget)`: слева картинка `start.jpg` во всю высоту (масштаб с сохранением пропорций, фон окна — ночное небо), справа «Проверим документ на ошибки?», подзаголовок «…текст никуда не отправляется», кнопки «Вставить текст» (Ctrl+V) и «Открыть документ» (Ctrl+O · .docx, .doc, .odt), зона перетаскивания, «Недавние документы», ссылка «Очистить список», закреплённая строка «F1 — горячие клавиши · Работает без интернета».
  - Сигналы: `open_requested()`, `paste_requested()`, `file_dropped(str)`, `recent_chosen(str)`, `clear_recent_requested()`.
  - `set_recent(items: list)` — строка: значок формата (по расширению), имя, папка, дата `дд.мм.гггг`, итог: `stats.fixed or stats.skipped` → «✓ 12 исправлено, 3 пропущено», иначе при `total` → «разобрано 14 из 23» (`handled`/`total`), иначе пусто; список прокручивается; файла нет на диске → строка серая с «файл не найден» и при выборе всё равно шлёт `recent_chosen` (окно покажет сообщение).
  - `dropEvent` принимает только локальные файлы с расширениями `.docx .doc .odt .txt`; чужое расширение → сигнал `file_dropped` всё равно, окно скажет «формат не поддерживается» (единое место сообщения — `open_document`).

- [ ] **Step 1: Failing tests:** кнопки шлют сигналы; `set_recent` с тремя элементами даёт три строки с текстами «✓ 12 исправлено, 3 пропущено» и «разобрано 14 из 23»; пустой список — блок «Недавние документы» скрыт, а «Очистить список» нет; клик по строке → `recent_chosen(path)`; имитация `QDropEvent` с `QMimeData.setUrls([QUrl.fromLocalFile(path)])` → `file_dropped(path)`; картинка загружена (`pixmap_label.pixmap().isNull() is False`); строка «F1 — горячие клавиши · Работает без интернета» на месте; 100 недавних элементов не ломают (максимум `storage.MAX_RECENT`, прокрутка).
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS. **Step 5: Commit** (`feat: start screen`).

---

### Task 12: Главное окно и поток разбора

**Files:**
- Create: `app/zhiraf/ui/main_window.py`, `app/tests/ui/test_main_window.py`

**Interfaces:**
- Consumes: всё из задач 1–11, `storage.Settings/Dictionary/Recent`, `__init__.missing_models`.
- Produces: `class MainWindow(QMainWindow)`:
  - `MainWindow(models_dir, factories=None, parent=None)`; центральный виджет — `QStackedWidget` (`StartScreen` / экран проверки: панель + `ReviewEditor` + `MarkCard` поверх viewport + `NoticeBar` + `ProgressPanel` справа вверху + `StatusPanel` внизу). Заголовок: «Жираф.Корректор» на старте, «Жираф.Корректор — имя файла» в работе (для вставки — «Вставленный текст»).
  - Публичные: `open_path(path)`, `paste_from_clipboard()`, `show_start()`, `save_copy()`, `save_as(path=None)`, `copy_with_formatting()`, `close_document() -> bool` (False — человек отменил), поля `doc`, `session`, `controller`, `editor`, `card`, `status`, `actions: dict` (`open paste stop save_copy save_as copy_formatted undo accept_all dictionary settings help`).
  - Клавиши (`QShortcut`, действуют только в режиме просмотра, не в режиме правки редактора): `←` `go_prev`, `→` `go_next`, `Enter/Return` принять, `Ctrl+Z` отмена, `Ctrl+O`, `Ctrl+V` (вставка, когда фокус не в режиме правки), `Ctrl+S` «Сохранить исправленную копию», `F1` справка. В режиме правки: `Esc` — назад в просмотр; клавиши стрелок/Enter остаются у текста.
  - Поведение: после `accept/skip/add_to_dictionary/manual` сессия сама переходит к следующей — окно вызывает `editor.repaint_paragraphs`, `editor.show_current()`, обновляет карточку (`card.show_mark(...)` и `card_position`), счётчики и, если пометок больше нет, прячет карточку и пишет «Все пометки разобраны». Правки от `Edit` сессии идут в `repaint_paragraphs({e.paragraph ...})`. «Принять все ошибки» — одно действие, один `Ctrl+Z`. Клик по метке — `session.select`. «В словарь»: `OSError` из `Dictionary.add` → `NoticeBar` «Не удалось записать словарь: …нет доступа к папке профиля. Слово не добавлено.» (состояние сессии не меняется, откат сделан в Task 1). Настройка `remember_recent`/`Recent.touch` с `OSError` — молча (удобство, не данные). Результаты `Recent.touch(path, stats)` при закрытии документа и после сохранения.
  - Открытие: `open_path` запускает `OpenTask`; во время открытия кнопки блокируются, на экране «Открываю…»; `failed(msg)` → `QMessageBox` с текстом и возврат на старт; `doc.notice` (например «.doc сохранён только как .docx») показывается в `NoticeBar`; нет предложений → «В документе нет текста для проверки» и проверка не стартует; `missing_models(models_dir)` при проверке → `NoticeBar` с текстом, документ показан без проверки.
  - Сохранение: «Сохранить» ▾ = «Сохранить исправленную копию» (Ctrl+S) и «Сохранить как…» (`QFileDialog.getSaveFileName` с `export.FORMATS`, `DontConfirmOverwrite` + собственный `QMessageBox.question` при `needs_overwrite_confirmation`); `DocumentError` → `QMessageBox` с текстом и предложением «Сохранить как…» (для вставки без пути «Сохранить исправленную копию» сразу открывает «Сохранить как…»); перед сохранением `editor.flush_edits()`. После успеха — сообщение в `NoticeBar`: «Сохранено: <путь>» (+ «Не удалось применить исправлений: N» если `report.skipped`).
  - Закрытие документа (`close_document`, `closeEvent`, `open_path`, «Открыть», `show_start`): `controller.close()`, `OpenTask.cancel()`; если есть принятые исправления и после последнего сохранения были изменения — `QMessageBox` «Сохранить исправленную копию?» (Сохранить / Не сохранять / Отмена); `close_document` ждёт завершения детей без зависания (≤ 2 с). `closeEvent` закрывает окно, сохраняя `Recent`.
  - Остановка/продолжение: «Остановить» активна при `state == "running"`; после `stopped`/`failed` в `NoticeBar` кнопка «Продолжить с этого места» → `controller.resume()`.

- [ ] **Step 1: Failing tests** (`qtbot`, `factories="fakes:make_factories"`, `models_dir` фикстура; `QMessageBox`/`QFileDialog` подменяются `monkeypatch` на статические методы; документ — `.docx` из `docfactory` с текстом «Работа с информации ведётся. Документ определяющий порядок утверждён.»):
  - `test_start_screen_is_shown_first`; `test_open_path_runs_check_and_shows_marks` (после `done` в `editor` есть метки, `status.accept_all_button` включена, счётчик ошибок совпадает с `session.counts()`);
  - `test_keys_review_flow`: `Right/Left` двигают `session.current`; `Enter` принимает (текст блока меняется, переход к следующей — `session.current` другая); `Ctrl+Z` возвращает текст и пометку; в режиме правки (вставка) `Right` двигает курсор, а не пометку;
  - `test_accept_all_one_undo`: «Принять все ошибки» → `counts["errors"] == 0`; один `Ctrl+Z` возвращает всё;
  - `test_check_level_is_not_accepted_by_accept_all`;
  - `test_manual_fix_and_skip_and_dictionary` (в словарь — слово записано в `storage.Dictionary()`, все такие же слова в документе серые/сняты);
  - `test_dictionary_write_failure_shows_notice_and_keeps_mark`: `Dictionary.add` бросает `OSError` → пометка остаётся `OPEN`, `NoticeBar` виден;
  - `test_empty_paste_shows_no_text_message_and_does_not_start` (Review Focus 1);
  - `test_paste_html_creates_editable_document_with_formatting`: буфер с `<b>`; после проверки и исправления «Скопировать с оформлением» кладёт в буфер итог;
  - `test_save_copy_next_to_original_and_original_untouched`: `Имя (исправлено).docx` существует, исходный файл не изменился (сравнить байты);
  - `test_save_as_same_path_is_refused_and_existing_file_asks`: `QMessageBox.question` вызывается ровно один раз при перезаписи чужого файла; ответ «Нет» → файл не тронут;
  - `test_save_failure_offers_save_as` (папка без прав, пропуск под root);
  - `test_closing_during_check_kills_child_and_ignores_late_messages` (Review Focus 3): `open_path` → сразу `close_document()` и открытие другого документа: `controller` старого — `state` не `done`, процесс мёртв, сессия нового документа без чужих пометок;
  - `test_crash_shows_notice_with_resume_button` (фабрики из `fakes:make_crashing_factories`, затем исправные);
  - `test_unsaved_changes_ask_before_closing`: три ответа QMessageBox (Сохранить / Не сохранять / Отмена) → файл сохранён / окно закрыто / документ остался;
  - `test_opening_unsupported_extension_shows_message_and_stays_on_start` («Формат «.pdf» не поддерживается…»);
  - `test_open_runs_in_thread`: во время открытия цикл событий обрабатывается (`qtbot.wait(10)` не блокируется; `OpenTask` с подменённым `open_document`, спящим 0,3 с).
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать, держа файл читаемым: `MainWindow` только собирает части и подписывает сигналы; логику показа карточки вынести в метод `_refresh()` (счётчики, карточка, рамка текущей пометки, `checked_until`). **Step 4:** `../venv-app/bin/python -m pytest tests/ui/test_main_window.py -q` — PASS. **Step 5: Commit** (`feat: main window and review flow`).

---

### Task 13: Справка F1, словарь, настройки

**Files:**
- Create: `app/zhiraf/ui/dialogs.py`, `app/tests/ui/test_dialogs.py`
- Modify: `app/zhiraf/ui/main_window.py` (меню «Словарь…», «Настройки…», F1)

**Interfaces:**
- Produces:
  - `HOTKEYS: List[Tuple[str, str]]` — `("← →", "К предыдущей или следующей пометке")`, `("Enter", "Принять исправление")`, `("Ctrl+Z", "Отменить последнее действие")`, `("Ctrl+O", "Открыть документ")`, `("Ctrl+V", "Вставить текст")`, `("Ctrl+S", "Сохранить исправленную копию")`, `("Esc", "Вернуться к разбору пометок")`, `("F1", "Эта справка")`; `HotkeysDialog(parent)` показывает список.
  - `DictionaryDialog(dictionary, parent)`: список слов (`Dictionary.words()`), поиск (фильтр без учёта регистра), «Удалить» (выбранные), «Выгрузить…» (`Dictionary.export`), «Загрузить…» (`Dictionary.import_from`, слова объединяются, в заголовке «добавлено N»); `OSError` на любой записи → сообщение в диалоге, список остаётся как был (откат из Task 1).
  - `SettingsDialog(settings, parent)`: три галочки — «Показывать пометки «проверьте»», «Строгий режим: заглавные буквы посреди предложения», «Запоминать недавние документы»; применение пишет `Settings.set`, `OSError` → сообщение, прежние значения; изменения «Показывать «проверьте»» применяются к уже найденному сразу (окно перерисовывает; новые находки фильтруются контроллером), «Строгий режим» — со следующей проверки (в диалоге подпись «Начнёт действовать при следующей проверке»).

- [ ] **Step 1: Failing tests:** `HOTKEYS` содержит все восемь строк, `HotkeysDialog` показывает их; `F1` в `MainWindow` открывает `HotkeysDialog` (подмена `exec_`); словарь: поиск «жир» оставляет «Жирафик»; удаление убирает слово и из файла; `import_from` из cp1251-файла; сбой записи (папка вместо файла) → сообщение и прежний список; настройки: галочки отражают `Settings`, «Принять» пишет, сбой записи → прежние значения; снятие «Показывать «проверьте»» в окне с готовыми пометками прячет жёлтые пометки.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS (`tests/ui`). **Step 5: Commit** (`feat: hotkeys help, dictionary and settings dialogs`).

---

### Task 14: Запуск, один экземпляр, журнал, охранные тесты

**Files:**
- Create: `app/zhiraf/ui/app.py`, `app/zhiraf/ui/__main__.py`, `app/tests/ui/test_app.py`, `app/tests/ui/test_guards.py`
- Modify: `app/zhiraf/__init__.py` (ничего, если не нужно), `app/tests/test_constraints.py` (если нужно расширить список)

**Interfaces:**
- Produces: `app.main(argv=None) -> int` — создаёт `QApplication` (имя «Жираф.Корректор», стиль `theme.stylesheet()`), берёт `QLockFile(<data_dir>/запущено.lock)` с `tryLock(0)`: занято (живой экземпляр) → `QMessageBox` «Жираф.Корректор уже запущен. Закройте его окно или найдите на панели задач.» и код 0; `storage.clean_tmp()` — только после взятой блокировки; `missing_models(models_dir())` не `None` → `QMessageBox.critical` с этим текстом и код 2; аргумент командной строки — путь к файлу открывается сразу (двойной щелчок по файлу); `sys.excepthook` пишет в `<data_dir>/журнал.txt` строку `время · safe_error_detail(exc)` (файл усекается, если больше 200 КБ) и показывает «Что-то пошло не так. Подробности записаны в журнал.» Запуск: `python -m zhiraf.ui` (`__main__.py` вызывает `main`). Функция `acquire_single_instance() -> Optional[QLockFile]` и `log_error(exc)` публичны для тестов.

- [ ] **Step 1: Failing tests:**
  - `test_app.py`: `acquire_single_instance()` дважды подряд — второй вызов `None`, после `unlock()` — снова lock; `log_error(ValueError("секретный текст"))` пишет в журнал имя класса и `файл:строка:функция`, и в файле нет «секретный текст»; журнал усекается; `main(["--check-models-only"])`-подобный путь не нужен — вместо этого `main` с несуществующей папкой моделей (`ZHIRAF_MODELS`) возвращает 2 и вызывает `QMessageBox.critical` (подмена).
  - `test_guards.py` (подпроцессы с чистым интерпретатором, `QT_QPA_PLATFORM=offscreen`): 
    1. `test_window_process_stays_light`: `python -c "import zhiraf.ui.main_window, sys; ..."` создаёт `MainWindow` (с `QApplication`) и печатает, какие из `onnxruntime tokenizers numpy spellcheck.checker spellcheck.sage torch` попали в `sys.modules`; ожидается пустой список; затем после `open_path` и завершённой проверки с фейковыми фабриками в процессе окна по-прежнему ни одного из них;
    2. `test_no_network_qt_modules_loaded`: после создания окна в `sys.modules` нет `PySide2.QtNetwork`, `PySide2.QtWebEngineWidgets`, `PySide2.QtQml`; нет `socket`-подмодулей из `FORBIDDEN`-списка, кроме тех, что тянет сам интерпретатор (`socket` может быть загружен `multiprocessing` — тест проверяет именно `PySide2.Qt*`, а сетевой код приложения закрыт AST-тестом);
    3. `test_second_launch_is_refused`: два процесса `python -m zhiraf.ui` с `ZHIRAF_HOME` в `tmp_path`: второй завершается кодом 0 за секунды и не создаёт окна (подмена диалога переменной окружения `ZHIRAF_TEST_NO_DIALOG=1`, при которой `main` пишет сообщение в `stderr`);
    4. `test_no_document_text_in_log_after_crash`: фабрики роняют процесс проверки; в `журнал.txt` и в выводе нет ни слова из текста документа.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** Полный набор: `../venv-app/bin/python -m pytest -q` — Expected: всё зелёное (включая vermin и AST-тест сети). Затем `../venv-app/bin/python -m pytest -m slow -q` — Expected: сквозной тест ядра по-прежнему проходит.
- [ ] **Step 5: Ручная проверка** (запуск настоящего окна после тестов): `QT_QPA_PLATFORM=xcb ../venv-app/bin/python -m zhiraf.ui` — на стартовом экране видна картинка, «Вставить текст» с настоящим текстом из `~/Downloads/*.docx` (скопировать абзацы), пометки появляются по мере проверки, карточка стоит под пометкой, ← → Enter работают, «Принять все ошибки» показывает подсказку, F1 открывает справку, «Сохранить исправленную копию» создаёт «Имя (исправлено).docx», окно закрывается без зависших процессов (`pgrep -f zhiraf` пусто). Результат приложить скриншотами к отчёту задачи.
- [ ] **Step 6: Commit** (`feat: app entry point, single instance, error log`).

---

## Self-Review

**Покрытие спеки.** Вариант B (текст + широкая карточка) — задачи 5, 6, 12; значки и цвета подписей — 3, 7; тема жирафа — 3; прогресс с % / осталось / готово к — 7; стрелки, Enter, автопереход — 12 (переход делает `ReviewSession`); «Принять все ошибки» с «?» внутри и подсказкой — 7; стартовый экран и недавние — 11; F1 — 13; офлайн — глобальное ограничение и 3, 14; вставка с форматированием, «Скопировать с оформлением» — 9, 10; сохранение в любом формате — 10; открытый документ показывает пометки на месте и копия «(исправлено)» — 5, 10, 12; форматы — 12; Word-интеграции нет; словарь/настройки — 13; ошибки раздела 10 — 8, 12, 14; безопасность раздела 9 — 3, 14. Отложенное из плана 1: сбой записи — 1, 12, 13; перезапись при «Сохранить как» — 10, 12; открытие в потоке — 9, 12; один экземпляр/tmp по PID — 1, 14. Новое требование «структура» — 2.

**Согласованность имён.** `sentence_kinds`, `structure`/`context_structure`, `CheckController.start/stop/resume/recheck/close`, `paragraph_runs/final_spans/final_paragraphs/display_range`, `ReviewEditor.load/repaint_paragraphs/show_current/set_checked_until/flush_edits`, `MARK_PROP`/`BASE_UNDERLINE_PROP` (определяются в `editor.py`, `clipboard.spans_from_block` импортирует их оттуда), `MarkCard.show_mark/card_position`, `StatusPanel.set_counts/accept_all_button`, `NoticeBar.show_notice` — одинаковы во всех задачах. Сигнатуры ядра взяты из кода как есть (`add_findings(paragraph, offset, findings, version=None)`, `CheckJob(..., resume_from=None)`, `save_document(doc, replacements, dst=None)`).

**Допущения для проверки при исполнении.** (1) Колёса PySide2 5.15.2.1: Windows `cp35…cp310-none-win_amd64`, Linux `abi3-manylinux1` — найдены; Qt-библиотеки в колесе включают `QtNetwork`, поэтому план 3 обязан вырезать его из поставки. (2) Offscreen-платформа требует системных `libxkbcommon/libEGL/fontconfig`; шрифтов в offscreen мало, тесты не зависят от пикселей. (3) Обновление `setUndoRedoEnabled` при программной перерисовке стирает историю правки пользователя — принято (перерисовка идёт только при событиях проверки).

**Пропорция.** Задач 14; код приведён только там, где его определяют тесты или формат (тесты Task 1, 6, 7).
