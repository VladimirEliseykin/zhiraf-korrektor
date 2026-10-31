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


def test_sage_promotes_a_check_ending_of_an_earlier_stage(models_dir):
    from fakes import FakeSage, FakeTagger
    sentences = ["Работа с информации ведётся."]
    factories = {"commas": lambda: FakeTagger(), "forms": lambda: FakeTagger(forms={"информации": ("case:ablt", 0.5)}),
                 "spell": lambda: FakeTagger(), "sage": lambda: FakeSage({"с информации": "с информацией"})}
    got = {}
    for stage, i, items in Checker(models_dir, factories=factories).stream(sentences):
        got.setdefault(stage, []).extend((f["rule"], f["level"], f["fix"]) for f in items)
    assert got["forms"] == [("MODEL_FORM", "check", "информацией")]
    assert got["sage"] == [("SAGE_ENDING", "error", "информацией")]
    # resumed at the SAGE stage there is nothing to confirm: no promotion
    resumed = [f for stage, i, items in Checker(models_dir, factories=factories).stream(sentences, start=("sage", 0))
               for f in items]
    assert resumed == []


def test_sage_confirms_a_half_sure_comma_deletion_of_the_ensemble(models_dir):
    from fakes import FakeSage, FakeTagger
    sentences = ["Документ, определяющий порядок утверждён."]

    def run(sage_fixes):
        factories = {"commas": [lambda: FakeTagger(del_after={"Документ"}, del_p=0.6) for _ in range(3)],
                     "forms": lambda: FakeTagger(), "spell": lambda: FakeTagger(), "sage": lambda: FakeSage(sage_fixes)}
        got = {}
        for stage, i, items in Checker(models_dir, factories=factories).stream(sentences):
            got.setdefault(stage, []).extend((f["rule"], f["level"], f["fix"]) for f in items)
        return got
    got = run({"Документ,": "Документ"})
    assert got["commas"] == []                                   # 0.6 is below the sure deletion threshold: not shown
    assert got["sage"] == [("SAGE_COMMA_DEL", "error", "")]
    assert run({})["sage"] == []                                 # SAGE keeps the comma: nothing shown at all


CASE = ["Договор подписан сторонами.", "Пункты договора согласованы.", "Срок договора истёк.",
        "Подписан Договор сегодня."]


def stage_findings(c, sentences, stage, **kw):
    return [(i, [(f["rule"], f["start"], f["end"]) for f in items])
            for st, i, items in c.stream(sentences, **kw) if st == stage]


def test_structure_changes_nothing_for_model_stages(models_dir):
    kinds = ["body", "heading", "table", "list"]
    for stage in ("commas", "forms", "spell", "sage"):
        c = checker(models_dir)
        assert stage_findings(c, SENTENCES, stage, structure=kinds) == stage_findings(c, SENTENCES, stage)


def test_rules_skip_capital_mid_in_headings(models_dir):
    c = checker(models_dir, strict=True)
    plain = stage_findings(c, CASE, "rules")
    assert any(r == "RULE_CAPITAL_MID" for r, _, _ in plain[3][1])
    as_body = stage_findings(c, CASE, "rules", structure=["body"] * 4)
    assert as_body == plain
    as_heading = stage_findings(c, CASE, "rules", structure=["body"] * 3 + ["heading"])
    assert not any(r == "RULE_CAPITAL_MID" for r, _, _ in as_heading[3][1])


def test_rules_take_kinds_of_the_context_when_one_is_given(models_dir, monkeypatch):
    from spellcheck import rules
    made = []
    real = rules.DocContext

    def spy(*args, **kwargs):
        made.append(args)
        return real(*args, **kwargs)
    monkeypatch.setattr(rules, "DocContext", spy)
    c = checker(models_dir, strict=True)
    # a recheck of the last sentence only: the context kinds are parallel to the context, the sentence kind to the sentence
    kinds = ["body"] * 3 + ["heading"]
    got = stage_findings(c, CASE[3:], "rules", context=CASE, structure=["heading"], context_structure=kinds)
    assert made[-1][2] == kinds and not any(r == "RULE_CAPITAL_MID" for r, _, _ in got[0][1])
    got = stage_findings(c, CASE[3:], "rules", context=CASE, structure=["body"], context_structure=kinds)
    assert any(r == "RULE_CAPITAL_MID" for r, _, _ in got[0][1])
    stage_findings(c, CASE, "rules", structure=kinds)
    assert made[-1][2] == kinds
