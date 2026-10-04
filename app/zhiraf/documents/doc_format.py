"""Word 97-2003 .doc.

With Word or LibreOffice on the computer a .doc is converted to .docx and back (task 9), keeping all
formatting. Without them only the text can be read: extract_doc_text follows the piece table of the
binary format ([MS-DOC]: FIB -> Clx -> PlcPcd) and keeps the visible text of the main document.
"""
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

import olefile

from .. import storage
from .docx_format import plain_paragraphs_xml, read_docx, save_docx, write_docx_package
from .model import Document, DocumentError, Paragraph, SaveReport, Span, apply_replacements, group_by_paragraph

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


NO_OFFICE_NOTICE = ("На компьютере нет Word и LibreOffice: оформление этого .doc сохранить не получится, "
                    "исправленная версия будет сохранена как .docx.")
WD_FORMAT_DOC, WD_FORMAT_DOCX = 0, 12   # wdFormatDocument, wdFormatXMLDocument (also valid in Word 2007)
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3
DUMMY_PASSWORD = "zhiraf-dummy-password"  # makes Word fail on a protected file instead of asking for a password


class ConversionError(Exception):
    pass


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def _safe_move(src, dst):
    """Put src at dst so that dst is either complete or untouched (also across volumes, also over an existing file)."""
    part = dst + ".part"
    try:
        shutil.copyfile(src, part)
        os.replace(part, dst)
    finally:
        if os.path.exists(part):
            os.remove(part)
    os.remove(src)


class LibreOffice:
    name = "LibreOffice"

    def __init__(self, soffice):
        self.soffice = soffice

    def _convert(self, src, target, outdir):
        profile = tempfile.mkdtemp(dir=storage.tmp_dir())  # never touch a LibreOffice the user has open
        cmd = [self.soffice, "--headless", "--norestore", "--nologo",
               "-env:UserInstallation=" + pathlib.Path(profile).as_uri(), "--convert-to", target, "--outdir", outdir, src]
        try:
            subprocess.run(cmd, check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **_no_window())
        except (subprocess.SubprocessError, OSError) as e:
            raise ConversionError(type(e).__name__)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + "." + target.split(":")[0])
        if not os.path.exists(out):
            raise ConversionError("no output")
        return out

    def to_docx(self, src, outdir):
        return self._convert(src, "docx", outdir)

    def to_doc(self, src_docx, dst):
        outdir = tempfile.mkdtemp(dir=storage.tmp_dir())
        try:
            _safe_move(self._convert(src_docx, "doc:MS Word 97", outdir), dst)
        finally:
            shutil.rmtree(outdir, ignore_errors=True)


class Word:
    """Microsoft Word through COM, invisible to the user."""
    name = "Microsoft Word"

    def _com_save(self, src, produced, file_format):
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()  # the GUI may convert from a worker thread
        except Exception as e:  # COM errors are many and version-specific
            raise ConversionError(type(e).__name__)
        try:
            try:
                word = comtypes.client.CreateObject("Word.Application")
            except Exception as e:
                raise ConversionError(type(e).__name__)
            try:
                word.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE  # no macros of a secret document
                word.Visible = False
                word.DisplayAlerts = 0
                document = word.Documents.Open(
                    FileName=os.path.abspath(src), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False,
                    PasswordDocument=DUMMY_PASSWORD, WritePasswordDocument=DUMMY_PASSWORD)
                try:
                    try:
                        document.SaveAs2(produced, file_format)
                    except AttributeError:
                        document.SaveAs(produced, file_format)  # Word 2007
                finally:
                    try:
                        document.Close(False)
                    except Exception:
                        pass
            except ConversionError:
                raise
            except Exception as e:
                raise ConversionError(type(e).__name__)
            finally:
                try:
                    word.Quit()
                except Exception:
                    pass
        finally:
            comtypes.CoUninitialize()

    def _save_as(self, src, dst, file_format):
        work = tempfile.mkdtemp(dir=storage.tmp_dir())  # a failed SaveAs must not leave a partial file at dst
        try:
            produced = os.path.join(work, os.path.basename(dst))
            self._com_save(src, produced, file_format)
            if not os.path.exists(produced):
                raise ConversionError("no output")
            _safe_move(produced, dst)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def to_docx(self, src, outdir):
        dst = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".docx")
        self._save_as(src, dst, WD_FORMAT_DOCX)
        return dst

    def to_doc(self, src_docx, dst):
        self._save_as(src_docx, dst, WD_FORMAT_DOC)


def _word_installed():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        return True
    except OSError:
        return False


def _installed_soffice():
    if sys.platform != "win32":
        return None
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramW6432")):
        for folder in ("LibreOffice", "LibreOffice 7", "LibreOffice 6", "OpenOffice 4", "OpenOffice.org 3"):
            exe = os.path.join(base or "", folder, "program", "soffice.exe")
            if base and os.path.exists(exe):
                return exe
    return None


def find_converter():
    """Word first (best fidelity), then LibreOffice; None when neither is installed."""
    if _word_installed():
        return Word()
    soffice = shutil.which("soffice") or _installed_soffice()
    return LibreOffice(soffice) if soffice else None


def open_doc(path, converter="auto"):
    if converter == "auto":
        converter = find_converter()
    if converter is None:
        texts = extract_doc_text(path)
        doc = Document([Paragraph([Span(t)]) for t in texts], kind="doc", path=path, editable=False,
                       saved_as="docx", notice=NO_OFFICE_NOTICE)
        doc.source = {"text_only": True}
        return doc
    tmpdir = tempfile.mkdtemp(dir=storage.tmp_dir())
    try:
        docx = converter.to_docx(path, tmpdir)
        inner = read_docx(docx)
    except (ConversionError, DocumentError):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise DocumentError("Не удалось открыть «%s» через %s. Попробуйте пересохранить его как .docx."
                            % (os.path.basename(path), converter.name))
    except BaseException:  # OSError, Ctrl+C...: the temp copy of a secret document must not stay
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    doc = Document(inner.paragraphs, kind="doc", path=path, editable=False, saved_as="doc")
    doc.source = {"docx": docx, "converter": converter, "tmpdir": tmpdir}
    return doc


def save_doc(doc, replacements, dst):
    if doc.source.get("text_only"):
        groups = group_by_paragraph(replacements)
        texts = [apply_replacements(p.text, groups.get(i, [])) for i, p in enumerate(doc.paragraphs)]
        if not dst.lower().endswith(".docx"):
            dst = os.path.splitext(dst)[0] + ".docx"  # never a file named .doc without a real .doc inside
        part = dst + ".part"
        try:
            write_docx_package(part, plain_paragraphs_xml(texts))
            os.replace(part, dst)
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        return SaveReport(dst, len(replacements))
    inner = Document(doc.paragraphs, kind="docx", path=doc.source["docx"])
    fixed = os.path.join(doc.source["tmpdir"], "исправлено.docx")
    try:
        report = save_docx(inner, replacements, fixed)
        if dst.lower().endswith(".docx"):
            shutil.copyfile(fixed, dst)
        else:
            try:
                doc.source["converter"].to_doc(fixed, dst)
            except ConversionError:
                raise DocumentError("Не удалось сохранить «%s» через %s. Сохраните как .docx."
                                    % (os.path.basename(dst), doc.source["converter"].name))
    finally:
        if os.path.exists(fixed):
            os.remove(fixed)
    return SaveReport(dst, report.applied, report.skipped)
