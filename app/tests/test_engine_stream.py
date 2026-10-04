from fakes import make_factories
from spellcheck.checker import STAGES, Checker, visible_level

SENTENCES = ["Так же был ограничен размер файлов.",
             "Документ определяющий порядок утверждён.",
             "Работа с информации ведётся.",
             "- Защита инфомационной системы обеспечена."]


def checker(models_dir, strict=False):
    return Checker(models_dir, factories=make_factories(), strict=strict)


def test_stages_run_in_order_one_result_per_sentence(models_dir):
    order = [(stage, i) for stage, i, _ in checker(models_dir).stream(SENTENCES)]
    assert order == [(s, i) for s in STAGES for i in range(len(SENTENCES))]


def test_findings_of_each_stage(models_dir):
    found = {}
    for stage, i, items in checker(models_dir).stream(SENTENCES):
        found.setdefault((stage, i), []).extend((f["rule"], f["level"], f["fix"]) for f in items)
    assert ("RULE_TAKZHE", "error", "Также") in found[("rules", 0)]
    assert ("MODEL_COMMA", "error", ",") in found[("commas", 1)]
    assert ("MODEL_FORM", "error", "информацией") in found[("forms", 2)]
    assert ("SAGE_TYPO", "error", "информационной") in found[("sage", 3)]


def test_positions_count_the_list_marker(models_dir):
    sage = [f for stage, i, items in checker(models_dir).stream(SENTENCES) if stage == "sage" for f in items]
    s = SENTENCES[3]
    assert [s[f["start"]:f["end"]] for f in sage] == ["инфомационной"]


def test_stop_ends_the_stream(models_dir):
    seen = []
    for stage, i, _ in checker(models_dir).stream(SENTENCES, should_stop=lambda: len(seen) >= 2):
        seen.append((stage, i))
    assert seen == [("rules", 0), ("rules", 1)]


def test_check_document_still_merges(models_dir):
    merged = checker(models_dir).check_document(SENTENCES)
    assert [f["rule"] for f in merged[0]] == ["RULE_TAKZHE"]


def test_strict_level_shows_only_in_strict_mode():
    assert visible_level("strict", False) is None
    assert visible_level("strict", True) == "check"
    assert visible_level("error", False) == "error" and visible_level("check", True) == "check"


def test_start_resumes_in_the_middle_of_a_stage(models_dir):
    seen = [(stage, i) for stage, i, _ in checker(models_dir).stream(SENTENCES, start=("forms", 2))]
    assert seen == [("forms", 2), ("forms", 3)] + [("spell", i) for i in range(len(SENTENCES))] \
        + [("sage", i) for i in range(len(SENTENCES))]


def test_skipped_stages_load_no_model(models_dir):
    loaded = []
    factories = make_factories()
    for name, make in list(factories.items()):
        factories[name] = (lambda n, m: lambda: (loaded.append(n), m())[1])(name, make)
    c = Checker(models_dir, factories=factories)
    list(c.stream(SENTENCES, start=("sage", 0)))
    assert loaded == ["sage"]


def test_rules_still_see_the_whole_context_when_resumed(models_dir):
    c = checker(models_dir)
    full = [f for stage, i, f in c.stream(SENTENCES, start=("rules", 0)) if stage == "rules"]
    resumed = [f for stage, i, f in c.stream(SENTENCES, start=("rules", 2)) if stage == "rules"]
    assert resumed == full[2:]


def test_empty_sentence_list_loads_nothing(models_dir):
    def boom():
        raise AssertionError("a model was loaded")
    c = Checker(models_dir, factories={"commas": boom, "forms": boom, "sage": boom})
    assert list(c.stream([])) == []


def test_stopped_flag(models_dir):
    c = checker(models_dir)
    list(c.stream(SENTENCES, should_stop=lambda: True))
    assert c.stopped is True
    list(c.stream(SENTENCES))
    assert c.stopped is False
