"""Word 97-2003 .doc.

With Word or LibreOffice on the computer a .doc is converted to .docx and back (task 9), keeping all
formatting. Without them only the text can be read: extract_doc_text follows the piece table of the
binary format ([MS-DOC]: FIB -> Clx -> PlcPcd) and keeps the visible text of the main document.
"""
import os
import struct

import olefile

from .model import DocumentError

FIB_WIDENT, FIB_FLAGS, FIB_CCP_TEXT, FIB_FC_CLX = 0x0000, 0x000A, 0x004C, 0x01A2
WIDENT_WORD97 = 0xA5EC
FLAG_ENCRYPTED, FLAG_TABLE1 = 0x0100, 0x0200
FIELD_BEGIN, FIELD_SEPARATE, FIELD_END = "\x13", "\x14", "\x15"
PARAGRAPH_ENDS = {"\r", "\x07", "\x0c"}         # paragraph, table cell / row, page or section break
DROPPED = {"\x01", "\x02", "\x08", "\x1f", "\x05"}  # picture, footnote mark, drawing, soft hyphen, comment
REPLACED = {"\x0b": "\n", "\x1e": "-", "\xa0": "\xa0"}


def _fail(path, why):
    return DocumentError("Не удалось открыть «%s»: %s." % (os.path.basename(path), why))


def _streams(path):
    ole = olefile.OleFileIO(path)
    try:
        if not ole.exists("WordDocument"):
            raise _fail(path, "это не документ Word")
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, FIB_FLAGS)[0]
        if flags & FLAG_ENCRYPTED:
            raise _fail(path, "документ защищён паролем")
        name = "1Table" if flags & FLAG_TABLE1 else "0Table"
        if not ole.exists(name):
            raise _fail(path, "файл повреждён")
        return word, ole.openstream(name).read()
    finally:
        ole.close()


def _pieces(word, clx, path):
    i = 0
    while i < len(clx) and clx[i] == 0x01:             # Prc: direct formatting, skipped
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise _fail(path, "не удалось найти текст документа")
    size = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + size]
    n = (size - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        count = cps[k + 1] - cps[k]
        if fc & 0x40000000:                            # 8-bit (cp1252) piece
            start = (fc & 0x3FFFFFFF) // 2
            yield word[start:start + count].decode("cp1252", "replace")
        else:                                          # UTF-16 piece: Cyrillic text lives here
            yield word[fc:fc + 2 * count].decode("utf-16-le", "replace")


def _paragraphs(text):
    paragraphs, current, fields = [], [], []           # fields: "code" or "result" per open field
    for ch in text:
        if ch == FIELD_BEGIN:
            fields.append("code")
        elif ch == FIELD_SEPARATE:
            if fields:
                fields[-1] = "result"
        elif ch == FIELD_END:
            if fields:
                fields.pop()
        elif "code" in fields or ch in DROPPED:
            continue
        elif ch in PARAGRAPH_ENDS:
            paragraphs.append("".join(current))
            current = []
        else:
            current.append(REPLACED.get(ch, ch))
    if current:
        paragraphs.append("".join(current))
    return paragraphs


def extract_doc_text(path):
    try:
        word, table = _streams(path)
        wident = struct.unpack_from("<H", word, FIB_WIDENT)[0]
        if wident != WIDENT_WORD97:
            raise _fail(path, "это не документ Word 97–2003")
        ccp_text = struct.unpack_from("<i", word, FIB_CCP_TEXT)[0]
        if ccp_text < 0:
            raise _fail(path, "файл повреждён")
        fc_clx, lcb_clx = struct.unpack_from("<II", word, FIB_FC_CLX)
        if fc_clx + lcb_clx > len(table):
            raise _fail(path, "файл повреждён")
        text = "".join(_pieces(word, table[fc_clx:fc_clx + lcb_clx], path))
        return _paragraphs(text[:ccp_text])                # main document only: no headers, footnotes
    except DocumentError:
        raise
    except MemoryError:
        raise
    except Exception:
        raise _fail(path, "файл повреждён")
