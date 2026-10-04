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


def test_load_gap_inflates_estimate():
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
