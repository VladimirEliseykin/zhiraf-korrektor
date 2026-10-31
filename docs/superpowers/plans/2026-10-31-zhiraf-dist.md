# Жираф.Корректор: поставка для Windows 7 — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать на Linux одной командой папку «Жираф.Корректор», которая на голой Windows 7 x64 SP1 (4 ГБ, без интернета, без прав администратора) запускается двойным щелчком по «Жираф.Корректор.exe».

**Architecture:**
- Сборка — пакет `build/` в репозитории (Python 3.8 хоста, venv-app). Шаги сборки:
  1. скачивает по закреплённому списку (URL + sha256) встраиваемый Python 3.7.9, колёса win_amd64, UCRT и набор llvm-mingw;
  2. раскладывает папку;
  3. вырезает сетевые модули;
  4. компилирует маленький запускатель на C с иконкой-шаром;
  5. проверяет результат: при нарушении сборка падает.
- Программа получает предложение создать ярлык при первом запуске.
- Готовность подтверждает сквозной прогон папки в VM Windows 7.

**Tech Stack:** Python 3.8 (сборка), C + llvm-mingw (запускатель), PySide2 5.15.2.1, embeddable CPython 3.7.9, xorriso + QEMU (проверка в VM).

**Spec:** `docs/superpowers/specs/2026-10-04-zhiraf-korrektor-design.md` (разделы 2, 3, 8, 9, 11). Окно — план 2 (`2026-10-31-zhiraf-window.md`, влит в `main`).

## Global Constraints

- Windows 7 x64 SP1 без обновлений, от 4 ГБ памяти, без прав администратора, без интернета (спека §2). Программа обязана работать и там, где нет KB2999226 (UCRT) и Visual C++ 2015–2019: эти DLL лежат в папке программы (§3, §8: «Visual C++ рядом с программой (на голой Win7 их нет)»).
- Одна папка, копируется куда угодно (флешка, рабочий стол, путь с кириллицей и пробелами). Без установщика, без записи в реестр, без автообновления (§8, §12).
- Ни строки сетевого кода. Сборка проверяет, что в папку не попали сетевые модули (`socket`, `ssl`, `urllib`, `http`, `QtNetwork`, …) и что код программы их не импортирует; при нарушении сборка падает (§9). Решение по исключению — в задаче 3.
- Всё скачанное сверяется с sha256 из `build/deps.lock`; несовпадение — сборка падает. Никаких «последних версий»: только закреплённые.
- Код в `app/zhiraf/**` и `engine/**` остаётся совместимым с Python 3.7 (vermin). Код `build/**` запускается только на хосте (3.8) и в поставку не попадает.
- Документы пользователя, эталоны, `spike/`, личные данные не попадают ни в поставку, ни в коммиты.
- Тяжёлые шаги на хосте (сборка папки ~7,5 ГБ, ISO) запускаются с ограничением: `systemd-run --user --wait --collect -p MemoryMax=4G -p MemorySwapMax=1G -p CPUQuota=400% -p IOWeight=10 nice -n 19 …`.
- Процессы не убивать по шаблону — только по PID.

## Review Focus

1. Папка лежит по пути с кириллицей и пробелами («C:\Users\Иван\Рабочий стол\Жираф.Корректор»). Запускатель и программа должны работать (широкие строки WinAPI, кавычки в командной строке). Покрывают задачи 4 и 7.
2. Документ передан запускателю двойным щелчком или перетаскиванием на ярлык («Жираф.Корректор.exe» "C:\Мои документы\отчёт 2.docx"). Файл открывается сразу, кавычки и пробелы целы. Задачи 4 и 7.
3. На машине нет UCRT и VC++: Python, onnxruntime и Qt берут DLL из папки программы, а не из System32. Задачи 2 и 7: проверка, что DLL на месте; прогон в VM при `PATH` без System32 невозможен, поэтому проверка сборки сверяет полный список имён.
4. Вырезанный сетевой модуль всё-таки нужен какому-то пути программы: открытие `.doc`, PDF, `pathlib.as_uri`, `multiprocessing`. Программа не должна упасть с `ModuleNotFoundError`. Задача 3: прогон окна и проверки с блокировкой вырезанных модулей.
5. Повторный запуск, когда ярлык уже создан или рабочий стол недоступен (перенаправленный профиль, нет прав). Предложение больше не появляется, сбой создания — спокойное сообщение. Задача 5.

