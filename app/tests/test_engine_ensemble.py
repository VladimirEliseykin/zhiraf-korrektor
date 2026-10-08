import gc
import os
import weakref

import pytest

from fakes import FakeTagger, make_ensemble_factories, make_factories
from spellcheck import checker as checker_module
from spellcheck.checker import Checker, combine_predictions, compact
from spellcheck.stages import model_folders
from zhiraf.worker import CheckJob

SENTENCES = ["Документ определяющий порядок утверждён.",
             "Работа с информации ведётся.",
             "Документ определяющий порядок отменён."]


@pytest.fixture(autouse=True)
def pure_agreement(monkeypatch):
    """The combiner tests below look at min / mean alone: no separate check score unless a test asks for it."""
    monkeypatch.setattr(checker_module, "CHECK_COMBINE", {})
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "min")  # the shipped commas combiner is "mean"


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
    # two models use the single-model thresholds (error from 0.9): the mean 0.725 is only a "check"
    assert commas(two_models(models_dir, p_a=0.95, p_b=0.5))[0] == [("MODEL_COMMA", "check")]
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "min")
    assert commas(two_models(models_dir, p_a=0.95, p_b=0.5))[0] == [("MODEL_COMMA", "check")]  # min 0.5


def test_combine_predictions_forms_need_the_same_label():
    def pred(label, p):
        return [{"comma": {"KEEP": 1.0, "ADD": 0.0, "DEL": 0.0}, "form": label, "form_p": p, "form_keep_p": 1 - p}]
    same = combine_predictions([compact(pred("case:ablt", 0.9)), compact(pred("case:ablt", 0.7))], "min")[0]
    assert same["form"] == "case:ablt" and same["form_p"] == pytest.approx(0.7)
    mean = combine_predictions([compact(pred("case:ablt", 0.9)), compact(pred("case:ablt", 0.7))], "mean")[0]
    assert mean["form_p"] == pytest.approx(0.8)
    other = combine_predictions([compact(pred("case:ablt", 0.9)), compact(pred("case:gent", 0.95))], "min")[0]
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
    blind = {}
    specs = [AGREE, AGREE, blind]  # the third model sees nothing: min 0, mean 0.63, first 0.95
    assert commas(models(models_dir, specs))[0] == []
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "mean")
    assert commas(models(models_dir, specs))[0] == [("MODEL_COMMA", "check")]
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "first")  # 0.95 ... but never an error
    assert commas(models(models_dir, specs))[0] == [("MODEL_COMMA", "check")]
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "max")
    assert commas(models(models_dir, [dict(AGREE, add_p=0.1), dict(AGREE, add_p=0.4), blind]))[0] == [("MODEL_COMMA", "check")]
    assert commas(models(models_dir, [AGREE] * 3))[0] == [("MODEL_COMMA", "error")]  # an agreed error stays an error


# ---------- review follow-up ----------

def models(models_dir, specs, log=None):
    """A Checker whose commas stage has one FakeTagger per spec (kwargs), named A, B, C ..."""
    factories = make_factories()
    factories["commas"] = [(lambda k, kw: lambda: FakeTagger(log=log, name=k, **kw))(chr(65 + n), spec)
                           for n, spec in enumerate(specs)]
    return Checker(models_dir, factories=factories)


AGREE = {"comma_after": {"Документ"}}


def test_a_single_model_keeps_the_single_thresholds(models_dir):
    c = models(models_dir, [dict(AGREE, add_p=0.75)])
    assert commas(c)[0] == [("MODEL_COMMA", "check")]  # 0.75 < 0.9
    c = models(models_dir, [dict(AGREE, add_p=0.95)])
    assert commas(c)[0] == [("MODEL_COMMA", "error")]
    c = models(models_dir, [dict(AGREE, add_p=0.25)])
    assert commas(c)[0] == []  # below the check band 0.3


