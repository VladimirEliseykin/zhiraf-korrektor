import time

from zhiraf.documents.model import Paragraph, Span
from zhiraf.review import ReviewSession
from zhiraf.storage import Settings
from zhiraf.ui.controller import CheckController

from test_worker import SENTENCES


class Doc:
    def __init__(self, texts):
        self.paragraphs = [Paragraph([Span(t)]) for t in texts]

    def get(self):
        return self.paragraphs


def make(models_dir, texts, factories="fakes:make_factories", **kw):
    doc = Doc(texts)
    session = ReviewSession(list(texts))
    controller = CheckController(session, doc.get, models_dir, Settings(), factories=factories, **kw)
    return doc, session, controller


def finish(qtbot, controller):
    qtbot.waitUntil(lambda: controller.state in ("done", "stopped", "failed"), timeout=60000)


def keys(session):
    return [(m.paragraph, m.start, m.end, m.rule) for m in session.marks]


def test_check_finds_marks_and_reports_done(qtbot, models_dir):
    doc, session, c = make(models_dir, SENTENCES)
    changed, until = [], []
    c.marks_changed.connect(changed.append)
    c.checked_until.connect(until.append)
    assert c.start() is True
    finish(qtbot, c)
    c.close()
    assert c.state == "done" and c.progress.fraction() == 1.0 and c.error is None
    assert any(m.rule.startswith("RULE_") or m.rule == "MODEL_FORM" for m in session.marks)
    assert changed and until[-1] == 2


def test_empty_document_does_not_start(qtbot, models_dir):
    doc, session, c = make(models_dir, ["", "   "])
    assert c.start() is False
    assert c.state == "done" and c.has_text is False and c.job is None and c.jobs_started == 0


def _slow_run(qtbot, models_dir, edit):
    texts = ["Документ определяющий порядок утверждён.", "Работа с информации ведётся."]
    doc, session, c = make(models_dir, texts, factories="fakes:make_slow_factories")
    c.start()
    qtbot.waitUntil(lambda: bool(c.progress) and c.progress.fraction() > 0, timeout=60000)
    if edit:
        doc.paragraphs[1] = Paragraph([Span("Новый текст")])
        session.replace_paragraph(1, "Новый текст")
    finish(qtbot, c)
    c.close()
    return [m for m in session.marks if m.paragraph == 1 and m.rule == "MODEL_FORM"]


def test_findings_for_edited_paragraph_are_dropped(qtbot, models_dir):
    control = _slow_run(qtbot, models_dir, edit=False)
    assert control, "without the edit the old text has model findings"
    assert _slow_run(qtbot, models_dir, edit=True) == []


def test_recheck_runs_after_main_pass_for_dirty_paragraphs(qtbot, models_dir):
    texts = ["Работа с информации ведётся.", "Всё хорошо."]
    doc, session, c = make(models_dir, texts)
    c.start()
    doc.paragraphs[1] = Paragraph([Span("Документ определяющий порядок.")])
    session.replace_paragraph(1, "Документ определяющий порядок.")
    c.recheck([1])
    finish(qtbot, c)
    c.close()
    assert c.state == "done" and c.jobs_started == 2
    assert any(m.paragraph == 1 for m in session.marks)


def test_stop_keeps_marks_and_resume_has_no_duplicates(qtbot, models_dir):
    doc, session, c = make(models_dir, SENTENCES * 4, factories="fakes:make_slow_factories")
    c.start()
    qtbot.waitUntil(lambda: bool(session.marks), timeout=60000)
    c.stop()
    finish(qtbot, c)
    assert c.state == "stopped" and session.marks
    kept = len(session.marks)
    c.factories = "fakes:make_factories"
    c.resume()
    finish(qtbot, c)
    c.close()
    assert c.state == "done" and len(session.marks) >= kept
    assert len(keys(session)) == len(set(keys(session)))


def test_crash_gives_failed_with_message_and_resume(qtbot, models_dir):
    logged = []
    doc, session, c = make(models_dir, SENTENCES, factories="fakes:make_crashing_factories", log_detail=logged.append)
    c.start()
    finish(qtbot, c)
    assert c.state == "failed" and c.error[0] == "crash" and "прервалась" in c.error[1]
    assert logged == [c.error[2]]
    assert any(m.fix is not None and m.fix.strip() == "," for m in session.marks)   # the commas stage got through
    before = keys(session)
    c.factories = "fakes:make_factories"
    c.resume()
    finish(qtbot, c)
    c.close()
    assert c.state == "done" and c.error is None
    assert set(before) <= set(keys(session)) and len(keys(session)) == len(set(keys(session)))
    assert c.jobs_started == 2


def test_close_stops_child_and_ignores_late_messages(qtbot, models_dir):
    doc, session, c = make(models_dir, SENTENCES * 4, factories="fakes:make_slow_factories")
    c.start()
    qtbot.waitUntil(lambda: bool(session.marks), timeout=60000)
    c.close()
    n = len(session.marks)
    qtbot.wait(300)
    assert c.state == "running" and c.job._process.is_alive() is False
    assert c.error is None and len(session.marks) == n
    c._tick()   # a tick after close() changes nothing
    assert c.state == "running" and c.error is None and len(session.marks) == n


def test_show_checks_off_hides_check_level(qtbot, models_dir):
    settings = Settings()
    settings.set("show_checks", False)
    doc = Doc(SENTENCES)
    session = ReviewSession(list(SENTENCES))
    c = CheckController(session, doc.get, models_dir, settings, factories="fakes:make_factories")
    c.start()
    finish(qtbot, c)
    c.close()
    assert session.marks and all(m.level != "check" for m in session.marks)


def test_polling_handles_flood(qtbot, models_dir):
    texts = ["Документ определяющий порядок."] * 3000
    doc, session, c = make(models_dir, texts)
    slowest = [0.0]
    original = c._tick

    def timed():
        began = time.perf_counter()
        original()
        slowest[0] = max(slowest[0], time.perf_counter() - began)

    c._timer.timeout.disconnect()
    c._timer.timeout.connect(timed)
    c.start()
    while c.state == "running":
        qtbot.wait(50)
    c.close()
    assert c.state == "done" and slowest[0] < 1.0
