import os
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
    assert job.progress.fraction() == 1.0 and job.stopped is False
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
    assert job.stopped is True and job.error is None


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


def test_close_on_never_started_job_does_not_raise(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_factories")
    job.close()


def test_crash_text_has_class_but_not_message(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_broken_factories")
    run(job)
    kind, user, log = job.error
    assert kind == "crash" and user == "Проверка прервалась из-за внутренней ошибки."
    assert "RuntimeError" not in user and "fakes.py" not in user
    assert "RuntimeError" in log and "fakes.py" in log
    assert "model files are missing" not in log and "model files are missing" not in user


def test_close_on_running_job_is_fast(models_dir):
    job = CheckJob(models_dir, SENTENCES * 20, factories="fakes:make_slow_factories")
    job.start()
    job.poll(timeout=1.0)
    began = time.monotonic()
    job.close()
    assert time.monotonic() - began < 2.0


def test_allocation_failure_is_reported_as_memory_without_its_text(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_oom_factories")
    run(job)
    kind, user, log = job.error
    assert kind == "memory" and user == "Не хватило памяти для проверки."
    assert "bad allocation" not in user and "bad allocation" not in log and "RuntimeError" in log


def test_silent_death_has_a_log_detail(models_dir):
    job = CheckJob(models_dir, SENTENCES * 20, factories="fakes:make_slow_factories")
    job.start()
    job.poll(timeout=1.0)
    job._process.kill()
    deadline = time.time() + 20
    while not job.finished and time.time() < deadline:
        job.poll(timeout=0.2)
    job.close()
    assert len(job.error) == 3 and job.error[2]


def test_safe_error_detail_names_class_and_frames_only():
    from zhiraf.worker import safe_error_detail
    try:
        raise ValueError("secret document text")
    except ValueError as e:
        detail = safe_error_detail(e)
    assert detail.startswith("ValueError: ") and "test_worker.py" in detail and "secret" not in detail


def test_resumed_job_skips_earlier_work(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_factories", resume_from=("commas", 1))
    messages = run(job)
    findings = [(m[1], m[2]) for m in messages if m[0] == "findings"]
    assert findings == [("commas", 1), ("commas", 2), ("forms", 0), ("forms", 1), ("forms", 2),
                        ("sage", 0), ("sage", 1), ("sage", 2)]
    assert job.progress.fraction() == 1.0 and job.error is None


def test_resumed_job_starts_with_the_skipped_work_counted():
    job = CheckJob("unused", SENTENCES, resume_from=("forms", 2))
    assert 0 < job.progress.fraction() < 1.0
    job.close()


def test_poll_hands_out_at_most_500_messages(models_dir):
    job = CheckJob(models_dir, ["Так же был."] * 400, factories="fakes:make_factories")
    job.start()
    time.sleep(0)
    biggest, deadline = 0, time.time() + 60
    while not job.finished and time.time() < deadline:
        biggest = max(biggest, len(job.poll(timeout=0.2)))
    job.close()
    assert job.finished and biggest <= 500


def test_importing_the_worker_does_not_load_the_engine_stack():
    import subprocess
    import sys
    code = "import sys, zhiraf.worker; sys.exit(1 if 'onnxruntime' in sys.modules else 0)"
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert subprocess.call([sys.executable, "-c", code], cwd=here) == 0
