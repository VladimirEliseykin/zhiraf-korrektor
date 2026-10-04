import time

from zhiraf.worker import CheckJob

SENTENCES = ["Так же был ограничен размер.", "Документ определяющий порядок утверждён.", "Работа с информации ведётся."]


def run(job, limit=60):
    job.start()
    messages, deadline = [], time.time() + limit
    while not job.finished and time.time() < deadline:
        messages += job.poll(timeout=0.2)
    job.close()
    assert job.finished, "the check did not finish in time"
    return messages


def test_all_stages_report_every_sentence(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_factories")
    messages = run(job)
    findings = [m for m in messages if m[0] == "findings"]
    assert len(findings) == 4 * len(SENTENCES)
    assert messages[-1][0] == "done" and job.error is None
    assert job.progress.fraction() == 1.0
    rules = [f["rule"] for m in findings if m[1] == "forms" for f in m[3]]
    assert rules == ["MODEL_FORM"]


def test_stop_finishes_early(models_dir):
    job = CheckJob(models_dir, SENTENCES * 5, factories="fakes:make_slow_factories")
    job.start()
    seen = []
    deadline = time.time() + 60
    while not job.finished and time.time() < deadline:
        for m in job.poll(timeout=0.1):
            seen.append(m)
            if m[0] == "findings" and m[1] == "commas":
                job.stop()
    job.close()
    commas = [m for m in seen if m[0] == "findings" and m[1] == "commas"]
    assert job.finished and 1 <= len(commas) < 15


def test_model_failure_is_reported(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_broken_factories")
    messages = run(job)
    assert job.error[0] == "crash" and messages[-1][0] == "error"


def test_silent_death_is_noticed(models_dir):
    job = CheckJob(models_dir, SENTENCES * 20, factories="fakes:make_slow_factories")
    job.start()
    job.poll(timeout=1.0)
    job._process.kill()  # as the OS does when memory runs out
    deadline = time.time() + 20
    while not job.finished and time.time() < deadline:
        job.poll(timeout=0.2)
    job.close()
    assert job.finished and job.error[0] == "crash"
