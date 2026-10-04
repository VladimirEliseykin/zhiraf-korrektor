"""Stand-ins for the neural models: fast, deterministic, no model files."""
import time

from spellcheck.text import words_of


class FakeTagger:
    def __init__(self, comma_after=(), forms=None, delay=0.0):
        self.comma_after = set(comma_after)
        self.forms = forms or {}
        self.delay = delay

    def predict(self, text):
        if self.delay:
            time.sleep(self.delay)
        out = []
        for m in words_of(text):
            word = m.group(0)
            add = 0.95 if word in self.comma_after else 0.0
            label, p = self.forms.get(word, ("KEEP", 0.99))
            out.append({"comma": {"KEEP": 1.0 - add, "ADD": add, "DEL": 0.0}, "form": label, "form_p": p,
                        "form_keep_p": p if label == "KEEP" else 1.0 - p})
        return out


class FakeSage:
    def __init__(self, fixes=None):
        self.fixes = fixes or {}

    def correct(self, text):
        for wrong, right in self.fixes.items():
            text = text.replace(wrong, right)
        return text


def make_factories():
    return {"commas": lambda: FakeTagger(comma_after={"Документ"}),
            "forms": lambda: FakeTagger(forms={"информации": ("case:ablt", 0.95)}),
            "sage": lambda: FakeSage({"инфомационной": "информационной"})}


def make_slow_factories():
    factories = make_factories()
    factories["commas"] = lambda: FakeTagger(delay=0.3)
    return factories


def _broken():
    raise RuntimeError("model files are missing")


def make_broken_factories():
    factories = make_factories()
    factories["commas"] = _broken
    return factories


def _oom():
    raise RuntimeError("bad allocation of 4 GB for the weights")


def make_oom_factories():
    factories = make_factories()
    factories["commas"] = _oom
    return factories
