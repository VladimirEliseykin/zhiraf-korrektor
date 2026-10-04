"""Reviewing one document's marks: what is open, accepted, skipped; navigation; undo.

Pure Python, no Qt: the window shows what this session says and calls its methods.
Mark positions are kept in the coordinates of the ORIGINAL paragraph text (the text the check ran
on); the current text is the original with the accepted fixes applied.
"""
import bisect
from dataclasses import dataclass
from typing import Optional

from .documents.model import Replacement, apply_replacements

OPEN, ACCEPTED, MANUAL, SKIPPED, DICTIONARY = "open", "accepted", "manual", "skipped", "dictionary"
APPLIED = (ACCEPTED, MANUAL)
LEVEL_RANK = {"error": 2, "check": 1}
SOURCE_RANK = {"SAGE": 3, "RULE": 2, "MODEL": 1}
DICTIONARY_RULES = {"RULE_TYPO", "RULE_MIXED_SCRIPT", "RULE_LATIN_HYPHEN", "RULE_NE_JOIN", "SAGE_TYPO", "SAGE_JOIN"}


@dataclass
class Mark:
    id: int
    paragraph: int
    start: int
    end: int
    level: str
    rule: str
    fix: Optional[str]
    message: str
    original: str
    status: str = OPEN
    applied: Optional[str] = None

    @property
    def rank(self):
        return LEVEL_RANK[self.level], SOURCE_RANK.get(self.rule.split("_")[0], SOURCE_RANK["RULE"])

    @property
    def can_add_to_dictionary(self):
        return self.rule in DICTIONARY_RULES and bool(self.original.strip())


@dataclass
class Edit:
    """A change of the CURRENT paragraph text that the window repeats in its view."""
    paragraph: int
    start: int
    end: int
    text: str


def _overlaps(a_start, a_end, b_start, b_end):
    if a_start == a_end and b_start == b_end:
        return a_start == b_start
    if a_start == a_end:
        return b_start < a_start < b_end   # an insertion meets a span only strictly inside it
    if b_start == b_end:
        return a_start < b_start < a_end
    return a_start < b_end and b_start < a_end


def _key(mark):
    return mark.paragraph, mark.start, mark.end, mark.id