## File Structure

```
build/__init__.py
build/deps.lock              закреплённые URL + sha256 + куда класть (формат ниже)
build/fetch.py               скачивание в кэш со сверкой sha256
build/layout.py              раскладка папки: python/, колёса, _pth, app/, engine/, art/, models/, DLL
build/prune.py               вырезание: список запрещённых путей + пересборка python37.zip без сетевых модулей
build/check_dist.py          проверка готовой папки (§9) — код выхода 1 при нарушении
build/icon.py                logo.png → zhiraf.ico (Qt)
build/launcher/launcher.c    запускатель
build/launcher/launcher.rc   иконка + версия
build/make_launcher.py       компиляция llvm-mingw → «Жираф.Корректор.exe»
build/build_dist.py          точка входа: fetch → layout → prune → launcher → check
build/vm/run.cmd, build/vm/win_check.py   задание для VM Windows 7 (из payload7, перенесено в репозиторий)
build/make_iso.sh            ISO для VM (xorriso)
app/zhiraf/ui/shortcut.py    ярлык на рабочем столе (comtypes.shelllink)
tests/build/test_*.py        тесты сборки (папка tests/build рядом с app/tests не нужна: тесты в app/tests/build/)
```

Раскладка поставки (корень = «Жираф.Корректор/»; `zhiraf.ROOT` = корень, потому что `app/zhiraf/__init__.py` считает ROOT как родителя `app/`):

```
Жираф.Корректор.exe
python/      pythonw.exe, python.exe, python37.dll, python37.zip, *.pyd, python37._pth, UCRT+VC DLL, Lib/site-packages/
app/zhiraf/
engine/spellcheck/   engine/art/start.jpg
models/{commas,commas-2,commas-3,forms,forms-2,forms-3,sage,spell,vocab.tsv}
ЧИТАЙ-МЕНЯ.txt
```

`python37._pth` (CRLF): `python37.zip`, `.`, `Lib\site-packages`, `..\app`. `engine/` добавляет в путь `zhiraf/__init__.py`.

---

### Task 1: Закреплённые зависимости и скачивание

**Files:**
- Create: `build/__init__.py`, `build/deps.lock`, `build/fetch.py`, `app/tests/build/__init__.py`, `app/tests/build/test_fetch.py`

**Interfaces:**
- Produces:
  - `deps.lock` — строки `name<TAB>url<TAB>sha256<TAB>kind`; `kind` ∈ `python-embed | wheel | ucrt | toolchain`; `#` — комментарий.
  - `read_lock(path) -> List[Dep]` (`Dep = namedtuple("Dep", "name url sha256 kind")`); `fetch(dep, cache_dir) -> str` (путь к файлу в кэше); `fetch_all(lock_path, cache_dir) -> Dict[str, str]`.
  - `HashMismatch(Exception)` с именем файла в сообщении.
- Состав `deps.lock` (сверено на 2026-10-31; sha256 брать из PyPI JSON / страницы релиза, не считать по скачанному):
  - `python-3.7.9-embed-amd64.zip` (python.org);
  - колёса cp37 win_amd64 или py3-none-any: numpy 1.21.6, onnxruntime 1.14.1, tokenizers 0.19.1, pymorphy3 2.0.2, DAWG-Python 0.7.2, pymorphy3-dicts-ru 2.4.417150.4580142, lxml 4.9.3, olefile 0.47, comtypes 1.2.1, psutil 5.9.8, PySide2 5.15.2.1, shiboken2 5.15.2.1;
  - UCRT: пакет conda-forge `ucrt` 10.0.22621.0 (win-64, `.conda`) — `ucrtbase.dll` и `api-ms-win-*.dll` из `Library/bin`;
  - VC++ 2015–2019 runtime: `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`, `concrt140.dll` — берутся из колеса shiboken2, отдельной строки не нужно (задача 2);
  - llvm-mingw 20261020 ucrt-ubuntu-22.04-x86_64.
  Хэши PySide2/shiboken2/lxml/olefile/comtypes уже сверены: af6b263f…, a0d0fdeb…, 120fa934…, 543c7da2…, fe1f1012…
