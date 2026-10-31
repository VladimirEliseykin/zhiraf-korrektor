"""End-to-end check of the shipped Windows folder inside the Windows 7 VM (the job started by run.cmd).

Two modes, both run on the VM with the Python of the shipped folder:
  driver <results> <dist on the CD> <job folder>   (python.exe from the CD) copies the folder to the desktop
      under a Cyrillic path with a space, starts the check under that copy's pythonw.exe, then the real exe.
  check <root> <results> <work>                    (the copy's pythonw.exe, no console, like the shipped program)
      drives the window and writes gui7.txt and win-*.png to the results folder. Never prints.
Document texts are never written: only counts, states, sizes and yes/no answers.
"""
import hashlib
import json
import shutil
import os
import subprocess
import sys
import time
import traceback

OUT = WORK = LOG = ROOT = app = None
FORBIDDEN_FILE = "forbidden.json"
state = {}


def say(*parts):
    LOG.write(" ".join(str(p) for p in parts) + "\n")
    LOG.flush()


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def step(name, func):
    say("--- %s" % name)
    try:
        func()
    except Exception:
        say("FAILED", traceback.format_exc())


# Qt and the window are imported in run() only: the spawned check child re-imports this file and must stay light
QEventLoop = MainWindow = zhiraf = models_dir = storage = zapp = export = theme = None


def wait(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents(QEventLoop.AllEvents, 100)
        if cond():
            return True
        time.sleep(0.02)
    return False


def lock():
    first = zapp.acquire_single_instance()
    second = zapp.acquire_single_instance()
    say("lock taken", first is not None, "second refused", second is None)
    env = dict(os.environ, ZHIRAF_TEST_NO_DIALOG="1")
    started = time.time()
    done = subprocess.run([os.path.join(ROOT, "python", "python.exe"), "-m", "zhiraf.ui"], env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    say("second launch rc", done.returncode, "secs %.1f" % (time.time() - started),
        "stderr", done.stderr.decode("utf-8", "replace").strip()[:200])
    first.unlock()


def window():
    w = MainWindow(models_dir(), log_detail=zapp.log_error_detail)
    w._say = lambda kind, text, buttons=None: say("DIALOG", kind, text) or 0
    w._ask_save_before_close = lambda *a, **k: "discard"
    w.resize(1100, 700)
    w.show()
    state["w"] = w
    say("heavy modules after window", [m for m in ("onnxruntime", "tokenizers", "spellcheck.checker", "torch")
                                       if m in sys.modules])


def check_docx():
    w = state["w"]
    docx = os.path.join(WORK, "Образец.docx")
    state["before"] = digest(docx)
    started = time.time()
    w.open_path(docx)
    ok = wait(lambda: w.controller is not None and w.controller.state in ("done", "failed", "stopped"), 900)
    c = w.controller
    say("check finished", ok, "state", c.state if c else None, "secs %.1f" % (time.time() - started),
        "counts", w.session.counts() if w.session else None, "error", c.error if c else None)
    say("marks", [(m.paragraph, m.start, m.end, m.rule, m.level) for m in w.session.marks][:20])
    say("heavy modules after check", [m for m in ("onnxruntime", "tokenizers", "spellcheck.checker", "torch")
                                      if m in sys.modules])
    wait(lambda: False, 1)
    w.grab().save(os.path.join(OUT, "win-review.png"))
    button = w.status.accept_all_button
    image = button.grab().toImage()
    paper = theme.COLORS["paper"].lower()
    skipped = theme.COLORS["skipped"].lower()
    hits = 0
    for x in range(8, min(26, image.width())):
        for y in range(image.height()):
            name = image.pixelColor(x, y).name().lower()
            hits += name in (paper, skipped)
    say("help badge pixels", hits, "button", button.size().width(), "x", button.size().height(),
        "enabled", button.isEnabled(), "visible", button.isVisible())
    button.grab().save(os.path.join(OUT, "win-accept-all.png"))


def save_and_export():
    w = state["w"]
    if w.session.counts().get("errors"):
        w._accept()
    w.save_copy()
    docx = os.path.join(WORK, "Образец.docx")
    copy = os.path.join(WORK, "Образец (исправлено).docx")
    say("corrected copy exists", os.path.isfile(copy), "original unchanged", digest(docx) == state["before"])
    pdf = os.path.join(WORK, "Образец.pdf")
    export.save_as(w.doc, w.session, pdf)
    with open(pdf, "rb") as f:
        data = f.read()
    say("pdf bytes", len(data), "starts", data[:5], "arial font", b"Arial" in data, "no part file",
        not os.path.exists(pdf + ".part"))
    w.copy_with_formatting()
    say("clipboard text length", len(app.clipboard().text()), "html", "<" in app.clipboard().mimeData().html())


def open_doc():
    w = state["w"]
    w.close_document()
    doc = os.path.join(WORK, "Образец.doc")
    started = time.time()
    w.open_path(doc)
    responsive = wait(lambda: False, 0.3) is False
    ok = wait(lambda: w.doc is not None and w.doc.path == doc, 120)
    say(".doc opened", ok, "secs %.1f" % (time.time() - started), "kind", w.doc.kind if w.doc else None,
        "editable", w.doc.editable if w.doc else None, "notice", w.notice.text_label.text()[:120],
        "loop ran", responsive)
    if ok:
        wait(lambda: w.controller is not None and w.controller.state in ("done", "failed", "stopped"), 600)
        say(".doc check", w.controller.state, w.session.counts())


def shortcut_step():
    """First start: the question is answered "yes" (ask replaced), the link must appear on the desktop."""
    from zhiraf.ui import shortcut
    w = state["w"]
    desktop = shortcut.desktop_dir()
    link = os.path.join(desktop, shortcut.LINK_NAME) if desktop else None
    say("desktop", desktop, "launcher", shortcut.launcher_path(), "link before", bool(link and os.path.exists(link)),
        "offered before", w.settings["shortcut_offered"])
    asked = []
    shortcut.offer_shortcut(w, w.settings, ask=lambda window: asked.append(1) or True)
    say("question asked", len(asked), "link created", bool(link and os.path.isfile(link)),
        "link bytes", os.path.getsize(link) if link and os.path.isfile(link) else None,
        "offered after", w.settings["shortcut_offered"])
    if link and os.path.isfile(link):
        try:
            from comtypes.client import CreateObject
            from comtypes.persist import IPersistFile
            from comtypes.shelllink import ShellLink
            sl = CreateObject(ShellLink)
            sl.QueryInterface(IPersistFile).Load(link, 0)
            target = sl.GetPath(0)
            target = target[0] if isinstance(target, tuple) else target
            say("link target is the launcher", os.path.normcase(str(target)) ==
                os.path.normcase(shortcut.launcher_path()), "target", target)
        except Exception:
            say("link target unreadable", traceback.format_exc()[-300:])
    with open(os.path.join(storage.data_dir(), "настройки.json"), encoding="utf-8") as f:
        say("settings file shortcut_offered", json.load(f).get("shortcut_offered"))
    asked.clear()
    shortcut.offer_shortcut(w, w.settings, ask=lambda window: asked.append(1) or True)
    say("question asked again", len(asked))


def is_forbidden(name, rules):
    return (any(name == f or name.startswith(f + ".") for f in rules["stdlib"])
            or any(name.startswith(prefix) for prefix in rules["qt"]))


def forbidden_modules():
    """Names the build removed (the list is embedded in the job: build/ is not shipped) that are loaded anyway."""
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), FORBIDDEN_FILE), encoding="utf-8") as f:
        rules = json.load(f)
    return sorted(m for m in list(sys.modules) if is_forbidden(m, rules)), sum(len(v) for v in rules.values())


