"""The window's whole working path, run in a process whose network modules are blocked.

Started by test_runs_without_network.py (not collected by pytest). Settings come from the environment:
DRIVER_MODELS, DRIVER_FILES (os.pathsep-separated), DRIVER_OUT, DRIVER_FACTORIES, DRIVER_EXTRA_IMPORT."""
import importlib
import os
import sys
import time

from PySide2.QtWidgets import QApplication, QFileDialog, QMessageBox

from zhiraf.ui.main_window import MainWindow


def wait(app, predicate, what, seconds=90):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    print("TIMEOUT: " + what)
    sys.exit(3)


def main():
    if os.environ.get("DRIVER_EXTRA_IMPORT"):
        importlib.import_module(os.environ["DRIVER_EXTRA_IMPORT"])
    app = QApplication([])
    # every modal the window can open is replaced: an unpatched one would block the run
    MainWindow._say = lambda self, kind, text, buttons=None: QMessageBox.Yes if kind == "question" else 0
    MainWindow._ask_save_before_close = lambda self: "discard"
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))

    out = os.environ["DRIVER_OUT"]
    w = MainWindow(os.environ["DRIVER_MODELS"], factories=os.environ["DRIVER_FACTORIES"])
    w.show()
    for path in os.environ["DRIVER_FILES"].split(os.pathsep):
        w.open_path(path)
        wait(app, lambda: w.controller is not None and w.controller.state in ("done", "failed", "stopped"),
             "check of " + path)
        if w.controller.state != "done":
            print("STATE %s for %s" % (w.controller.state, path))
            sys.exit(4)
        w._accept_all()
        w.save_copy()
        print("copy saved: " + path)
    for name in ("saved.pdf", "saved.odt", "saved.txt"):
        w.save_as(os.path.join(out, name))
        if not os.path.exists(os.path.join(out, name)):
            print("MISSING " + name)
            sys.exit(5)
    w.copy_with_formatting()
    w.close()
    app.clipboard().clear()   # the offscreen clipboard must be emptied while Python is alive
    print("DRIVER OK")


if __name__ == "__main__":   # the spawned check re-imports this file
    main()