- [ ] **Step 1: Failing tests** (`test_fetch.py`, без сети: локальный HTTP-сервер не нужен, `fetch` принимает `file://` URL):
  - `read_lock` пропускает комментарии и пустые строки;
  - `fetch` по `file://` с верным sha256 кладёт файл в кэш и возвращает путь;
  - повторный `fetch` не копирует заново (время изменения файла кэша не меняется);
  - неверный sha256 → `HashMismatch`, в кэше нет ни файла, ни `*.part`;
  - файл в кэше испорчен → `fetch` замечает и скачивает заново;
  - в `deps.lock` у каждой строки 4 поля, sha256 из 64 hex, есть все имена из списка выше.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать: `urllib.request` (только хост, в поставку не идёт), запись в `.part` → проверка → `os.replace`. **Step 4:** PASS. **Step 5: Commit** (`feat: pinned Windows dependencies and verified download`).

### Task 2: Раскладка папки

**Files:**
- Create: `build/layout.py`, `app/tests/build/test_layout.py`

**Interfaces:**
- Consumes: `fetch_all` (Task 1).
- Produces: `lay_out(dist: str, files: Dict[str, str], repo: str, models: str, link_models: bool = True) -> None`. Создаёт раскладку из File Structure:
  - распаковывает embed-zip в `python/`;
  - распаковывает колёса в `python/Lib/site-packages`, кроме каталогов `*.data/scripts`;
  - пишет `_pth`;
  - кладёт UCRT DLL и VC DLL из `shiboken2/` в `python/`, рядом с `python.exe`;
  - копирует `app/zhiraf` и `engine/spellcheck` без `__pycache__` и без `tests`, `engine/art`;
  - кладёт модели: жёсткие ссылки при `link_models`, иначе копия;
  - пишет `ЧИТАЙ-МЕНЯ.txt` (3–5 строк по-русски: как запустить, что текст никуда не отправляется, куда пишется журнал).
- `REQUIRED_DLLS = ("ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")` — константа, её же использует `check_dist`.
- [ ] **Step 1: Failing tests** на маленьких поддельных архивах. Тест сам собирает zip «embed» с `python.exe`, `python37.zip`, `python37._pth` и два мини-колеса, одно с `shiboken2/msvcp140.dll`. Проверить:
  - `_pth` ровно 4 строки CRLF;
  - пакеты лежат в `python/Lib/site-packages`;
  - DLL из `REQUIRED_DLLS` лежат в `python/`;
  - `app/zhiraf/__init__.py` есть, а `__pycache__` нет;
  - модели — жёсткие ссылки (`os.stat(...).st_ino` совпадает);
  - повторный `lay_out` в непустую папку → `FileExistsError`: сборка всегда в чистую папку;
  - текст `ЧИТАЙ-МЕНЯ.txt` в UTF-8 с BOM (Блокнот Win7).
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS. **Step 5: Commit** (`feat: Windows folder layout`).

### Task 3: Вырезание сетевых модулей и проверка папки

**Files:**
- Create: `build/prune.py`, `build/check_dist.py`, `app/tests/build/test_prune.py`, `app/tests/ui/test_runs_without_network.py`

