import gc
import os
import weakref

import pytest

from fakes import FakeTagger, make_ensemble_factories, make_factories
from spellcheck import checker as checker_module
from spellcheck.checker import Checker, combine_predictions
from spellcheck.stages import model_folders
from zhiraf.worker import CheckJob

SENTENCES = ["Документ определяющий порядок утверждён.",
             "Работа с информации ведётся.",
             "Документ определяющий порядок отменён."]


@pytest.fixture(autouse=True)
def pure_agreement(monkeypatch):
    """The combiner tests below look at min / mean alone: no separate check score unless a test asks for it."""
    monkeypatch.setattr(checker_module, "CHECK_COMBINE", {})


def commas(c, stages=("commas",), **kwargs):
    return {i: [(f["rule"], f["level"]) for f in items] for stage, i, items in c.stream(SENTENCES, stages=stages, **kwargs)}


def two_models(models_dir, p_a=0.95, p_b=0.95, after_b=("Документ",), log=None):
    factories = make_factories()
    factories["commas"] = [lambda: FakeTagger(comma_after={"Документ"}, add_p=p_a, log=log, name="A"),
                           lambda: FakeTagger(comma_after=after_b, add_p=p_b, log=log, name="B")]
    return Checker(models_dir, factories=factories)


def test_two_models_that_agree_give_the_finding(models_dir):
    found = commas(two_models(models_dir))
    assert found[0] == [("MODEL_COMMA", "error")] and found[1] == []


def test_min_needs_both_models(models_dir):
    assert commas(two_models(models_dir, after_b=()))[0] == []  # the second model does not see the comma
    # below the "check" band of the second model: nothing, between the bands: only a "check"
    assert commas(two_models(models_dir, p_b=0.15))[0] == []
    level = commas(two_models(models_dir, p_a=0.95, p_b=0.5))[0]
    assert level == [("MODEL_COMMA", "check")]


def test_mean_combiner_is_softer_than_min(models_dir, monkeypatch):
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "mean")
    # one model sure, the other does not see it: min gives nothing, the average 0.475 stays a "check"
    assert commas(two_models(models_dir, after_b=()))[0] == [("MODEL_COMMA", "check")]
    assert commas(two_models(models_dir, p_a=0.95, p_b=0.3))[0] == [("MODEL_COMMA", "check")]  # mean 0.625
    assert commas(two_models(models_dir, p_a=0.95, p_b=0.5))[0] == [("MODEL_COMMA", "error")]  # mean 0.725
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "min")
    assert commas(two_models(models_dir, p_a=0.95, p_b=0.5))[0] == [("MODEL_COMMA", "check")]  # min 0.5


def test_combine_predictions_forms_need_the_same_label():
    def pred(label, p):
        return [{"comma": {"KEEP": 1.0, "ADD": 0.0, "DEL": 0.0}, "form": label, "form_p": p, "form_keep_p": 1 - p}]
    same = combine_predictions([pred("case:ablt", 0.9), pred("case:ablt", 0.7)], "min")[0]
    assert same["form"] == "case:ablt" and same["form_p"] == pytest.approx(0.7)
    mean = combine_predictions([pred("case:ablt", 0.9), pred("case:ablt", 0.7)], "mean")[0]
    assert mean["form_p"] == pytest.approx(0.8)
    other = combine_predictions([pred("case:ablt", 0.9), pred("case:gent", 0.95)], "min")[0]
    assert other["form"] == "KEEP" and other["form_p"] == 0.0


def test_the_first_model_is_released_before_the_second_loads(models_dir):
    events, refs = [], []

    def make(name):
        def factory():
            if refs:  # a second model is being loaded: the first one must be gone
                events.append(("alive", refs[0]() is not None))
            model = FakeTagger(comma_after={"Документ"}, log=events, name=name)
            events.append(("load", name))
            refs.append(weakref.ref(model))
            return model
        return factory
    factories = make_factories()
    factories["commas"] = [make("A"), make("B")]
    c = Checker(models_dir, factories=factories)
    list(c.stream(SENTENCES, stages=("commas",)))
    n = len(SENTENCES)
    assert events == [("load", "A")] + [("predict", "A")] * n + [("alive", False), ("load", "B")] + \
        [("predict", "B")] * n


def test_models_of_different_stages_do_not_overlap_either(models_dir):
    live, peak = [], []

    class Counted(FakeTagger):
        def __init__(self, *args, **kwargs):
            FakeTagger.__init__(self, *args, **kwargs)
            live.append(weakref.ref(self))
            gc.collect()
            peak.append(sum(1 for r in live if r() is not None))
    factories = make_factories()
    factories["commas"] = [lambda: Counted(comma_after={"Документ"}), lambda: Counted(comma_after={"Документ"})]
    factories["forms"] = lambda: Counted()
    list(Checker(models_dir, factories=factories).stream(SENTENCES, stages=("commas", "forms")))
    assert peak == [1, 1, 1]


