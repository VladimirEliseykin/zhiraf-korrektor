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