**Interfaces:**
- Produces:
  - `FORBIDDEN_STDLIB` — модули, которые удаляются из `python37.zip`, и `.pyd`/`.dll`:
    - `ssl`, `_ssl`, `http`, `urllib.request`, `urllib.response`, `urllib.error`, `urllib.robotparser`;
    - `ftplib`, `smtplib`, `smtpd`, `poplib`, `imaplib`, `nntplib`, `telnetlib`, `xmlrpc`, `socketserver`;
    - `asyncio`, `_asyncio`, `_overlapped`;
    - `wsgiref`, `webbrowser`, `mailbox`, `cgi`, `cgitb`;
    - `_msi`, `winsound`;
    - `libssl-1_1.dll`, `libcrypto-1_1.dll`, `_hashlib`. Встроенные `_sha*`/`_md5` в `python37.dll` остаются.
  - `FORBIDDEN_QT` — удаляется из `PySide2/`:
    - `QtNetwork*`, `Qt5Network.dll`;
    - `QtWebEngine*`, `Qt5WebEngine*`, `QtWebChannel*`, `QtWebSockets*`;
    - `QtQml*`, `QtQuick*`, `Qt5Qml*`, `Qt5Quick*`, `Qt3D*`, `Qt53D*`;
    - `QtMultimedia*`, `Qt5Multimedia*`, `QtPositioning*`, `QtLocation*`, `QtBluetooth*`, `QtNfc*`, `QtRemoteObjects*`, `QtSensors*`, `QtSerialPort*`, `QtScxml*`, `QtCharts*`, `QtDataVisualization*`;
    - `plugins/bearer`, `plugins/geoservices`, `plugins/position`, `plugins/sensors`, `plugins/qmltooling`, `plugins/webview`;
    - `qml/`, `translations/` (кроме `qtbase_ru.qm`), `examples/`, `include/`, `designer.exe`, `lupdate.exe` и прочие `*.exe`, кроме `QtWebEngineProcess.exe`, который удаляется вместе с WebEngine.
  - `prune(dist: str) -> List[str]` — удалённые пути (относительные).
  - `check(dist: str) -> List[str]` — нарушения, пустой список = чисто. Модуль `python -m build.check_dist <dist>` печатает нарушения и выходит с кодом 1. Проверяет:
    - (а) нет ни одного пути из `FORBIDDEN_*`, включая имена внутри `python37.zip`;
    - (б) AST всех `.py` в `app/` и `engine/` не импортирует сетевые модули: `socket`, `ssl`, `http`, `urllib.request`, `ftplib`, `smtplib`, `asyncio`, `PySide2.QtNetwork` и прочие;
    - (в) на месте все `REQUIRED_DLLS`, `python/pythonw.exe`, `Жираф.Корректор.exe`, `models/vocab.tsv`, `engine/art/start.jpg`, `app/zhiraf/ui/art/logo.png`.
- **Решение по `socket`:**
  - `socket.py`, `_socket.pyd` и `select.pyd` остаются в папке: `multiprocessing.connection` импортирует `socket` при загрузке, хотя на Windows проверка общается через каналы (Pipe), а не через сеть.
  - Код программы `socket` не импортирует — это проверяет пункт (б).
  - `check_dist` разрешает именно эти три имени и пишет об этом в выводе.
  - Это отступление от буквы §9, оно ради `multiprocessing`; записать в ЧИТАЙ-МЕНЯ.txt не нужно, записать в план и спеку: правка §9 — строка «socket остаётся: его требует multiprocessing; программа его не использует».
  - `urllib.parse` остаётся: `pathlib.as_uri` и lxml используют разбор строк, в нём нет сети.
- [ ] **Step 1: Failing tests:**
  - `test_prune.py` на поддельной папке: в `python37.zip` лежат `ssl.py`, `http/client.py`, `urllib/request.py`, `urllib/parse.py`, `json/__init__.py`; кроме того, `_ssl.pyd`, `PySide2/QtNetwork.pyd`, `PySide2/Qt5Network.dll`, `PySide2/plugins/bearer/x.dll`, `PySide2/translations/qtbase_ru.qm`, `qtbase_de.qm`. После `prune`:
    - в zip остались только `urllib/parse.py` и `json`;
    - сетевые файлы удалены;
    - `qtbase_ru.qm` на месте;
    - `check` пуст.
    - Обратный случай: `check` на папке с `QtNetwork.pyd` и с `app/zhiraf/x.py`, где есть `import socket`, даёт ровно два нарушения.
    - `python -m build.check_dist` на грязной папке возвращает код 1.
  - `test_runs_without_network.py` (slow не нужен: фейковые фабрики). Подпроцесс с `sys.meta_path`-блокировщиком: любой импорт модуля из `FORBIDDEN_STDLIB`/`FORBIDDEN_QT` → `ImportError`. В подпроцессе:
    1. создать `MainWindow`;
    2. открыть `.docx`, `.odt`, `.txt` и `.doc` из `docfactory` (`.doc` при наличии soffice);
    3. дождаться `done`;
    4. сохранить исправленную копию;
    5. сделать «Сохранить как» `.pdf`, `.odt`, `.txt`;
    6. скопировать с оформлением;
    7. закрыть окно.

    Ожидание: код 0 и ни одного `ImportError` в выводе. Блокировщик наследуется дочерним процессом проверки через `sitecustomize` в `PYTHONPATH`, создаваемом во временной папке теста.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать: `python37.zip` пересобирается во временный файл и подменяется через `os.replace`. **Step 4:** PASS. **Step 5: Commit** (`feat: strip network modules and check the folder`).