def test_three_models_use_the_ensemble_thresholds(models_dir):
    assert commas(models(models_dir, [dict(AGREE, add_p=0.85)] * 3))[0] == [("MODEL_COMMA", "error")]  # mean >= 0.8
    assert commas(models(models_dir, [dict(AGREE, add_p=0.75)] * 3))[0] == [("MODEL_COMMA", "check")]  # mean < 0.8
    assert commas(models(models_dir, [dict(AGREE, add_p=0.25)] * 3))[0] == [("MODEL_COMMA", "check")]  # >= 0.2


def test_two_models_fall_back_to_the_single_thresholds(models_dir):
    # a missing or half-copied third model: nothing measured for two, so 0.9 / 0.3 like a single model
    assert commas(models(models_dir, [dict(AGREE, add_p=0.75)] * 2))[0] == [("MODEL_COMMA", "check")]
    assert commas(models(models_dir, [dict(AGREE, add_p=0.95)] * 2))[0] == [("MODEL_COMMA", "error")]
    assert commas(models(models_dir, [dict(AGREE, add_p=0.25)] * 2))[0] == []


COMMA_SENTENCES = ["Мы знаем, что это так.", "Он сказал, что придёт."]


def del_levels(c):
    return [[(f["rule"], f["level"]) for f in items] for stage, i, items in c.stream(COMMA_SENTENCES, stages=("commas",))]


def test_delete_needs_every_model_and_the_ensemble_delete_threshold(models_dir):
    sure = {"del_after": {"знаем", "сказал"}}
    assert del_levels(models(models_dir, [dict(sure, del_p=0.85)] * 3)) == [[("MODEL_COMMA_DEL", "error")]] * 2  # >= 0.8
    one_blind = [dict(sure, del_p=0.95), dict(sure, del_p=0.95), {}]
    assert del_levels(models(models_dir, one_blind)) == [[], []]  # the mean 0.63 is under 0.8
    assert del_levels(models(models_dir, [dict(sure, del_p=0.75)] * 3)) == [[], []]  # under 0.8
    assert del_levels(models(models_dir, [dict(sure, del_p=0.85)])) == [[], []]  # a single model needs 0.9


def test_delete_and_add_do_not_mix_up(models_dir):
    spec = {"del_after": {"знаем"}, "comma_after": {"Мы"}, "del_p": 0.95, "add_p": 0.95}
    found = del_levels(models(models_dir, [spec] * 3))[0]
    assert ("MODEL_COMMA_DEL", "error") in found  # the comma after "знаем" goes
    assert len(found) == 2 and ("MODEL_COMMA", "error") in found  # and one is added after "Мы"


def test_three_models_are_released_one_after_another(models_dir):
    events, refs = [], []

    def make(name):
        def factory():
            events.append(("alive", name, [r() is not None for r in refs]))
            model = FakeTagger(comma_after={"Документ"})
            refs.append(weakref.ref(model))
            return model
        return factory
    factories = make_factories()
    factories["commas"] = [make("A"), make("B"), make("C")]
    list(Checker(models_dir, factories=factories).stream(SENTENCES, stages=("commas",)))
    # when B loads A is gone; when C loads A and B are gone
    assert events == [("alive", "A", []), ("alive", "B", [False]), ("alive", "C", [False, False])]


def test_ensemble_resume_equals_the_full_run_from_k_on(models_dir):
    def run(**kw):
        c = models(models_dir, [dict(AGREE, add_p=0.8)] * 3)
        return [(i, items) for stage, i, items in c.stream(SENTENCES, stages=("commas",), **kw)]
    full = run()
    for k in range(len(SENTENCES)):
        assert run(start=("commas", k)) == full[k:]


def test_a_failing_predict_releases_the_model(models_dir):
    refs = []

    def first():
        model = FakeTagger(comma_after={"Документ"}, fail_after=2)
        refs.append(weakref.ref(model))
        return model
    factories = make_factories()
    factories["commas"] = [first, lambda: FakeTagger(), lambda: FakeTagger()]
    c = Checker(models_dir, factories=factories)
    with pytest.raises(RuntimeError):
        list(c.stream(SENTENCES, stages=("commas",)))
    gc.collect()
    assert refs[0]() is None


