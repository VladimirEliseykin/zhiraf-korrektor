"""Zip packages (.docx, .odt): rewrite changed parts, copy every other part as it was."""
import os
import zipfile

from .model import DocumentError


def read_package(path):
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            return infos, {i.filename: z.read(i.filename) for i in infos}
    except (zipfile.BadZipFile, OSError):
        raise DocumentError("Не удалось прочитать «%s»: файл повреждён или занят." % os.path.basename(path))


def write_package(dst, infos, blobs):
    """Same entries in the same order with the same compression (ODF needs 'mimetype' first, stored)."""
    tmp = dst + ".part"
    try:
        with zipfile.ZipFile(tmp, "w") as z:
            for info in infos:
                z.writestr(info, blobs[info.filename])
        os.replace(tmp, dst)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
