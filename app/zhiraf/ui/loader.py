"""Opening a document in a background thread, so the window never freezes on a big file."""
import os

from PySide2.QtCore import QObject, QThread, Signal, Slot

from ..documents.model import DocumentError
from ..documents.opener import close_document, open_document


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, path):
        QObject.__init__(self)
        self._path = path

    @Slot()
    def run(self):
        try:
            doc = open_document(self._path)
        except DocumentError as e:
            self.failed.emit(str(e))
        except BaseException:  # never carry the exception text or a traceback to the window
            self.failed.emit("Не удалось открыть «%s»: файл повреждён." % os.path.basename(self._path))
        else:
            self.done.emit(doc)


class OpenTask(QObject):
    """One open at a time: opened(Document) or failed(message); cancel() drops the result."""
    opened = Signal(object)
    failed = Signal(str)

    def __init__(self, path, parent=None):
        QObject.__init__(self, parent)
        self._path = path
        self._cancelled = False
        self._thread = None
        self._worker = None

    def start(self):
        if self._thread is not None:
            return
        self._thread = QThread()
        self._worker = _Worker(self._path)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        # if the task is deleted without close() (its window is gone), never destroy a running thread
        thread, worker = self._thread, self._worker
        self.destroyed.connect(lambda *_: (thread.quit(), thread.wait(), worker))
        self._thread.start()

    def is_running(self):
        return self._thread is not None and self._thread.isRunning()

    def cancel(self):
        """Drop the result; returns at once. The thread is waited for in close()."""
        self._cancelled = True

    def wait(self, msec):
        """Wait for the thread at most msec; True when it is finished (or never started)."""
        if self._thread is None:
            return True
        self._thread.quit()   # the worker's own quit() is queued to this thread's event loop, which is not running
        return self._thread.wait(msec)

    def close(self):
        self._stop_thread()

    def _stop_thread(self):
        if self._thread is None:
            return
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self._worker = None

    @Slot(object)
    def _on_done(self, doc):
        if self._cancelled:
            close_document(doc)   # a converted copy of a secret .doc must not stay on disk
        else:
            self.opened.emit(doc)

    @Slot(str)
    def _on_failed(self, message):
        if not self._cancelled:
            self.failed.emit(message)
