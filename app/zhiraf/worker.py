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
