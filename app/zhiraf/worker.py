"""The check runs in its own process: the window stays responsive and model memory is really freed."""
import importlib
import multiprocessing
import os
import traceback

from spellcheck.stages import STAGE_COST, STAGES

from .eta import Progress

SILENT_DEATH = ("crash", "Проверка неожиданно прервалась (возможно, не хватило памяти).",
                "процесс проверки завершился без ответа")
CRASH_MESSAGE = "Проверка прервалась из-за внутренней ошибки."
MEMORY_MESSAGE = "Не хватило памяти для проверки."
POLL_LIMIT = 500  # messages handed out per poll: the window stays responsive under a flood


def _resolve(spec):
    module, function = spec.split(":")
    return getattr(importlib.import_module(module), function)


def safe_error_detail(exc):
    """Class name and the last frames (file:line:function) for the log. Never str(exc) or source lines:
    they could carry document text."""
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    where = "; ".join("%s:%s:%s" % (os.path.basename(f.filename), f.lineno, f.name) for f in frames)
    return "%s: %s" % (type(exc).__name__, where)


def _is_memory_error(exc):
    if isinstance(exc, MemoryError):
        return True
    runtime = isinstance(exc, RuntimeError) or type(exc).__module__.startswith("onnxruntime")
    if not runtime:
        return False
    # the message is only classified here, it is never forwarded
    text = ("%s %s" % (type(exc).__name__, exc)).lower()
    return "alloc" in text or "out of memory" in text


def _run(models_dir, sentences, context, stages, strict, threads, factories_spec, out, stop, start=None):
    try:
        import zhiraf  # noqa: F401  (puts the engine on sys.path in this process)
        from spellcheck.checker import Checker
        factories = _resolve(factories_spec)() if factories_spec else None
        checker = Checker(models_dir, threads, strict=strict, factories=factories)
        out.send(("plan", {stage: checker.passes(stage) for stage in stages}))  # model passes per stage (progress)
        for stage, index, items in checker.stream(sentences, context, stages, should_stop=stop.is_set, start=start,
                                                  on_step=lambda stage: out.send(("step", stage))):
            out.send(("findings", stage, index, items))
        out.send(("done", checker.stats, checker.stopped))
    except Exception as exc:
        if _is_memory_error(exc):
            out.send(("error", "memory", MEMORY_MESSAGE, safe_error_detail(exc)))
        else:
            out.send(("error", "crash", CRASH_MESSAGE, safe_error_detail(exc)))


class CheckJob:
    def __init__(self, models_dir, sentences, context=None, stages=None, strict=False, threads=2, factories=None,
                 resume_from=None):
        self.stages = tuple(stages or STAGES)
        ctx = multiprocessing.get_context("spawn")
        self._reader, self._writer = ctx.Pipe(duplex=False)
        self._stop = ctx.Event()
        args = (models_dir, list(sentences), None if context is None else list(context), self.stages, strict,
                threads, factories, self._writer, self._stop, resume_from)
        self._process = ctx.Process(target=_run, args=args, daemon=True)
        self.progress = Progress(len(sentences), self.stages, STAGE_COST)
        if resume_from is not None:
            stage, index = resume_from
            if stage not in self.stages:
                raise ValueError("unknown stage: %s" % stage)
            for earlier in self.stages[:self.stages.index(stage)]:
                self.progress.skip(earlier, len(sentences))
            self.progress.skip(stage, index)
        self.finished = False
        self.error = None
        self.stats = None
        self.stopped = False

    def start(self):
        self.progress.start()
        self._process.start()
        self._writer.close()  # only the child holds the write end, so its death gives EOF

    def _note(self, message):
        if message[0] == "findings" or message[0] == "step":
            self.progress.sentence_done(message[1])
        elif message[0] == "plan":
            self.progress.set_passes(message[1])
        elif message[0] == "done":
            self.finished, self.stats, self.stopped = True, message[1], bool(message[2])
        elif message[0] == "error":
            self.finished, self.error = True, (message[1], message[2], message[3])

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
                if self.finished or len(messages) >= POLL_LIMIT:
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
