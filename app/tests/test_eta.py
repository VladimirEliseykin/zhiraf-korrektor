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


def test_remaining_uses_measured_speed():
    clock = Clock()
    p = Progress(10, ("commas", "sage"), COST, clock)
    p.start()
    for _ in range(10):
        p.sentence_done("commas")
    clock.now = 20.0  # twice as slow as the prior cost said
    assert p.remaining_seconds() == pytest.approx(60.0)
    assert p.finish_at(now=1000.0) == pytest.approx(1060.0)


def test_unknown_before_measuring():
    clock = Clock()
    p = Progress(5, ("commas",), COST, clock)
    assert p.remaining_seconds() is None
    p.start()
    p.sentence_done("commas")
    clock.now = 1.0
    assert p.remaining_seconds() is None


def test_done_and_empty_document():
    clock = Clock()
    p = Progress(0, ("commas",), COST, clock)
    p.start()
    assert p.fraction() == 1.0