def test_steps_are_reported_for_the_silent_pass(models_dir):
    steps = []
    c = two_models(models_dir)
    stream = list(c.stream(SENTENCES, stages=("rules", "commas"), on_step=steps.append))
    assert steps == ["commas"] * len(SENTENCES)
    assert [(s, i) for s, i, _ in stream] == [(s, i) for s in ("rules", "commas") for i in range(len(SENTENCES))]


def test_passes_of_a_stage(models_dir):
    c = Checker(models_dir, factories=make_ensemble_factories())
    assert (c.passes("rules"), c.passes("commas"), c.passes("forms"), c.passes("sage")) == (1, 2, 1, 1)


def test_stop_during_the_silent_pass_loads_no_second_model(models_dir):
    loaded = []
    factories = make_factories()
    factories["commas"] = [lambda: (loaded.append("A"), FakeTagger())[1], lambda: (loaded.append("B"), FakeTagger())[1]]
    c = Checker(models_dir, factories=factories)
    seen = []
    result = list(c.stream(SENTENCES, stages=("commas",), should_stop=lambda: len(seen) >= 1,
                           on_step=lambda stage: seen.append(stage)))
    assert result == [] and c.stopped is True and loaded == ["A"]


def test_resume_predicts_only_the_remaining_sentences(models_dir):
    log = []
    c = two_models(models_dir, log=log)
    found = [(s, i) for s, i, _ in c.stream(SENTENCES, stages=("commas",), start=("commas", 2))]
    assert found == [("commas", 2)]
    assert log == [("predict", "A"), ("predict", "B")]


def test_check_document_uses_the_ensemble(models_dir):
    merged = two_models(models_dir).check_document(SENTENCES, stages=("rules", "commas"))
    assert [f["rule"] for f in merged[0]] == ["MODEL_COMMA"]


def make_model_folder(root, name, complete=True):
    folder = os.path.join(root, name)
    os.makedirs(folder)
    open(os.path.join(folder, "labels.json"), "w").close()
    if complete:
        open(os.path.join(folder, "model.onnx"), "w").close()


def test_missing_optional_models_mean_a_single_model_stage(models_dir):
    make_model_folder(models_dir, "commas")
    make_model_folder(models_dir, "forms")
    assert model_folders(models_dir, "commas") == [os.path.join(models_dir, "commas")]
    assert Checker(models_dir).passes("commas") == 1
    # a missing main folder still comes first: the stage then fails loudly when it loads
    assert model_folders(models_dir, "sage") == [os.path.join(models_dir, "sage")]


def test_extra_model_folders_are_found_in_order(models_dir):
    for name in ("commas", "commas-2", "commas-3", "forms"):
        make_model_folder(models_dir, name)
    assert [os.path.basename(f) for f in model_folders(models_dir, "commas")] == ["commas", "commas-2", "commas-3"]
    c = Checker(models_dir)
    assert (c.passes("commas"), c.passes("forms")) == (3, 1)


def test_a_half_copied_or_gapped_extra_model_is_ignored(models_dir):
    make_model_folder(models_dir, "commas")
    make_model_folder(models_dir, "commas-2", complete=False)  # no model file yet
    make_model_folder(models_dir, "commas-3")  # after a gap: not used
    assert len(model_folders(models_dir, "commas")) == 1


def test_job_progress_counts_both_passes(models_dir):
    job = CheckJob(models_dir, SENTENCES, factories="fakes:make_ensemble_factories")
    job.start()
    messages = []
    import time
    deadline = time.time() + 60
    while not job.finished and time.time() < deadline:
        messages += job.poll(timeout=0.2)
    job.close()
    assert job.finished and job.error is None
    kinds = [m[0] for m in messages]
    assert kinds.count("step") == len(SENTENCES)  # the silent pass of the first commas model
    assert job.progress.passes["commas"] == 2
    assert job.progress.done["commas"] == 2 * len(SENTENCES)
    assert job.progress.fraction() == 1.0
    assert [m[2] for m in messages if m[0] == "findings" and m[1] == "commas"] == list(range(len(SENTENCES)))



def test_hybrid_check_level_uses_the_softer_score(models_dir, monkeypatch):
    # the second model sees nothing: min is 0 (no finding), the mean 0.475 reaches the check band
    assert commas(two_models(models_dir, after_b=()))[0] == []
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "mean")
    assert commas(two_models(models_dir, after_b=()))[0] == [("MODEL_COMMA", "check")]
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "first")  # the main model alone: 0.95 ...
    assert commas(two_models(models_dir, after_b=()))[0] == [("MODEL_COMMA", "check")]  # ... but never an error
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "max")
    assert commas(two_models(models_dir, p_a=0.1, p_b=0.4, after_b=("Документ",)))[0] == [("MODEL_COMMA", "check")]
    # an agreed error stays an error whatever the check score is
    assert commas(two_models(models_dir))[0] == [("MODEL_COMMA", "error")]