def forbidden_step():
    loaded, count = forbidden_modules()
    say("forbidden names checked", count, "loaded in the window process", loaded)
    # the import graph of the program without a window, in a fresh interpreter of the shipped folder
    code = ("import json, sys; sys.path.insert(0, %r); import win_check; import zhiraf.ui.main_window, "
            "zhiraf.ui.app; print(win_check.forbidden_modules()[0])" % os.path.dirname(os.path.abspath(__file__)))
    done = subprocess.run([os.path.join(ROOT, "python", "python.exe"), "-c", code], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=180)
    say("forbidden after importing the program in a fresh interpreter rc", done.returncode,
        done.stdout.decode("utf-8", "replace").strip(), done.stderr.decode("utf-8", "replace").strip()[-300:])


def close_window():
    w = state["w"]
    started = time.time()
    w.close()
    wait(lambda: not w.isVisible(), 10)
    say("window closed secs %.1f" % (time.time() - started), "hard_exit", w.hard_exit)


def run():
    global OUT, WORK, LOG, ROOT, app, QEventLoop, MainWindow, zhiraf, models_dir, storage, zapp, export, theme
    ROOT, OUT, WORK = sys.argv[2], sys.argv[3], sys.argv[4]
    LOG = open(os.path.join(OUT, "gui7.txt"), "w", encoding="utf-8")
    say("python", sys.version.split()[0], "exe", sys.executable, "root", ROOT)
    from PySide2 import __version__ as pyside_version
    from PySide2.QtCore import QEventLoop
    from PySide2.QtWidgets import QApplication
    import zhiraf
    from zhiraf import models_dir, storage
    from zhiraf.ui import app as zapp, export, theme
    from zhiraf.ui.main_window import MainWindow
    app = QApplication(sys.argv[:1])
    say("pyside", pyside_version, "platform", app.platformName())
    app.setStyleSheet(theme.stylesheet())
    say("data_dir", storage.data_dir(), "models", models_dir(), "missing", zhiraf.missing_models(models_dir()))
    for name, func in (("lock", lock), ("window", window), ("check docx", check_docx),
                       ("save and export", save_and_export), ("open .doc", open_doc), ("shortcut", shortcut_step),
                       ("forbidden modules", forbidden_step), ("close", close_window)):
        step(name, func)
    log_path = os.path.join(storage.data_dir(), "журнал.txt")
    say("error log", open(log_path, encoding="utf-8").read()[-500:] if os.path.isfile(log_path) else "(none)")
    say("=== end")
    LOG.close()


