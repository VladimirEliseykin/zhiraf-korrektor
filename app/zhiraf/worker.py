"""The check runs in its own process: the window stays responsive and model memory is really freed."""
import importlib
import multiprocessing
import os
import traceback

from .eta import Progress

SILENT_DEATH = ("crash", "Проверка неожиданно прервалась (возможно, не хватило памяти).")


def _resolve(spec):
    module, function = spec.split(":")
    return getattr(importlib.import_module(module), function)


def _safe_error(exc):
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    where = "; ".join("%s:%s:%s" % (os.path.basename(f.filename), f.lineno, f.name) for f in frames)
    return "Проверка прервалась из-за внутренней ошибки (%s): %s" % (type(exc).__name__, where)


def _run(models_dir, sentences, context, stages, strict, threads, factories_spec, out, stop):
    try:
        import zhiraf  # noqa: F401  (puts the engine on sys.path in this process)
        from spellcheck.checker import Checker
        factories = _resolve(factories_spec)() if factories_spec else None
        checker = Checker(models_dir, threads, strict=strict, factories=factories)
        for stage, index, items in checker.stream(sentences, context, stages, should_stop=stop.is_set):
            out.send(("findings", stage, index, items))
        out.send(("done", checker.stats))
    except MemoryError:
        out.send(("error", "memory", "Не хватило памяти для проверки."))
    except Exception as exc:
        # never str(exc) or source lines: they could carry document text
        out.send(("error", "crash", _safe_error(exc)))


class CheckJob:
    def __init__(self, models_dir, sentences, context=None, stages=None, strict=False, threads=2, factories=None):
        import zhiraf  # noqa: F401
        from spellcheck.checker import STAGE_COST, STAGES
        self.stages = tuple(stages or STAGES)
        ctx = multiprocessing.get_context("spawn")
        self._reader, self._writer = ctx.Pipe(duplex=False)
        self._stop = ctx.Event()
        args = (models_dir, list(sentences), None if context is None else list(context), self.stages, strict,
                threads, factories, self._writer, self._stop)
        self._process = ctx.Process(target=_run, args=args, daemon=True)
        self.progress = Progress(len(sentences), self.stages, STAGE_COST)
        self.finished = False
        self.error = None
        self.stats = None

    def start(self):
        self.progress.start()
        self._process.start()
        self._writer.close()  # only the child holds the write end, so its death gives EOF

    def _note(self, message):
        if message[0] == "findings":
            self.progress.sentence_done(message[1])
        elif message[0] == "done":
            self.finished, self.stats = True, message[1]
        elif message[0] == "error":
            self.finished, self.error = True, (message[1], message[2])

    def poll(self, timeout=0.0):
        messages = []
        if self.finished:
            return messages
        wait = timeout
        try:
            while self._reader.poll(wait):
                message = self._reader.recv()
                self._note(message)
                messages.append(message)
                wait = 0
                if self.finished:
                    return messages
        except (EOFError, OSError):
            # the child died, possibly mid-message; what it sent before is already delivered
            self.finished, self.error = True, SILENT_DEATH
            messages.append(("error",) + SILENT_DEATH)
        return messages

    def stop(self):
        self._stop.set()

    def close(self):
        if self._process.pid is not None:
            self._stop.set()
            self._process.join(timeout=0.5)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=0.5)
        else:
            self._writer.close()
        self._reader.close()
