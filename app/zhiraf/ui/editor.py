"""The text of the document on "paper": one block per paragraph, marks as character formats."""
from typing import Iterable, Optional

from PySide2.QtCore import QEvent, QPointF, QRect, Qt, QTimer, Signal
from PySide2.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextFormat, QTextListFormat)
from PySide2.QtWidgets import QTextEdit, QToolTip

from ..review import ACCEPTED, MANUAL, OPEN, SKIPPED
from .blockfmt import BASE_UNDERLINE_PROP, LINE_SEPARATOR, MARK_ID_PROP, MARK_PROP, spans_from_block
from .runs import display_range, paragraph_runs, to_utf16
from .theme import COLORS

EDIT_DELAY_MS = 700
BASE_POINT_SIZE = 13.0
HEADING_SCALE = {"title": 1.8, "h1": 1.6, "h2": 1.35, "h3": 1.15}
HEADING_LEVEL = {"title": 1, "h1": 1, "h2": 2, "h3": 3}
TABLE_SHADE = "#efe9dc"
UNCHECKED_LABEL = "ещё проверяется"
SKIPPED_LABEL = "пропущено"
IMAGE_HINT = "Здесь в документе рисунок"


def _alpha(name, alpha):
    color = QColor(COLORS[name])
    color.setAlpha(alpha)
    return color


def _shown_text(text):
    """Text as the block holds it: a line break is U+2028 and a carriage return a space (length unchanged)."""
    return text.replace("\n", LINE_SEPARATOR).replace("\r", " ").replace(" ", " ")


