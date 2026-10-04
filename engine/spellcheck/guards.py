"""Protective layer between the author's text and the models.

prepare() strips list markers before a model sees the text; allowed() decides which edits of a
rewriting model (SAGE) may reach the author, so anything it rejects stays exactly as written.
"""
import re

TOKEN = re.compile(r"\s+|\w+(?:-\w+)*|[^\w\s]")
LIST_MARKER = re.compile(r"^\s*(?:[•●▪◦·\-–—*]|\d{1,2}[.)]|[а-яa-z][)])\s+")
LATIN = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"\d")
QUOTES = set('"«»„“”')
BIBLIOGRAPHY = re.compile(r"\[(Электронный ресурс|Текст)\]|//|\s/\s[А-ЯЁA-Z]|–\s*С\.\s*\d|—\s*С\.\s*\d|\bURL:|\bISBN\b|"
                          r"–\s*\d+\s*с\.")
QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")
PROTECTED = re.compile(r".*[0-9A-Za-z].*")


def prepare(text):
    """Return (marker, body): the list marker is never shown to a model."""
    match = LIST_MARKER.match(text)
    if match:
        return match.group(0), text[match.end():]
    return "", text


def is_protected_word(token):
    """Words a rewriting model must never touch: numbers, latin, mixed-case abbreviations."""
    if DIGIT.search(token) or LATIN.search(token):
        return True
    upper = sum(c.isupper() for c in token)
    return upper >= 2 and upper != len(token.replace("-", ""))


def protected(word):
    """Words the tagger must not inflect: anything with digits/latin, abbreviations."""
    upper = sum(c.isupper() for c in word)
    return bool(PROTECTED.match(word)) or upper >= 2


def quoted_spans(text):
    return [m.span() for m in QUOTED.finditer(text)]


def allowed(before, after, at_start, at_end, src_first_lower):
    joined_before, joined_after = "".join(before), "".join(after)
    if not joined_before.strip() and not joined_after.strip():
        return False  # whitespace-only edits (e.g. "А.В." -> "А. В.")
    if any(is_protected_word(t) for t in before + after if t.strip()):
        return False
    if set(joined_after.replace(" ", "")) & QUOTES and not set(joined_before) & QUOTES:
        return False  # the model loves adding quotes; too unreliable
    if at_end and joined_before.strip() in (";", ":"):
        return False  # list items legitimately end with ; or :
    if at_start and src_first_lower and joined_before.lower() == joined_after.lower():
        return False  # list continuation starts lowercase on purpose
    if "…" in joined_before or ". . ." in joined_after or ".." in joined_after.replace(" ", ""):
        return False
    return True
