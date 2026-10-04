import pytest

from zhiraf.eta import Progress

COST = {"rules": 0.0, "commas": 1.0, "sage": 3.0}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_fraction_weighs_stages_by_cost():
    p = Progress(10, ("rules", "commas", "sage"), COST, Clock())
    p.start()
    for _ in range(10):
        p.sentence_done("commas")
    assert p.fraction() == pytest.approx(10 / 40)


def test_load_gap_does_not_inflate_estimate():
    """Load pauses between stages should not inflate the final estimate."""
    clock = Clock()
    cost = {"rules": 0.003, "commas": 0.1, "forms": 0.1, "sage": 0.5}
    p = Progress(100, ("rules", "commas", "forms", "sage"), cost, clock)

    p.start()

    for _ in range(100):
        clock.now += 0.001
        p.sentence_done("rules")

    clock.now += 3.0

    for _ in range(10):
        clock.now += 0.2
        p.sentence_done("commas")

    remaining = p.remaining_seconds()
    assert remaining is not None
    assert remaining == pytest.approx(144.0, abs=1.0)


def test_unknown_before_any_stage_has_two_sentences():
    """Returns None until a stage has >= 2 sentences."""
    clock = Clock()
    p = Progress(5, ("commas",), {"commas": 1.0}, clock)

    assert p.remaining_seconds() is None

    p.start()
    assert p.remaining_seconds() is None

    clock.now = 1.0
    p.sentence_done("commas")
    assert p.remaining_seconds() is None

    clock.now = 2.0
    p.sentence_done("commas")
    assert p.remaining_seconds() is not None


def test_finish_at_with_remaining():
    """finish_at(now) returns now + remaining_seconds()."""
    clock = Clock()
    p = Progress(10, ("commas",), {"commas": 0.1}, clock)

    p.start()
    clock.now = 0.1
    p.sentence_done("commas")
    clock.now = 0.2
    p.sentence_done("commas")

    remaining = p.remaining_seconds()
    assert remaining is not None

    finish_at_1000 = p.finish_at(now=1000.0)
    assert finish_at_1000 == pytest.approx(1000.0 + remaining, abs=0.01)


def test_done_and_empty_document():
    clock = Clock()
    p = Progress(0, ("commas",), COST, clock)
    p.start()
    assert p.fraction() == 1.0


def test_skipped_work_counts_as_done():
    p = Progress(10, ("a", "b"), {"a": 1.0, "b": 1.0}, Clock())
    p.skip("a", 10)
    p.skip("b", 5)
    assert p.fraction() == pytest.approx(15 / 20)
    p.start()
    for _ in range(5):
        p.sentence_done("b")
    assert p.fraction() == 1.0


def test_second_model_pass_doubles_the_stage_work():
    p = Progress(10, ("commas", "sage"), {"commas": 1.0, "sage": 3.0}, Clock())
    p.set_passes({"commas": 2, "sage": 1})
    p.start()
    for _ in range(10):  # the silent pass of the first model
        p.sentence_done("commas")
    assert p.fraction() == pytest.approx(10 / (20 + 30))
    for _ in range(10):
        p.sentence_done("commas")
    assert p.fraction() == pytest.approx(20 / 50)


def test_resume_skips_every_pass_of_a_finished_stage():
    p = Progress(10, ("commas", "sage"), {"commas": 1.0, "sage": 3.0}, Clock())
    p.set_passes({"commas": 2})
    p.skip("commas", 10)
    assert p.fraction() == pytest.approx(20 / 50)


def test_estimate_counts_both_passes_of_a_stage():
    clock = Clock()
    p = Progress(10, ("commas",), {"commas": 0.1}, clock)
    p.set_passes({"commas": 2})
    p.start()
    for _ in range(10):
        clock.now += 1.0
        p.sentence_done("commas")
    # ten steps took 1 s each (9 s between the first and the last): ten steps are still to come
    assert p.remaining_seconds() == pytest.approx(10.0)


def test_each_model_still_to_load_adds_the_average_load_time():
    """Stage commas has three models; its first one is loaded (3 s) and half done: two more loads are ahead."""
    def make(passes):
        clock = Clock()
        p = Progress(10, ("commas", "sage"), {"commas": 0.1, "sage": 0.5}, clock)
        p.set_passes({"commas": passes})
        p.start()
        clock.now += 3.0  # loading the first model
        for _ in range(5):
            clock.now += 1.0
            p.sentence_done("commas")
        return p
    one, three = make(1), make(3)
    # three models ahead: 20 more steps of 1 s and the loading of two more models (3 s each)
    assert three.remaining_seconds() - one.remaining_seconds() == pytest.approx(20 * 1.0 + 2 * 3.0, abs=0.01)
