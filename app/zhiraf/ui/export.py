"""Save the corrected document in any format and copy it out with formatting."""
import os

from PySide2.QtGui import QFont, QTextCursor, QTextCharFormat, QTextDocument, QTextDocumentWriter, QPageSize
from PySide2.QtPrintSupport import QPrinter

from ..documents.docx_format import text_runs_xml, write_docx_package
from ..documents.model import DocumentError, SaveReport
from ..documents.opener import save_document
from .clipboard import copy_to_clipboard
from .runs import final_paragraphs

FORMATS = [("Документ Word (*.docx)", "docx"), ("Документ ODF (*.odt)", "odt"), ("PDF (*.pdf)", "pdf"),
           ("Текст (*.txt)", "txt")]

_HEADING_SIZE = {"title": 20, "h1": 18, "h2": 16, "h3": 14}  # points; body text is 11


def _unsupported(ext):
    return DocumentError("Формат «%s» не поддерживается. Можно сохранить как .docx, .odt, .pdf или .txt."
                         % (("." + ext) if ext else "без расширения"))


def _same_file(a, b):
    if os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
        return True
    try:
        return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return False


def _check_not_source(doc, dst):
    if doc.path and _same_file(dst, doc.path):
        raise DocumentError("Исходный документ не перезаписывается — выберите другое имя.")


def save_corrected_copy(doc, session, dst=None):
    if not dst and not doc.path:
        raise DocumentError("Укажите, куда сохранить документ.")
    return save_document(doc, session.replacements(), dst)


def save_as(doc, session, dst):
    _check_not_source(doc, dst)
    ext = os.path.splitext(dst)[1].lower().lstrip(".")
    if ext not in [e for _, e in FORMATS]:
        raise _unsupported(ext)
    if doc.path and ext == doc.saved_as:
        return save_document(doc, session.replacements(), dst)
    return export_paragraphs(final_paragraphs(doc, session), dst)


def needs_overwrite_confirmation(dst, doc):
    return os.path.exists(dst) and not (doc.path and _same_file(dst, doc.path))


def copy_corrected(doc, session, clipboard):
    copy_to_clipboard(final_paragraphs(doc, session), clipboard)


def _shown_text(p):
    return ("• " if p.style == "list" else "") + p.text


def _docx_body(paragraphs):
    out = []
    for p in paragraphs:
        size = _HEADING_SIZE.get(p.style)
        runs = []
        if p.style == "list":
            runs.append(text_runs_xml("• "))
        for s in p.spans:
            props = ""
            if s.bold or size:
                props += "<w:b/>"
            if s.italic:
                props += "<w:i/>"
            if s.underline:
                props += '<w:u w:val="single"/>'
            if size:
                props += '<w:sz w:val="%d"/>' % (size * 2)
            runs.append(text_runs_xml(s.text, props))
        out.append("<w:p>%s</w:p>" % "".join(runs))
    return "".join(out)


def _qtext_document(paragraphs):
    qdoc = QTextDocument()
    qdoc.setDefaultFont(QFont("Arial", 11))
    cursor = QTextCursor(qdoc)
    for i, p in enumerate(paragraphs):
        if i:
            cursor.insertBlock()
        size = _HEADING_SIZE.get(p.style)
        pieces = ([("• ", False, False, False)] if p.style == "list" else [])
        pieces += [(s.text, s.bold, s.italic, s.underline) for s in p.spans]
        for text, bold, italic, underline in pieces:
            fmt = QTextCharFormat()
            fmt.setFontWeight(QFont.Bold if (bold or size) else QFont.Normal)
            fmt.setFontItalic(italic)
            fmt.setFontUnderline(underline)
            if size:
                fmt.setFontPointSize(size)
            cursor.insertText(text, fmt)
    return qdoc


def _write_txt(paragraphs, part):
    with open(part, "wb") as f:
        f.write("\r\n".join(_shown_text(p) for p in paragraphs).encode("utf-8-sig"))


def _write_docx(paragraphs, part):
    write_docx_package(part, _docx_body(paragraphs))


def _write_odt(paragraphs, part):
    if not QTextDocumentWriter(part, b"ODF").write(_qtext_document(paragraphs)):
        raise OSError("odt write failed")


def _write_pdf(paragraphs, part):
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setPageSize(QPageSize(QPageSize.A4))
    printer.setOutputFileName(part)
    _qtext_document(paragraphs).print_(printer)
    if not os.path.exists(part) or os.path.getsize(part) == 0:
        raise OSError("pdf write failed")


_WRITERS = {"docx": _write_docx, "odt": _write_odt, "pdf": _write_pdf, "txt": _write_txt}


def export_paragraphs(paragraphs, dst):
    ext = os.path.splitext(dst)[1].lower().lstrip(".")
    writer = _WRITERS.get(ext)
    if writer is None:
        raise _unsupported(ext)
    name = os.path.basename(dst)
    part = dst + ".part"
    try:
        writer(paragraphs, part)
        os.replace(part, dst)
    except BaseException as e:
        try:
            if os.path.exists(part):
                os.remove(part)
        except OSError:
            pass
        if isinstance(e, DocumentError) or not isinstance(e, Exception):
            raise
        if isinstance(e, OSError):
            raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе." % name)
        if isinstance(e, MemoryError):
            raise DocumentError("Не хватило памяти, чтобы сохранить «%s»." % name)
        raise DocumentError("Не удалось сохранить «%s»." % name)
    return SaveReport(dst, len(paragraphs))
