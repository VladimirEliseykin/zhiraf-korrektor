"""Pieces of a paragraph's text as stored in a file: editable text nodes and fixed characters.

Saving a fix "in place" means rewriting only the text nodes the fix covers; a fix that would cross
a fixed character (a tab, a line break, a field) is refused rather than risk damaging the file.
"""


class Slot:
    """Editable text stored in some XML node; subclasses know where."""
    editable = True

    def __init__(self, text):
        self.text = text

    def write(self, text):
        raise NotImplementedError


class FixedSlot(Slot):
    """A character the file stores as an element (tab, line break): shown, never edited."""
    editable = False

    def write(self, text):
        raise RuntimeError("fixed text cannot be edited")


def _char_map(slots):
    """For every character of the paragraph: (slot index, offset inside the slot)."""
    chars = []
    for index, slot in enumerate(slots):
        chars.extend((index, k) for k in range(len(slot.text)))
    return chars


def apply_to_slots(slots, start, end, text):
    """Put text in place of characters [start, end) of the paragraph.

    False when a fixed character is in the way or an insertion has no editable text to join.
    An insertion (start == end, a comma) joins the text before it: the end of the previous word.
    A replacement across several text nodes goes into the first one; the others give up their part.
    """
    chars = _char_map(slots)
    if start == end:
        for pos, after in ((start - 1, True), (start, False)):
            if 0 <= pos < len(chars) and slots[chars[pos][0]].editable:
                index, k = chars[pos]
                k += 1 if after else 0
                slot = slots[index]
                slot.write(slot.text[:k] + text + slot.text[k:])
                return True
        return False
    if start < 0 or end > len(chars):
        return False
    touched = sorted({chars[i][0] for i in range(start, end)})
    if any(not slots[i].editable for i in range(touched[0], touched[-1] + 1)):
        return False
    first, last = touched[0], touched[-1]
    k0, k1 = chars[start][1], chars[end - 1][1] + 1
    if first == last:
        slot = slots[first]
        slot.write(slot.text[:k0] + text + slot.text[k1:])
        return True
    slots[first].write(slots[first].text[:k0] + text)
    for i in range(first + 1, last):
        slots[i].write("")
    slots[last].write(slots[last].text[k1:])
    return True
