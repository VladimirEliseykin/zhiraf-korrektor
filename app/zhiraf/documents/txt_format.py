"""Plain text: one line is one paragraph; encoding and line endings are kept on saving."""
import os

from .model import Document, DocumentError, Paragraph, SaveReport, Span, apply_replacements, group_by_paragraph

BOM_UTF8 = b"\xef\xbb\xbf"
BOM_UTF16_LE = b"\xff\xfe"
BOM_UTF16_BE = b"\xfe\xff"


def read_txt(path):
    with open(path, "rb") as f:
        raw = f.read()

    # Detect encoding strictly
    encoding = None
    if raw.startswith(BOM_UTF8):
        encoding = "utf-8-sig"
    elif raw.startswith(BOM_UTF16_LE) or raw.startswith(BOM_UTF16_BE):
        encoding = "utf-16"
    else:
        # Try UTF-8 strictly
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            # Try CP1251 strictly
            try:
                raw.decode("cp1251")
                encoding = "cp1251"
            except UnicodeDecodeError:
                raise DocumentError("Не удалось прочитать «%s»: неизвестная кодировка текста." % os.path.basename(path))

    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        raise DocumentError("Не удалось прочитать «%s»: неизвестная кодировка текста." % os.path.basename(path))

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    doc = Document([Paragraph([Span(line)]) for line in lines], kind="txt", path=path, editable=False, saved_as="txt")
    doc.source = {"encoding": encoding, "newline": newline}
    return doc


def save_txt(doc, replacements, dst):
    groups = group_by_paragraph(replacements)
    lines = [apply_replacements(p.text, groups.get(i, [])) for i, p in enumerate(doc.paragraphs)]

    # Write to temporary file first; whatever goes wrong, no .part is left behind
    part_path = dst + ".part"
    try:
        with open(part_path, "w", encoding=doc.source["encoding"], newline="") as f:
            f.write(doc.source["newline"].join(lines))
        os.replace(part_path, dst)
    except BaseException as e:
        try:
            os.remove(part_path)
        except OSError:
            pass
        if isinstance(e, UnicodeEncodeError):
            raise DocumentError("Исправленный текст содержит символы, которые нельзя сохранить в кодировке исходного файла.")
        raise
    return SaveReport(dst, len(replacements))
