"""How much of the check is done and when it will end, measured on this very computer."""
import time

MIN_SECONDS = 2.0  # before that the speed is noise (models are still loading)


class Progress(object):
    def __init__(self, n_sentences, stages, cost, clock=None):
        if clock is None:
            clock = time.monotonic
        self.n = n_sentences
        self.stages = list(stages)
        self.cost = dict(cost)
        self.clock = clock
        self.done = {s: 0 for s in self.stages}
        self.started = None

    def start(self):
        self.started = self.clock()

    def sentence_done(self, stage):
        self.done[stage] += 1

    def _units(self, counts):
        return sum(self.cost[s] * counts[s] for s in self.stages)

    def _total(self):
        return self._units({s: self.n for s in self.stages})

    def fraction(self):
        total = self._total()
        if total <= 0:
            return 1.0
        return min(1.0, self._units(self.done) / total)

    def remaining_seconds(self):
        done = self._units(self.done)
        if self.started is None or done <= 0:
            return None
        elapsed = self.clock() - self.started
        if elapsed < MIN_SECONDS:
            return None
        return max(0.0, (self._total() - done) * elapsed / done)

    def finish_at(self, now=None):
        remaining = self.remaining_seconds()
        if remaining is None:
            return None
        return (time.time() if now is None else now) + remaining