class ReviewSession:
    def __init__(self, paragraphs, dictionary=None):
        self.originals = list(paragraphs)
        self.dictionary = dictionary
        self.marks = []
        self.current = None
        self._next_id = 1
        self._by_par = {}   # paragraph -> its marks sorted by _key (index over self.marks)
        self._par_keys = {}  # paragraph -> the _key of each of those marks
        self._keys = []     # the _key of each of self.marks
        self._removed = []
        self._versions = {}
        # groups of ([(mark, previous status, previous applied), ...], word added to the dictionary or None)
        self._undo = []

    def version(self, paragraph):
        return self._versions.get(paragraph, 0)

    def _insert(self, mark):
        """Put the mark into self.marks and its paragraph list, both kept sorted by _key (no re-sorting)."""
        key = _key(mark)
        i = bisect.bisect_left(self._keys, key)
        self._keys.insert(i, key)
        self.marks.insert(i, mark)
        local, local_keys = self._by_par.setdefault(mark.paragraph, []), self._par_keys.setdefault(mark.paragraph, [])
        j = bisect.bisect_left(local_keys, key)
        local_keys.insert(j, key)
        local.insert(j, mark)

    def _discard(self, mark):
        key = _key(mark)
        i = bisect.bisect_left(self._keys, key)
        del self._keys[i]
        del self.marks[i]
        local_keys = self._par_keys[mark.paragraph]
        j = bisect.bisect_left(local_keys, key)
        del local_keys[j]
        del self._by_par[mark.paragraph][j]

    def pop_removed(self):
        """Marks that add_findings removed (a stronger finding took their place) since the last call."""
        removed, self._removed = self._removed, []
        return removed

    # --- findings arriving from the check ---

    def add_findings(self, paragraph, offset, findings, version=None):
        added = []
        if version is not None and version != self.version(paragraph):
            return added
        text = self.originals[paragraph]
        local = self._by_par.setdefault(paragraph, [])
        for f in findings:
            if f.get("level") not in LEVEL_RANK:
                continue
            start, end = offset + f["start"], offset + f["end"]
            original = text[start:end]
            if self.dictionary is not None and original.strip() and original.strip() in self.dictionary:
                continue
            clash = [m for m in local if _overlaps(start, end, m.start, m.end)]
            if any(m.status != OPEN for m in clash):
                continue  # the reader has already decided about this place
            mark = Mark(self._next_id, paragraph, start, end, f["level"], f["rule"], f.get("fix"),
                        f.get("message", ""), original)
            if any(m.rank >= mark.rank for m in clash):
                continue
            self._next_id += 1
            for m in clash:
                if self.current is m:
                    self.current = mark
                self._discard(m)
                self._removed.append(m)
            self._insert(mark)
            added.append(mark)
        if self.current is None:
            self.current = next((m for m in self.marks if m.status == OPEN), None)
        return added

    # --- navigation ---

    def open_marks(self):
        return [m for m in self.marks if m.status == OPEN]

    def go_next(self):
        opens = self.open_marks()
        if not opens:
            self.current = None
        elif self.current is None:
            self.current = opens[0]
        else:
            after = [m for m in opens if _key(m) > _key(self.current)]
            self.current = after[0] if after else opens[0]
        return self.current

    def go_prev(self):
        opens = self.open_marks()
        if not opens:
            self.current = None
        elif self.current is None:
            self.current = opens[-1]
        else:
            before = [m for m in opens if _key(m) < _key(self.current)]
            self.current = before[-1] if before else opens[-1]
        return self.current

    def select(self, mark_id):
        mark = next((m for m in self.marks if m.id == mark_id), None)
        if mark is not None and mark.status == OPEN:
            self.current = mark
        return mark

    # --- decisions ---

    def _change(self, marks, status, texts, word=None):
        group, edits = [], []
        for mark, text in zip(marks, texts):
            if status in APPLIED:
                start = self.to_current(mark.paragraph, mark.start)
                edits.append(Edit(mark.paragraph, start, start + mark.end - mark.start, text))
            group.append((mark, mark.status, mark.applied))
            mark.status, mark.applied = status, (text if status in APPLIED else None)
        if group:
            self._undo.append((group, word))
        return edits

    def accept(self):
        mark = self.current
        if mark is None or mark.fix is None:
            return []
        edits = self._change([mark], ACCEPTED, [mark.fix])
        self.go_next()
        return edits

    def manual(self, text):
        mark = self.current
        if mark is None:
            return []
        if text == mark.original:
            return self.skip()
        edits = self._change([mark], MANUAL, [text])
        self.go_next()
        return edits

    def skip(self):
        mark = self.current
        if mark is None:
            return []
        self._change([mark], SKIPPED, [None])
        self.go_next()
        return []

    def add_to_dictionary(self):
        mark = self.current
        if mark is None or not mark.can_add_to_dictionary:
            return None
        word = mark.original.strip()
        if self.dictionary is not None:
            self.dictionary.add(word)
        same = [m for m in self.marks
                if m.status == OPEN and m.can_add_to_dictionary and m.original.strip().lower() == word.lower()]
        self._change(same, DICTIONARY, [None] * len(same), word=word)
        self.go_next()
        return word

    def accept_all_errors(self):
        targets = [m for m in self.marks if m.status == OPEN and m.level == "error" and m.fix is not None]
        edits = self._change(targets, ACCEPTED, [m.fix for m in targets])
        if self.current is not None and self.current.status != OPEN:
            self.go_next()
        return edits

    def undo(self):
        if not self._undo:
            return []
        group, word = self._undo.pop()
        if word is not None and self.dictionary is not None:
            self.dictionary.remove(word)
        edits = []
        for mark, status, applied in reversed(group):
            if mark.status in APPLIED:
                start = self.to_current(mark.paragraph, mark.start, exclude=mark)
                edits.append(Edit(mark.paragraph, start, start + len(mark.applied), mark.original))
            mark.status, mark.applied = status, applied
        reopened = [m for m, _, _ in group if m.status == OPEN]
        if reopened:
            self.current = min(reopened, key=_key)
        return edits

    # --- text and positions ---

    def to_current(self, paragraph, pos, exclude=None):
        shift = 0
        for m in self._by_par.get(paragraph, ()):
            if m.status in APPLIED and m is not exclude and m.end <= pos:
                shift += len(m.applied) - (m.end - m.start)
        return pos + shift

    def span(self, mark):
        start = self.to_current(mark.paragraph, mark.start, exclude=mark)
        length = len(mark.applied) if mark.status in APPLIED else mark.end - mark.start
        return start, start + length

    def text(self, paragraph):
        return apply_replacements(self.originals[paragraph],
                                  [Replacement(m.paragraph, m.start, m.end, m.applied)
                                   for m in self._by_par.get(paragraph, ()) if m.status in APPLIED])

    def replacements(self):
        return [Replacement(m.paragraph, m.start, m.end, m.applied) for m in self.marks if m.status in APPLIED]

    def counts(self):
        statuses = [(m.status, m.level) for m in self.marks]
        return {"errors": statuses.count((OPEN, "error")), "checks": statuses.count((OPEN, "check")),
                "fixed": sum(1 for s, _ in statuses if s in APPLIED),
                "skipped": sum(1 for s, _ in statuses if s == SKIPPED),
                "dictionary": sum(1 for s, _ in statuses if s == DICTIONARY), "total": len(statuses)}

    def replace_paragraph(self, paragraph, new_text):
        """The reader typed in this paragraph (pasted text only): its marks and their history go away."""
        self.originals[paragraph] = new_text
        self._versions[paragraph] = self.version(paragraph) + 1
        gone = self._by_par.pop(paragraph, [])
        self._par_keys.pop(paragraph, None)
        gone_ids = {id(m) for m in gone}
        self.marks = [m for m in self.marks if m.paragraph != paragraph]
        self._keys = [_key(m) for m in self.marks]
        undo = [([e for e in entries if id(e[0]) not in gone_ids], word) for entries, word in self._undo]
        self._undo = [(entries, word) for entries, word in undo if entries]
        if self.current is not None and id(self.current) in gone_ids:
            self.current = None
            self.go_next()
