"""Open any supported document into the model and save its corrected copy next to it."""
import os
import shutil

from . import doc_format, docx_format, odt_format, txt_format
from .model import DocumentError, UnsupportedFormat, corrected_path

READERS = {".txt": txt_format.read_txt, ".docx": docx_format.read_docx, ".odt": odt_format.read_odt,
           ".doc": doc_format.open_doc}
SAVERS = {"txt": txt_format.save_txt, "docx": docx_format.save_docx, "odt": odt_format.save_odt,
          "doc": doc_format.save_doc}


def open_document(path):
    ext = os.path.splitext(path)[1].lower()
    reader = READERS.get(ext)
    if reader is None:
        raise UnsupportedFormat("Формат «%s» не поддерживается. Можно открыть .docx, .doc, .odt и .txt."
                                % (ext or "без расширения"))
    if not os.path.exists(path):
        raise DocumentError("Файл не найден: %s" % path)
    name = os.path.basename(path)
    try:
        return reader(path)
    except DocumentError:
        raise
    except OSError:
        raise DocumentError("Не удалось открыть «%s»: нет доступа или файл занят другой программой." % name)
    except MemoryError:
        raise DocumentError("Не хватило памяти, чтобы открыть «%s»." % name)
    except Exception:  # lxml, RecursionError... never carry document text or a traceback to the window
        raise DocumentError("Не удалось открыть «%s»: файл повреждён." % name)


def save_document(doc, replacements, dst=None):
    if not dst and not doc.path:
        raise DocumentError("Укажите, куда сохранить документ.")
    saver = SAVERS.get(doc.kind)
    if saver is None:
        raise DocumentError("Формат документа «%s» не поддерживается для сохранения." % doc.kind)
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
    name = os.path.basename(dst)
    try:
        return saver(doc, replacements, dst)
    except DocumentError:
        raise
    except OSError:
        raise DocumentError("Не удалось сохранить «%s»: нет доступа или файл открыт в другой программе." % name)
    except MemoryError:
        raise DocumentError("Не хватило памяти, чтобы сохранить «%s»." % name)
    except Exception:
        raise DocumentError("Не удалось сохранить «%s»." % name)


def close_document(doc):
    """Remove temp copies made for this document (a .doc converted to .docx)."""
    source = doc.source if isinstance(doc.source, dict) else {}
    if source.get("tmpdir"):
        shutil.rmtree(source["tmpdir"], ignore_errors=True)