def driver():
    """Runs under python.exe of the CD copy: stages the folder, runs the check, then the real exe."""
    import ctypes
    results, source, job = sys.argv[2:5]
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
    desktop = buf.value
    root = os.path.join(desktop, "Жираф Корректор тест")
    work = os.path.join(desktop, "Жираф Образцы тест")
    tools = os.path.join(os.environ["USERPROFILE"], "zhjob")
    data = os.path.join(os.environ["APPDATA"], "Жираф.Корректор")
    log = open(os.path.join(results, "driver7.txt"), "w", encoding="utf-8")

    def say_(*parts):
        log.write("%s %s\n" % (time.strftime("%H:%M:%S"), " ".join(str(p) for p in parts)))
        log.flush()

    def processes():
        done = subprocess.run(["wmic", "process", "where", "name='pythonw.exe' or name='python.exe' or "
                               "name like 'Жираф%'", "get", "ProcessId,ParentProcessId,Name,CommandLine",
                               "/format:list"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = done.stdout.decode("cp866", "replace")
        entries = [e for e in text.replace("\r", "").split("\n\n") if "Name=" in e]
        names = [dict(l.split("=", 1) for l in e.strip().split("\n") if "=" in l) for e in entries]
        return names

    def show(label):
        found = processes()
        say_(label, "pythonw", sum(1 for p in found if p.get("Name") == "pythonw.exe"),
             "python", sum(1 for p in found if p.get("Name") == "python.exe"))
        for p in found:
            say_("   ", p.get("Name"), "pid", p.get("ProcessId"), "parent", p.get("ParentProcessId"),
                 p.get("CommandLine", "")[-150:])

    say_("driver", sys.version.split()[0], sys.executable)
    say_("desktop", desktop, "free GB", shutil.disk_usage(desktop).free // 2 ** 30)
    def unlock(func, path, _):   # files copied from the CD are read-only
        os.chmod(path, 0o700)
        func(path)

    for folder in (root, work, tools):
        if os.path.exists(folder):
            shutil.rmtree(folder, onerror=unlock)
    for name in ("журнал.txt", "настройки.json"):   # a clean first start
        path = os.path.join(data, name)
        if os.path.isfile(path):
            os.remove(path)
    link = os.path.join(desktop, "Жираф.Корректор.lnk")
    if os.path.isfile(link):
        os.remove(link)
    started = time.time()
    shutil.copytree(source, root)
    say_("folder copied secs %.0f" % (time.time() - started), "to", root,
         "files", sum(len(f) for _, _, f in os.walk(root)))
    shutil.copytree(os.path.join(job, "work"), work)
    os.makedirs(tools)
    for name in ("win_check.py", FORBIDDEN_FILE):
        shutil.copy(os.path.join(job, name), tools)
    shutil.copy(os.path.join(work, "Образец.docx"), os.path.join(work, "Образец 2.docx"))

    say_("[check] window under pythonw.exe of the copy")
    child = subprocess.Popen([os.path.join(root, "python", "pythonw.exe"), os.path.join(tools, "win_check.py"),
                              "check", root, results, work])
    started = time.time()
    marks = [30, 120, 300]
    while child.poll() is None and time.time() - started < 50 * 60:
        time.sleep(5)
        if marks and time.time() - started > marks[0]:
            show("running +%ds" % marks.pop(0))
    if child.poll() is None:
        child.kill()
        say_("check killed at the deadline")
    say_("check exit=%s secs %.0f" % (child.poll(), time.time() - started))

    say_("[clipboard] after the window process ended")
    done = subprocess.run([os.path.join(root, "python", "python.exe"), "-c",
                           "from PySide2.QtWidgets import QApplication; a=QApplication([]); t=a.clipboard().text(); "
                           "print(len(t))"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    say_("clipboard text length after exit", done.stdout.decode().strip(), "rc", done.returncode,
         done.stderr.decode("utf-8", "replace").strip()[-200:])

    say_("[exe] the real launcher with a document of a Cyrillic path with a space")
    exe = os.path.join(root, "Жираф.Корректор.exe")
    doc = os.path.join(work, "Образец 2.docx")
    program = subprocess.Popen([exe, doc], cwd=work)
    time.sleep(150)
    say_("shot-now")
    time.sleep(30)
    show("window of the real exe")
    subprocess.run(["taskkill", "/f", "/t", "/im", "pythonw.exe"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    say_("launcher exit", program.poll())
    path = os.path.join(data, "журнал.txt")
    say_("error log size", os.path.getsize(path) if os.path.isfile(path) else "(none)")
    say_("link on desktop", os.path.isfile(link))
    say_("=== end")
    log.close()


# the check runs in a spawned child that re-imports this file as __mp_main__: only the real start runs the job
if __name__ == "__main__":
    if sys.argv[1] == "driver":
        driver()
    else:
        run()