### Task 4: Запускатель «Жираф.Корректор.exe»

**Files:**
- Create: `build/icon.py`, `build/launcher/launcher.c`, `build/launcher/launcher.rc`, `build/make_launcher.py`, `app/tests/build/test_launcher.py`

**Interfaces:**
- Consumes: каталог llvm-mingw из `fetch_all` (Task 1).
- Produces:
  - `make_icon(png: str, ico: str) -> None`: QImage → `.ico` с размерами 16, 24, 32, 48, 64, 128, 256; запись через плагин Qt `ico`.
  - `make_launcher(toolchain_dir: str, out_exe: str, ico: str) -> None`: `x86_64-w64-mingw32-windres` (llvm-rc) и `x86_64-w64-mingw32-clang -municode -mwindows -Os -s -static`.
  - `launcher.c` (`wWinMain`):
    1. `GetModuleFileNameW` даёт папку exe;
    2. командная строка `"<папка>\python\pythonw.exe" -m zhiraf.ui` и затем ВСЯ исходная командная строка после имени exe как есть: хвост `GetCommandLineW()` после первого аргумента с учётом кавычек;
    3. `CreateProcessW` с `lpCurrentDirectory = <папка>`;
    4. при неудаче `MessageBoxW` «Не найден python\pythonw.exe рядом с программой. Скопируйте папку «Жираф.Корректор» целиком.» и код 1;
    5. иначе код 0, ждать завершения не нужно.

    Только `kernel32`/`user32`, без CRT-зависимостей сверх static.
  - `launcher.rc`: `1 ICON "zhiraf.ico"`; VERSIONINFO: ProductName «Жираф.Корректор», FileDescription «Проверка орфографии без интернета», CompanyName пусто.
- [ ] **Step 1: Failing tests** (`test_launcher.py`). Тесты, которым нужен llvm-mingw, помечаются `needs_toolchain`: skip, если кэша нет.
  - `make_icon` даёт `.ico`, `QImageReader` видит 7 размеров.
  - Разбор PE (свой минимальный парсер в тесте, `struct`):
    - `MZ` и `PE\0\0`;
    - Machine `0x8664`;
    - Subsystem `2` (GUI);
    - в секции ресурсов есть `RT_GROUP_ICON` и `RT_VERSION`;
    - импорты содержат только `KERNEL32.dll` и `USER32.dll` (никаких `api-ms-win-crt-*`, `msvcrt.dll`), потому что запускатель должен стартовать даже без UCRT.
  - Функция разбора хвоста командной строки вынесена в `launcher.c` как `static const wchar_t *args_after_program(const wchar_t *cmdline)`. Тест компилирует её хост-clang'ом из того же файла (`#ifdef LAUNCHER_TEST` с `main`, читающим строки из stdin) и сверяет таблицу:
    - `"C:\x\Жираф.Корректор.exe"` → `""`;
    - `"C:\x y\Ж.exe" "C:\Мои документы\отчёт 2.docx"` → `"C:\Мои документы\отчёт 2.docx"` в кавычках, как есть;
    - `C:\x\Ж.exe a b` → `a b`;
    - `"C:\x\Ж.exe"  "a"` → `"a"`.
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS. **Step 5: Commit** (`feat: Windows launcher with the balloon icon`).

