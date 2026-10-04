"""How much of the check is done and when it will end, measured on this very computer."""
import time

DEFAULT_LOAD_SECONDS = 3.0
MIN_LOAD_COST = 0.01


class Progress(object):
    def __init__(self, n_sentences, stages, cost, clock=None):
        if clock is None:
            clock = time.monotonic
        self.n = n_sentences
        self.stages = list(stages)
        self.cost = dict(cost)
        self.clock = clock
        self.done = {s: 0 for s in self.stages}
        self.skipped = {s: 0 for s in self.stages}  # sentences a resumed check does not repeat
        self.passes = {s: 1 for s in self.stages}  # model passes per stage; every pass over a sentence is a step
        self.started = None
        self.last_event = None
        self.stage_begin = {}
        self.first = {}
        self.last = {}

    def start(self):
        t0 = self.clock()
        self.started = t0
        self.last_event = t0

    def skip(self, stage, count):
        """Count `count` sentences of the stage as already done (a resumed check)."""
        if stage in self.skipped:
            self.skipped[stage] = max(0, min(self.n, count))

    def set_passes(self, passes):
        """A stage with several models makes that many passes over the sentences (cost is per pass)."""
        for stage, count in passes.items():
            if stage in self.passes:
                self.passes[stage] = max(1, int(count))

    def _size(self, stage):
        return self.n * self.passes[stage]

    def _skipped_steps(self, stage):
        return self.skipped[stage] * self.passes[stage]

    def sentence_done(self, stage):
        """One step of a stage is done: a sentence checked, or a sentence of a silent pass of an earlier model."""
        now = self.clock()
        if self.done[stage] == 0:
            self.stage_begin[stage] = self.last_event
            self.first[stage] = now
        self.last[stage] = now
        self.done[stage] += 1
        self.last_event = now

    def _units(self, counts):
        return sum(self.cost[s] * counts[s] for s in self.stages)

    def _total(self):
        return self._units({s: self._size(s) for s in self.stages})

    def fraction(self):
        total = self._total()
        if total <= 0:
            return 1.0
        counts = {s: self.done[s] + self._skipped_steps(s) for s in self.stages}
        return min(1.0, self._units(counts) / total)

    def _get_rates(self):
        rates = {}
        for stage in self.stages:
            if self.done[stage] >= 2:
                rates[stage] = (self.last[stage] - self.first[stage]) / (self.done[stage] - 1)
        return rates

    def _get_loads(self, rates):
        loads = {}
        for stage, rate in rates.items():
            loads[stage] = max(0, self.first[stage] - self.stage_begin[stage] - rate)
        return loads

    def _models_to_load(self, stage):
        """Models of the stage whose pass has not begun (every model of a stage makes one pass over the sentences)."""
        per_pass = max(1, self.n - self.skipped[stage])
        begun = -(-self.done[stage] // per_pass)  # ceil: a pass with one step done has loaded its model
        return max(0, self.passes[stage] - begun)

    def remaining_seconds(self):
        if self.started is None:
            return None

        rates = self._get_rates()
        if not rates:
            return None

        loads = self._get_loads(rates)

        numerator = sum(rates[s] * self.done[s] for s in rates if self.cost[s] >= MIN_LOAD_COST)
        denominator = sum(self.cost[s] * self.done[s] for s in rates if self.cost[s] >= MIN_LOAD_COST)
        speed_factor = numerator / denominator if denominator > 0 else 1.0

        load_stages = [s for s in rates if self.cost[s] >= MIN_LOAD_COST]
        if load_stages:
            average_load = sum(loads[s] for s in load_stages) / len(load_stages)
        else:
            average_load = DEFAULT_LOAD_SECONDS

        remaining = 0.0
        for stage in self.stages:
            left = self._size(stage) - self.done[stage] - self._skipped_steps(stage)
            if left <= 0:
                continue
            elif stage in rates:
                remaining += left * rates[stage]
                remaining += average_load * self._models_to_load(stage)
            else:
                remaining += left * self.cost[stage] * speed_factor
                if self.cost[stage] >= MIN_LOAD_COST:
                    remaining += average_load * self._models_to_load(stage)

        return max(0.0, remaining)

    def finish_at(self, now=None):
        remaining = self.remaining_seconds()
        if remaining is None:
            return None
        return (time.time() if now is None else now) + remaining
