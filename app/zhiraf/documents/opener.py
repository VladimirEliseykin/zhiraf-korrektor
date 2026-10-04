"""Open any supported document into the model and save its corrected copy next to it."""
import os
import shutil

from . import txt_format
from .model import DocumentError, UnsupportedFormat, corrected_path

READERS = {".txt": txt_format.read_txt}
SAVERS = {"txt": txt_format.save_txt}


def open_document(path):
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if reader is None:
        raise UnsupportedFormat("Формат «%s» не поддерживается. Можно открыть .docx, .doc, .odt и .txt."
                                % (ext or "без расширения"))
    if not os.path.exists(path):
        raise DocumentError("Файл не найден: %s" % path)
    return reader(path)


def save_document(doc, replacements, dst=None):
    dst = dst or corrected_path(doc.path, doc.saved_as)
    if doc.path and os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(doc.path)):
        raise DocumentError("Исходный документ не перезаписывается — выберите другое имя.")
    try:
        return SAVERS[doc.kind](doc, replacements, dst)
    except PermissionError:
        raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе."
                            % os.path.basename(dst))


def close_document(doc):
    """Remove temp copies made for this document (a .doc converted to .docx)."""
    source = doc.source if isinstance(doc.source, dict) else {}
    if source.get("tmpdir"):
        shutil.rmtree(source["tmpdir"], ignore_errors=True)
