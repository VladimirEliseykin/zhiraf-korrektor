"""Split a paragraph into sentences with their offsets: the engine checks one sentence at a time."""
import re

ABBREVIATIONS = {
    "т", "е", "д", "п", "г", "гг", "ст", "пп", "ч", "им", "рис", "табл", "см", "др", "руб", "тыс", "млн", "млрд",
    "стр", "ул", "кв", "тел", "прим", "вып", "гл", "разд", "подп", "абз", "обл", "корп", "пер", "проф", "акад",
    "доц", "канд", "экз", "шт", "коп", "мин", "сек", "изд", "т.е", "т.д", "т.п", "т.к", "т.н", "н.э", "и.о",
}
BREAK = re.compile(r'[.!?…]+[»")\]]*\s+')
NEXT_STARTS = re.compile(r'[«"(]?[А-ЯЁA-Z0-9]')
NUMBER_OR_MARKER = re.compile(r"^(\d+(\.\d+)*\.?|[а-яa-z]\)|[IVXLC]+\.?)$")


def _skip_space(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def split_sentences(text):
    """Sentence spans (start, end) in text, surrounding whitespace excluded."""
    spans = []
    start = _skip_space(text, 0)
    for m in BREAK.finditer(text):
        if m.start() < start or not NEXT_STARTS.match(text, m.end()):
            continue
        head = text[start:m.start()]
        if NUMBER_OR_MARKER.match(head.strip()):
            continue  # "1." or "2.1." starts a heading, it is not a sentence of its own
        if m.group(0).rstrip().rstrip('»")]') == ".":
            words = head.split()
            last = words[-1].lstrip('«"(').lower() if words else ""
            if last in ABBREVIATIONS or (len(last) == 1 and last.isalpha()):
                continue  # "г.", "т. е.", initials "А. С."
        end = m.start() + len(m.group(0).rstrip())
        spans.append((start, end))
        start = _skip_space(text, m.end())
    tail = text[start:].rstrip()
    if tail:
        spans.append((start, start + len(tail)))
    return spans
