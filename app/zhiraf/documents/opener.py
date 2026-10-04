"""Open any supported document into the model and save its corrected copy next to it."""
import os
import shutil

from . import docx_format, txt_format
from .model import DocumentError, UnsupportedFormat, corrected_path

READERS = {".txt": txt_format.read_txt, ".docx": docx_format.read_docx}
SAVERS = {"txt": txt_format.save_txt, "docx": docx_format.save_docx}


def open_document(path):
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if reader is None:
        raise UnsupportedFormat("Формат «%s» не поддерживается. Можно открыть .docx, .doc, .odt и .txt."
                                % (ext or "без расширения"))
    if not os.path.exists(path):
        raise DocumentError("Файл не найден: %s" % path)
    try:
        return reader(path)
    except DocumentError:
        raise
    except OSError:
        raise DocumentError("Не удалось открыть «%s»: нет доступа или файл занят другой программой." % os.path.basename(path))


def save_document(doc, replacements, dst=None):
    dst = dst or corrected_path(doc.path, doc.saved_as)
    if doc.path and os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(doc.path)):
        raise DocumentError("Исходный документ не перезаписывается — выберите другое имя.")
    # Check if dst exists and is the same file as doc.path
    if dst and os.path.exists(dst) and doc.path and os.path.exists(doc.path):
        try:
            if os.path.samefile(dst, doc.path):
                raise DocumentError("Исходный документ не перезаписывается — выберите другое имя.")
        except OSError:
            pass
    try:
        return SAVERS[doc.kind](doc, replacements, dst)
    except DocumentError:
        raise
    except OSError:
        raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе."
                            % os.path.basename(dst))


def close_document(doc):
    """Remove temp copies made for this document (a .doc converted to .docx)."""
    source = doc.source if isinstance(doc.source, dict) else {}
    if source.get("tmpdir"):
        shutil.rmtree(source["tmpdir"], ignore_errors=True)
