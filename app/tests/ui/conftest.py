import os

import pytest

# must be set before PySide2 is imported anywhere
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def empty_clipboard_at_exit():
    """The offscreen/minimal platforms keep the clipboard's QMimeData in a C++ global static that is destroyed by
    libc exit(), after the interpreter is gone; a mime object created from Python then calls into the dead
    interpreter and the run ends with a segfault. Emptying the clipboard while Python is alive avoids it."""
    yield
    from PySide2.QtWidgets import QApplication
    app = QApplication.instance()
    if app is not None:
        app.clipboard().clear()
