"""Runs a check in a child process and feeds its findings into the review session."""
from PySide2.QtCore import QObject, QTimer, Signal

from ..segment import plan_sentences, sentence_kinds
from ..worker import CheckJob

TICK_MS = 50


class _Pass:
    """One job's input: what was sent to the child and where each sentence belongs."""

    def __init__(self, sentences, where, context, structure, context_structure, versions):
        self.sentences, self.where = sentences, where
        self.context, self.structure, self.context_structure = context, structure, context_structure
        self.versions = versions  # paragraph -> session version at the start: later edits make findings stale
        self.last = {}            # stage -> index of the last findings message received
        self.recheck = context is not None


class CheckController(QObject):
    marks_changed = Signal(object)
    progressed = Signal()
    state_changed = Signal(str)
    checked_until = Signal(int)

    def __init__(self, session, get_paragraphs, models_dir, settings, factories=None, parent=None, log_detail=None):
        super().__init__(parent)
        self.session = session
        self.get_paragraphs = get_paragraphs
        self.models_dir = models_dir
        self.settings = settings
        self.factories = factories
        self.log_detail = log_detail  # optional callable(str): the safe error detail for the log
        self.state = "idle"
        self.progress = None
        self.error = None
        self.job = None
        self.jobs_started = 0
        self._pass = None
        self._queue = []
        self._closed = False
        self._job_closed = True
        self._until = -1
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # --- public API ---

    @property
    def has_text(self):
        return bool(plan_sentences([p.text for p in self.get_paragraphs()])[0])

    def start(self):
        if self._closed:
            return False
        paragraphs = self.get_paragraphs()
        sentences, where = plan_sentences([p.text for p in paragraphs])
        if not sentences:
            self._set_state("done")
            return False
        self._until = -1
        versions = {i: self.session.version(i) for i in range(len(paragraphs))}
        self._launch(_Pass(sentences, where, None, sentence_kinds(paragraphs, where), None, versions), None)
        return True

    def stop(self):
        if self.state == "running" and self.job is not None:
            self.job.stop()

    def resume(self):
        if self._closed or self.state not in ("stopped", "failed") or self._pass is None:
            return
        resume_from = self._resume_point()
        if resume_from is None:
            self._after_pass()
        else:
            self._launch(self._pass, resume_from)

    def recheck(self, dirty):
        self._queue = sorted(set(self._queue) | set(dirty))
        if self.state == "done" and not self._closed:
            self._after_pass()

    def close(self):
        self._closed = True
        self._timer.stop()  # before job.close(): a later poll() on the closed reader would look like a crash
        self._close_job()

    # --- internals ---

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _resume_point(self):
        stages = self.job.stages
        n = len(self._pass.sentences)
        for stage in stages:
            done = self._pass.last.get(stage, -1)
            if done < n - 1:
                return stage, done + 1
        return None

    def _launch(self, pas, resume_from):
        self._close_job()
        self._pass = pas
        self.error = None
        self.job = CheckJob(self.models_dir, pas.sentences, pas.context, strict=bool(self.settings["strict_mode"]),
                            factories=self.factories, resume_from=resume_from, structure=pas.structure,
                            context_structure=pas.context_structure)
        self._job_closed = False
        self.jobs_started += 1
        self.progress = self.job.progress
        self.job.start()
        self._set_state("running")
        self._timer.start()
        self.progressed.emit()

    def _close_job(self):
        if self.job is not None and not self._job_closed:
            self._job_closed = True
            self.job.close()

    def _tick(self):
        if self._closed or self.job is None or self._job_closed:
            return
        messages = self.job.poll(0)
        changed = set()
        last_stage = self.job.stages[-1]
        reached = None
        for message in messages:
            if message[0] != "findings":
                continue
            _, stage, idx, items = message
            self._pass.last[stage] = idx
            paragraph, offset = self._pass.where[idx]
            if not self.settings["show_checks"]:
                items = [f for f in items if f.get("level") != "check"]
            if items:
                for mark in self.session.add_findings(paragraph, offset, items, self._pass.versions.get(paragraph)):
                    changed.add(mark.paragraph)
            if stage == last_stage and not self._pass.recheck:
                reached = paragraph if reached is None else max(reached, paragraph)
        for mark in self.session.pop_removed():
            changed.add(mark.paragraph)
        if changed:
            self.marks_changed.emit(changed)
        if reached is not None and reached > self._until:
            self._until = reached
            self.checked_until.emit(reached)
        if messages:
            self.progressed.emit()
        if self.job.finished:
            self._timer.stop()
            self._finished()

    def _finished(self):
        job = self.job
        self._close_job()
        if job.error is not None:
            self.error = job.error
            if self.log_detail is not None:
                self.log_detail(job.error[2])
            self._set_state("failed")
        elif job.stopped:
            self._set_state("stopped")
        else:
            self._after_pass()

    def _after_pass(self):
        """The main pass (or a recheck) is over: run the queued paragraphs, or finish."""
        paragraphs = self.get_paragraphs()
        dirty, self._queue = [i for i in self._queue if i < len(paragraphs)], []
        if dirty:
            texts = [p.text for p in paragraphs]
            sentences, where = plan_sentences(texts)
            kinds = sentence_kinds(paragraphs, where)
            picked = [k for k, (paragraph, _) in enumerate(where) if paragraph in dirty]
            if picked:
                versions = {i: self.session.version(i) for i in range(len(paragraphs))}
                pas = _Pass([sentences[k] for k in picked], [where[k] for k in picked], sentences,
                            [kinds[k] for k in picked], kinds, versions)
                self._launch(pas, None)
                return
        self._set_state("done")