### Task 5: Предложение создать ярлык

**Files:**
- Create: `app/zhiraf/ui/shortcut.py`, `app/tests/ui/test_shortcut.py`
- Modify: `app/zhiraf/ui/app.py` (после показа окна), `app/zhiraf/storage.py` (`DEFAULT_SETTINGS["shortcut_offered"] = False`)

**Interfaces:**
- Produces:
  - `launcher_path() -> Optional[str]`: `os.path.join(zhiraf.ROOT, "Жираф.Корректор.exe")`, если такой файл есть и `sys.platform == "win32"`, иначе `None`. В разработке и на Linux предложения нет.
  - `desktop_dir() -> Optional[str]`: `SHGetFolderPathW(CSIDL_DESKTOPDIRECTORY)` через `ctypes`, `None` при сбое.
  - `create_desktop_shortcut(target: str, desktop: str) -> str`: `comtypes.shelllink.ShellLink`, путь `<desktop>\Жираф.Корректор.lnk`, рабочая папка — папка exe, иконка — сам exe. Возвращает путь; при сбое `OSError` (COM-ошибка оборачивается).
  - `offer_shortcut(window, settings, ask=None, create=create_desktop_shortcut) -> None`. Если `launcher_path()` и `settings["shortcut_offered"]` ложь, функция спрашивает «Создать ярлык «Жираф.Корректор» на рабочем столе?» (Да/Нет). Затем `settings.set("shortcut_offered", True)` при любом ответе, а `OSError` от `settings.set` молча игнорируется. При «Да» вызывается `create`; при `OSError` или `desktop_dir() is None` — NoticeBar «Не удалось создать ярлык: рабочий стол недоступен.». Ярлык уже есть — не перезаписывать, считать успехом.
- [ ] **Step 1: Failing tests:**
  - на Linux `launcher_path() is None` и вопрос не задаётся;
  - с подменой `launcher_path` / `desktop_dir` / `ask` / `create`: «Да» → `create` вызван один раз и `shortcut_offered` стал True;
  - второй вызов → вопроса нет;
  - «Нет» → `create` не вызван, флаг True;
  - `create` бросает `OSError` → NoticeBar с текстом выше, без исключения;
  - ярлык существует → `create` не вызван, вопроса нет;
  - `app.main` вызывает `offer_shortcut` после `window.show()` (подмена).
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать (импорт `comtypes` только внутри `create_desktop_shortcut`; vermin 3.7). **Step 4:** PASS. **Step 5: Commit** (`feat: offer a desktop shortcut on first start`).

### Task 6: Сборка одной командой

