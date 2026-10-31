"""Program start: one running copy, the crash log, the window.

The log holds a time, the exception class and file:line:function, never document text.
"""
import os
import sys
import time

from PySide2.QtCore import QLockFile
from PySide2.QtWidgets import QApplication, QMessageBox

from .. import missing_models, models_dir, storage
from ..worker import safe_error_detail
from . import theme
from .main_window import MainWindow

TITLE = "Жираф.Корректор"
ALREADY_RUNNING = "Жираф.Корректор уже открыт"
SOMETHING_WRONG = "Что-то пошло не так. Подробности записаны в журнал."
LOG_NAME = "журнал.txt"
LOCK_NAME = "запущено.lock"
LOG_LIMIT = 200 * 1024
LOG_KEEP = 100 * 1024


def _tell(kind, text):
    """Show a message; ZHIRAF_TEST_NO_DIALOG=1 (guard tests) writes it to stderr instead."""
    if os.environ.get("ZHIRAF_TEST_NO_DIALOG") == "1":
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    elif kind == "critical":
        QMessageBox.critical(None, TITLE, text)
    else:
        QMessageBox.information(None, TITLE, text)


def acquire_single_instance():
    """The lock of this running copy, or None when another live copy holds it (a dead one's lock is taken over)."""
    lock = QLockFile(os.path.join(storage.data_dir(), LOCK_NAME))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(0) else None


def log_path():
    return os.path.join(storage.data_dir(), LOG_NAME)


def log_error_detail(detail):
    """Append 'time · detail' to the log; the detail is already safe (class and file:line:function)."""
    try:
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > LOG_LIMIT:
            with open(path, "rb") as f:
                f.seek(-LOG_KEEP, os.SEEK_END)
                tail = f.read()
            tail = tail.split(b"\n", 1)[-1]  # drop the line cut in the middle
            with open(path, "wb") as f:
                f.write(tail)
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s · %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), detail))
    except (OSError, ValueError):
        pass  # logging must never raise, least of all from the exception hook


def log_error(exc):
    log_error_detail(safe_error_detail(exc))


def _install_excepthook():
    state = {"busy": False, "shown": False}   # one box per session: a slot that keeps raising must not stack boxes

    def hook(exc_type, exc, tb):
        try:
            if exc is not None:
                log_error(exc)
            if state["busy"] or state["shown"]:
                return
            state["busy"] = state["shown"] = True
            try:
                _tell("critical", SOMETHING_WRONG)
            finally:
                state["busy"] = False
        except Exception:
            pass
    sys.excepthook = hook


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(TITLE)
    app.setStyleSheet(theme.stylesheet())
    lock = acquire_single_instance()
    if lock is None:
        _tell("information", ALREADY_RUNNING)
        return 0
    try:
        storage.clean_tmp()
        folder = models_dir()
        problem = missing_models(folder)
        if problem is not None:
            _tell("critical", problem)
            return 2
        _install_excepthook()
        window = MainWindow(folder, log_detail=log_error_detail)
        window.show()
        paths = [a for a in argv[1:] if not a.startswith("-")]
        if paths:
            window.open_path(paths[0])
        code = app.exec_()
        if window.hard_exit:
            lock.unlock()
            os._exit(code)
        return code
    finally:
        lock.unlock()
