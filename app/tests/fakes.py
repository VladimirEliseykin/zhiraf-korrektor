"""Stand-ins for the neural models: fast, deterministic, no model files."""
import time

from spellcheck.text import words_of


class FakeTagger:
    def __init__(self, comma_after=(), forms=None, delay=0.0, add_p=0.95, log=None, name=None, del_after=(), del_p=0.95,
                 fail_after=None, spell=None):
        self.comma_after = set(comma_after)
        self.add_p = add_p
        self.log = log  # shared list: ("predict", name) per call, to check the order of the passes
        self.name = name
        self.del_after = set(del_after)
        self.del_p = del_p
        self.fail_after = fail_after  # raise on this call number (1-based): a model that dies mid-pass
        self.calls = 0
        self.forms = forms or {}
        self.spell = spell  # None: a model without the spelling head; else {word: (label, p)}
        self.delay = delay

    def predict(self, text):
        if self.delay:
            time.sleep(self.delay)
        self.calls += 1
        if self.fail_after is not None and self.calls == self.fail_after:
            raise RuntimeError("predict failed")
        if self.log is not None:
            self.log.append(("predict", self.name))
        out = []
        for m in words_of(text):
            word = m.group(0)
            add = self.add_p if word in self.comma_after else 0.0
            label, p = self.forms.get(word, ("KEEP", 0.99))
            dele = self.del_p if word in self.del_after else 0.0
            out.append({"comma": {"KEEP": 1.0 - add - dele, "ADD": add, "DEL": dele}, "form": label, "form_p": p,
                        "form_keep_p": p if label == "KEEP" else 1.0 - p})
            if self.spell is not None:
                name, q = self.spell.get(word, ("KEEP", 1.0))
                probs = {k: 0.0 for k in ("KEEP", "JOIN", "HYPHEN", "SPLIT", "LOWER", "UPPER")}
                probs[name] = q
                probs["KEEP"] += 1.0 - q if name != "KEEP" else 0.0
                out[-1]["spell"] = probs
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
            "spell": lambda: FakeTagger(),
            "sage": lambda: FakeSage({"инфомационной": "информационной"})}


def make_ensemble_factories():
    """Two comma models that agree, one forms model: the commas stage makes two passes."""
    factories = make_factories()
    factories["commas"] = [lambda: FakeTagger(comma_after={"Документ"}), lambda: FakeTagger(comma_after={"Документ"})]
    return factories


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
