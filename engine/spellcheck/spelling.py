"""Data shared by the spelling corruptions (train/corrupt.py) and the spelling findings (checker.py).

One copy of each table: what the generator treats as ambiguous is exactly what the checker will not call sure.
"""
import os

# fixed spellings that are often written apart: joined form -> length of its first part
JOINED_TABLE = {"поэтому": 2, "также": 3, "тоже": 2, "чтобы": 3, "зато": 2, "притом": 3, "причем": 3,
                "причём": 3, "ввиду": 1, "вследствие": 1, "насчет": 2, "насчёт": 2, "навстречу": 2,
                "затем": 2, "поскольку": 2, "несмотря": 2, "вместо": 1, "вроде": 1, "навсегда": 2,
                "потому": 2, "незадолго": 2}
# pairs that are also right written apart in some context ("по этому вопросу", "так же как", "в течение недели"):
# a JOIN there is at most a "check"; every joined form of JOINED_TABLE is such a pair
AMBIGUOUS_PAIRS = {("так", "же"), ("то", "же"), ("что", "бы"), ("при", "чем"), ("на", "счет"), ("на", "счёт"),
                   ("в", "виду"), ("за", "то"), ("по", "этому"), ("в", "течение"), ("в", "течении")}
# "так же как", "то же самое": the following word shows that the pair is meant apart
SEPARATE_BEFORE = {("так", "же"): {"как", "же", "самое"}, ("то", "же"): {"как", "же", "самое"}}


def is_ambiguous_pair(first, second):
    first, second = first.lower(), second.lower()
    return (first, second) in AMBIGUOUS_PAIRS or first + second in JOINED_TABLE


def pair_is_meant_apart(first, second, following):
    """"так же" / "то же" before "как", "же", "самое" is the right spelling: never joined, never created."""
    return (following or "").lower() in SEPARATE_BEFORE.get((first.lower(), second.lower()), ())


def load_capital_lemmas(path=None):
    """Lemmas of common nouns that official text capitalises mid-sentence (train/capital_stats.py made the file)."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "capital_lemmas.txt")
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip() and not line.startswith("#")}


CAPITAL_LEMMAS = load_capital_lemmas()