class ReviewEditor(QTextEdit):
    mark_clicked = Signal(int)
    paragraph_edited = Signal(int)
    edit_mode_changed = Signal(bool)
    current_rect_changed = Signal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc = None
        self._session = None
        self._writing = False          # the program (not the reader) is changing the document
        self._dirty = set()
        self.checked_until = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(EDIT_DELAY_MS)
        self._timer.timeout.connect(self.flush_edits)
        font = QFont(self.font())
        font.setPointSizeF(BASE_POINT_SIZE)
        self.setFont(font)
        self.document().setDefaultFont(font)
        self.document().setDocumentMargin(28)
        self.setStyleSheet("QTextEdit { background: %(paper)s; color: %(ink)s; border: 0; }" % COLORS)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setAcceptRichText(False)
        self.document().contentsChange.connect(self._contents_changed)
        self.document().blockCountChanged.connect(self._block_count_changed)
        self.verticalScrollBar().valueChanged.connect(lambda _: self._emit_current_rect())

    # --- loading and repainting ---

    def load(self, doc, session):
        self._timer.stop()
        self._dirty.clear()
        self._doc, self._session = doc, session
        self.checked_until = None
        self._writing = True
        try:
            self.setReadOnly(True)
            self.setUndoRedoEnabled(False)
            self.setExtraSelections([])
            self.document().clear()
            cursor = QTextCursor(self.document())
            cursor.beginEditBlock()
            for i, paragraph in enumerate(doc.paragraphs):
                block_format = self._block_format(paragraph)
                if i == 0:
                    cursor.setBlockFormat(block_format)
                else:
                    cursor.insertBlock(block_format, QTextCharFormat())
                self._insert_runs(cursor, i)
            self._make_lists(cursor)
            cursor.endEditBlock()
        finally:
            self._writing = False
        self.moveCursor(QTextCursor.Start)

    def _block_format(self, paragraph):
        fmt = QTextBlockFormat()
        if paragraph.style in HEADING_LEVEL:
            fmt.setHeadingLevel(HEADING_LEVEL[paragraph.style])
            fmt.setTopMargin(10)
            fmt.setBottomMargin(4)
        if paragraph.table is not None:
            fmt.setLeftMargin(16)
            fmt.setBackground(QBrush(QColor(TABLE_SHADE)))
        return fmt

    def _make_lists(self, cursor):
        current = None
        block = self.document().firstBlock()
        for paragraph in self._doc.paragraphs:
            if paragraph.style == "list":
                if current is None:
                    cursor.setPosition(block.position())
                    current = cursor.createList(QTextListFormat.ListDisc)
                else:
                    current.add(block)
            else:
                current = None
            block = block.next()

    def _insert_runs(self, cursor, index):
        """Write the runs of paragraph `index` at the cursor (the cursor is at the end of its empty block)."""
        paragraph = self._doc.paragraphs[index]
        for run in paragraph_runs(paragraph, self._session, index, self._show_checks):
            if run.text:
                cursor.insertText(_shown_text(run.text), self._char_format(run, paragraph.style))

    _show_checks = True

    def _char_format(self, run, style):
        fmt = QTextCharFormat()
        if style in HEADING_SCALE:
            fmt.setFontPointSize(BASE_POINT_SIZE * HEADING_SCALE[style])
            fmt.setFontWeight(QFont.Bold)
        elif run.bold:
            fmt.setFontWeight(QFont.Bold)
        fmt.setFontItalic(run.italic)
        fmt.setFontUnderline(run.underline)
        if run.mark is not None:
            mark_id, status, level = run.mark
            fmt.setProperty(MARK_PROP, status)
            fmt.setProperty(MARK_ID_PROP, mark_id)
            fmt.setProperty(BASE_UNDERLINE_PROP, run.underline)
            if status == OPEN and level == "error":
                fmt.setBackground(QBrush(_alpha("error", 70)))
                fmt.setUnderlineStyle(QTextCharFormat.SingleUnderline)
                fmt.setUnderlineColor(QColor(COLORS["error"]))
            elif status == OPEN:
                fmt.setBackground(QBrush(_alpha("check", 90)))
                fmt.setUnderlineStyle(QTextCharFormat.DotLine)
                fmt.setUnderlineColor(QColor(COLORS["check"]))
            elif status == SKIPPED:
                fmt.setBackground(QBrush(_alpha("skipped", 70)))
            else:
                fmt.setBackground(QBrush(_alpha("fixed", 80)))
        return fmt

    def repaint_paragraphs(self, indexes: Iterable[int]):
        if self._doc is None:
            return
        keep = None
        if not self.isReadOnly():
            keep = self.document().findBlock(self.textCursor().position()).blockNumber()
        cursor = QTextCursor(self.document())
        self._writing = True
        undo = self.isUndoRedoEnabled()
        if self.isReadOnly():
            self.setUndoRedoEnabled(False)
        cursor.beginEditBlock()
        try:
            for i in sorted(set(indexes)):
                if i == keep or not 0 <= i < self.document().blockCount():
                    continue
                block = self.document().findBlockByNumber(i)
                cursor.setPosition(block.position())
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                self._insert_runs(cursor, i)
        finally:
            cursor.endEditBlock()
            self._writing = False
            if self.isReadOnly():
                self.setUndoRedoEnabled(undo)

    def set_show_checks(self, value):
        self._show_checks = value

    # --- positions and marks ---

    def _utf16_position(self, paragraph, offset):
        return self.document().findBlockByNumber(paragraph).position() + to_utf16(self._session.text(paragraph),
                                                                                  offset)

    def mark_at(self, position: int) -> Optional[int]:
        """Id of the mark on the character at document position `position` (UTF-16), if any."""
        doc = self.document()
        block = doc.findBlock(position)
        if not block.isValid() or position < 0 or position >= block.position() + block.length() - 1:
            return None
        cursor = QTextCursor(doc)
        cursor.setPosition(position + 1)
        fmt = cursor.charFormat()
        if not fmt.hasProperty(MARK_PROP):
            return None
        return fmt.property(MARK_ID_PROP)

    def _position_at(self, point):
        """Position of the character under a viewport point, or -1."""
        scrolled = QPointF(point.x() + self.horizontalScrollBar().value(),
                           point.y() + self.verticalScrollBar().value())
        return self.document().documentLayout().hitTest(scrolled, Qt.ExactHit)

    def tooltip_text_at(self, position):
        mark_id = self.mark_at(position)
        if mark_id is not None:
            cursor = QTextCursor(self.document())
            cursor.setPosition(position + 1)
            if cursor.charFormat().property(MARK_PROP) in (ACCEPTED, MANUAL):
                mark = next((m for m in self._session.marks if m.id == mark_id), None)
                if mark is not None:
                    return "было: " + (mark.original or "ничего")
            return None
        number = self.document().findBlock(position).blockNumber()
        if self._doc is not None and 0 <= number < len(self._doc.paragraphs) and self._doc.paragraphs[number].has_image:
            return IMAGE_HINT
        return None

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            position = self._position_at(self.viewport().mapFromGlobal(e.globalPos())) if self._doc else -1
            text = self.tooltip_text_at(position) if position >= 0 else None
            if text:
                QToolTip.showText(e.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    # --- the current mark ---

    def show_current(self):
        mark = self._session.current if self._session is not None else None
        if mark is None:
            self.setExtraSelections([])
            return
        start, end = display_range(self._session, mark)
        a, b = self._utf16_position(mark.paragraph, start), self._utf16_position(mark.paragraph, end)
        cursor = QTextCursor(self.document())
        cursor.setPosition(a)
        cursor.setPosition(b, QTextCursor.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setProperty(QTextFormat.OutlinePen, QPen(QColor(COLORS["ink"]), 1.5))
        self.setExtraSelections([selection])
        self._scroll_to(a)
        self._current_range = (a, b)
        self._emit_current_rect()

    _current_range = None

    def _scroll_to(self, position):
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        rect = self.cursorRect(cursor)
        height = self.viewport().height()
        if rect.top() < 0 or rect.bottom() > height:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + rect.top() - height // 3)

    def _emit_current_rect(self):
        if self._current_range is None or not self.extraSelections():
            return
        a, b = self._current_range
        first, last = QTextCursor(self.document()), QTextCursor(self.document())
        first.setPosition(a)
        last.setPosition(b)
        r1, r2 = self.cursorRect(first), self.cursorRect(last)
        if r1.top() == r2.top():
            rect = QRect(r1.left(), r1.top(), max(r2.left() - r1.left(), 4), r1.height())
        else:
            rect = QRect(r1.left(), r1.top(), max(self.viewport().width() - r1.left() - 8, 4), r1.height())
        self.current_rect_changed.emit(rect.intersected(self.viewport().rect()))

    # --- checked / unchecked part ---

    def set_checked_until(self, paragraph: Optional[int]):
        self.checked_until = paragraph
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._doc is None:
            return
        painter = QPainter(self.viewport())
        try:
            self._paint_skipped(painter)
            self._paint_unchecked(painter)
        finally:
            painter.end()

    def _paint_unchecked(self, painter):
        if self.checked_until is None:
            return
        block = self.document().findBlockByNumber(self.checked_until + 1)
        if not block.isValid():
            return
        top = self.document().documentLayout().blockBoundingRect(block).top() - self.verticalScrollBar().value()
        view = self.viewport().rect()
        if top >= view.height():
            return
        top = int(top)
        painter.fillRect(QRect(0, max(top, 0), view.width(), view.height()), _alpha("paper", 170))
        painter.setPen(QColor(COLORS["sky"]))
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        painter.setFont(font)
        if top >= 0:
            painter.drawLine(24, top, view.width() - 24, top)
        painter.drawText(QRect(24, max(top, 0) + 3, view.width() - 48, 20), Qt.AlignRight | Qt.AlignTop,
                         UNCHECKED_LABEL)

    def _paint_skipped(self, painter):
        top = self.cursorForPosition(self.viewport().rect().topLeft()).block()
        bottom = self.cursorForPosition(self.viewport().rect().bottomLeft()).block()
        font = QFont(self.font())
        font.setPointSizeF(8)
        painter.setFont(font)
        painter.setPen(QColor(COLORS["skipped"]))
        block, stop = top, bottom.next()
        cursor = QTextCursor(self.document())
        while block.isValid() and block != stop:
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.charFormat().property(MARK_PROP) == SKIPPED:
                    cursor.setPosition(fragment.position())
                    rect = self.cursorRect(cursor)
                    painter.drawText(rect.left(), rect.top() - 1, SKIPPED_LABEL)
                it += 1
            block = block.next()

    # --- edit mode ---

    def _hit_mark(self, event):
        position = self._position_at(event.pos())
        return self.mark_at(position) if position >= 0 else None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._doc is not None:
            mark_id = self._hit_mark(event)
            if mark_id is not None:
                self.mark_clicked.emit(mark_id)
            elif self._doc.editable and self.isReadOnly():
                self._enter_edit_mode()
        super().mousePressEvent(event)

    def _enter_edit_mode(self):
        self.setReadOnly(False)
        self.setUndoRedoEnabled(True)
        self.edit_mode_changed.emit(True)

    def _leave_edit_mode(self):
        self.flush_edits()
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.edit_mode_changed.emit(False)

    def keyPressEvent(self, event):
        if not self.isReadOnly():
            if event.key() == Qt.Key_Escape:
                self._leave_edit_mode()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.insertPlainText(LINE_SEPARATOR)   # a paragraph stays one block
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        if source.hasText():
            text = source.text().replace("\r\n", "\n").replace("\r", "\n")
            self.insertPlainText(text.replace("\n", LINE_SEPARATOR))

    def _contents_changed(self, position, removed, added):
        if self._writing or self.isReadOnly() or self._doc is None:
            return
        self._dirty.add(self.document().findBlock(position).blockNumber())
        self._timer.start()

    def _block_count_changed(self, count):
        if not self._writing and self._doc is not None and count != len(self._doc.paragraphs):
            QTimer.singleShot(0, self._restore_structure)

    def _restore_structure(self):
        # the reader joined or split paragraphs (e.g. deleted a selection across them): not supported, undo it
        while self.document().blockCount() != len(self._doc.paragraphs) and self.document().isUndoAvailable():
            self.document().undo()
        self._dirty = {n for n in self._dirty if n < self.document().blockCount()}

    def flush_edits(self):
        """Copy the reader's edits into the document model and the session now."""
        self._timer.stop()
        if self._doc is None or self.document().blockCount() != len(self._doc.paragraphs):
            return
        dirty, self._dirty = sorted(self._dirty), set()
        for i in dirty:
            if i >= len(self._doc.paragraphs):
                continue
            block = self.document().findBlockByNumber(i)
            spans = spans_from_block(block)
            self._doc.paragraphs[i].spans = spans
            self._session.replace_paragraph(i, "".join(s.text for s in spans))
            self._strip_marks(block)
            self.paragraph_edited.emit(i)

    def _strip_marks(self, block):
        """Take the mark formatting off a block in place (the reader's cursor stays where it is)."""
        self._writing = True
        try:
            cursor = QTextCursor(self.document())
            it = block.begin()
            ranges = []
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                if fmt.hasProperty(MARK_PROP):
                    ranges.append((fragment.position(), fragment.length(), fmt))
                it += 1
            for position, length, fmt in ranges:
                base = bool(fmt.property(BASE_UNDERLINE_PROP))
                for prop in (MARK_PROP, MARK_ID_PROP, BASE_UNDERLINE_PROP):
                    fmt.clearProperty(prop)
                fmt.clearBackground()
                fmt.setUnderlineStyle(QTextCharFormat.SingleUnderline if base else QTextCharFormat.NoUnderline)
                fmt.setFontUnderline(base)
                cursor.setPosition(position)
                cursor.setPosition(position + length, QTextCursor.KeepAnchor)
                cursor.setCharFormat(fmt)
        finally:
            self._writing = False