**Files:**
- Create: `build/build_dist.py`, `build/make_iso.sh`, `app/tests/build/test_build_dist.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `python -m build.build_dist --out <dir> [--cache ~/vm/win7/dist-cache] [--models engine/models] [--copy-models]`. Шаги: `fetch_all` → `lay_out` в `<out>/Жираф.Корректор.tmp` → `prune` → `make_icon` + `make_launcher` → `check` → переименование в `<out>/Жираф.Корректор`. Любое исключение или нарушение `check`: временная папка удаляется, код 1, в выводе — причина. В конце выводятся размер папки и число файлов. `make_iso.sh <dist> <job_dir> <iso>` — `xorriso -as mkisofs -iso-level 3 -J -joliet-long -R -V ZHIRAF -o <iso> -graft-points dist=<dist> job=<job_dir>`.
- [ ] **Step 1: Failing tests:**
  - с подделанными `fetch_all` / `make_launcher`: поддельные архивы из Task 2 и пустой exe-файл с `MZ` → папка `Жираф.Корректор` создана, `.tmp` нет, код 0;
  - `check` вернул нарушение → кода 1, папки нет;
  - вторая сборка в ту же `--out` с уже существующей папкой → код 1 с сообщением «уже есть, удалите её».
- [ ] **Step 2:** FAIL. **Step 3:** Реализовать. **Step 4:** PASS, затем настоящая сборка (под ограничением из Global Constraints): `python -m build.build_dist --out ~/vm/win7/dist` — код 0, `check_dist` чист, размер ≈ 7,5 ГБ. **Step 5: Commit** (`feat: one-command Windows build`).

### Task 7: Сквозная проверка в VM Windows 7

**Files:**
- Create: `build/vm/run.cmd`, `build/vm/win_check.py` (перенести из `~/vm/win7/payload7/job/`, уже отлажен), `build/vm/README.md` (как вставить ISO и прочитать результаты)

**Interfaces:**
- Consumes: папка из Task 6, VM (`~/vm/win7/start-vm.sh`, сокет монитора, `results.img`). Порядок работы с VM описан в `build/vm/README.md`: ISO вставляется через `change cd0`, результаты — `mtype -i results.img@@1048576`.
- [ ] **Step 1: Задание.** `run.cmd` делает следующее:
  1. копирует `dist\Жираф.Корректор` в `C:\Users\tester\Рабочий стол\Жираф Корректор тест` (кириллица и пробел, без прав администратора на запись вне профиля);
  2. запускает `win_check.py` под `python\pythonw.exe` поставки. Нужны правки: путь программы берётся из аргумента, `models` — из поставки, плюс проверка, что ни один из `FORBIDDEN_*` не загружен (`sys.modules`);
  3. запускает сам `Жираф.Корректор.exe "…\Образец 2.docx"` (кириллица и пробел в имени документа), ждёт 180 с и делает скриншот через монитор QEMU с хоста;
  4. в выводе `tasklist` должен быть ровно один `pythonw.exe` окна и дочерний процесс проверки до её конца;
  5. `ярлык`: проверка `shortcut_offered` в `%APPDATA%\Жираф.Корректор\настройки.json` после первого запуска (вопрос подтверждается из `win_check` подменой `ask`).

  ISO собирается через `make_iso.sh`.
- [ ] **Step 2: Прогон.** Ожидание:
  - в журнале задания `exit=0`;
  - `gui7.txt` даёт те же проверки, что в плане 2 (job7c): блокировка, проверка `done`, «?» виден, копия сохранена, оригинал цел, PDF с Arial, `.doc` открыт, буфер обмена жив после выхода;
  - сетевых модулей в `sys.modules` нет;
  - на скриншоте окно с пометками и документом из кириллического пути;
  - журнал ошибок пуст.

  Результаты записать в отчёт задачи (без текстов документов).
- [ ] **Step 3: Commit** (`test: end-to-end check of the Windows folder in a Win7 VM`).

---

## Self-Review

**Покрытие спеки.**
- §3, состав папки: задачи 2 и 6.
- «Visual C++ рядом»: задачи 1 и 2, проверка в задаче 3.
- §8: одна папка — задачи 2 и 6; exe с иконкой-шаром — задача 4; без установщика, без прав — задача 7 (путь в профиле); ярлык при первом запуске — задача 5; сборка скриптом на Linux и ISO для VM — задачи 6 и 7.
- §9: сеть вырезана, сборка падает при нарушении — задача 3; журнал без текста — уже в плане 2, проверяется в задаче 7.
- §11: сквозная проверка в VM 4 ГБ — задача 7.
- §2, «без обновлений Windows»: UCRT и VC++ в папке — задача 2. Прогон на VM без KB2999226 невозможен: в VM обновление уже стоит. Поэтому замена — проверка списка DLL и импорта запускателя, задачи 3 и 4. На ПК друга это первая проверка.

**Расхождения со спекой (решения).**
- `socket` остаётся (задача 3).
- Размер папки ≈ 7,5 ГБ вместо «~2,3 ГБ»: с тех пор в ансамбль добавлены модели. В спеке §8 поправить число.
- Раскладка `python/` в подпапке совпадает со спекой; `art/` из спеки — это `engine/art` и `app/zhiraf/ui/art`, менять код ради этого не нужно.

**Согласованность имён.** `REQUIRED_DLLS`, `FORBIDDEN_STDLIB`, `FORBIDDEN_QT`, `fetch_all`, `lay_out`, `prune`, `check`, `make_icon`, `make_launcher`, `offer_shortcut`, `launcher_path` одинаковы во всех задачах.