def test_stop_after_the_last_silent_step_loads_no_last_model(models_dir):
    loaded, steps = [], []
    factories = make_factories()
    factories["commas"] = [(lambda n: lambda: (loaded.append(n), FakeTagger())[1])(n) for n in "ABC"]
    c = Checker(models_dir, factories=factories)
    total = 2 * len(SENTENCES)  # two silent passes
    result = list(c.stream(SENTENCES, stages=("commas",), should_stop=lambda: len(steps) >= total,
                           on_step=steps.append))
    assert result == [] and c.stopped is True and loaded == ["A", "B"]


def test_unknown_combiners_are_refused(models_dir, monkeypatch):
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "median")
    with pytest.raises(ValueError):
        list(two_models(models_dir).stream(SENTENCES, stages=("commas",)))
    monkeypatch.setitem(checker_module.ENSEMBLE_COMBINE, "commas", "min")
    monkeypatch.setitem(checker_module.CHECK_COMBINE, "commas", "median")
    with pytest.raises(ValueError):
        list(two_models(models_dir).stream(SENTENCES, stages=("commas",)))


def test_earlier_predictions_are_stored_compactly(models_dir):
    from array import array
    c = models(models_dir, [AGREE] * 3)
    parts = c._earlier_passes("commas", c.factories["commas"], [(" ", s) for s in SENTENCES], 0, None, None)
    assert len(parts) == 2
    numbers, forms = parts[0][0]
    assert isinstance(numbers, array) and len(forms) == len(numbers) // 5  # five numbers and a label per word


def test_forms_ensemble_thresholds_are_pinned():
    # R5 + base-cased-forms, min: measured on dev by train/ensemble_eval.py (see the comment in checker.py)
    assert checker_module.ENSEMBLE_SIZE == {"commas": 3, "forms": 2}
    assert (checker_module.SURE_FORM_ENS, checker_module.CHECK_FORM_ENS) == (0.8, 0.8)
    assert checker_module.ENSEMBLE_COMBINE["forms"] == "min"


def test_form_check_score_never_makes_an_error_from_disagreeing_models():
    from spellcheck.checker import form_findings

    def pred(label, p):
        return [{"comma": {"KEEP": 1.0, "ADD": 0.0, "DEL": 0.0}, "form": label, "form_p": p, "form_keep_p": 1 - p}]
    parts = [compact(pred("case:ablt", 0.5)), compact(pred("case:gent", 0.95))]
    merged = combine_predictions(parts, "min", "max")
    assert merged[0]["form"] == "KEEP" and merged[0]["form_check"] == ("case:gent", 0.95)
    assert combine_predictions(parts, "min", "first")[0]["form_check"] == ("case:ablt", 0.5)
    assert combine_predictions(parts, "min", "mean")[0]["form_check"] == ("KEEP", 0.0)
    found = form_findings("Он занимается информации.", merged, sure=0.8, check=0.4)
    assert [f["level"] for f in found] == ["check"]  # 0.95 from one model is only a check


def test_commas_ensemble_thresholds_are_pinned(monkeypatch):
    monkeypatch.undo()  # the autouse fixture above replaces the shipped combiners
    # R3 + R6 + large-commas-e0, mean (train/ensemble_eval.py; see the comment in checker.py)
    assert checker_module.ENSEMBLE_SIZE["commas"] == 3
    assert checker_module.ENSEMBLE_COMBINE["commas"] == "mean"
    assert checker_module.CHECK_COMBINE["commas"] == "min"
    assert (checker_module.SURE_COMMA_ENS, checker_module.SURE_DEL_ENS, checker_module.CHECK_COMMA_ENS) == (0.8, 0.8, 0.2)
