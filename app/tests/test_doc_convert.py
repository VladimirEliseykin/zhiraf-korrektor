import os
import shutil

import pytest
from conftest import SOFFICE, needs_soffice
from docfactory import P, R, make_docx
from test_doc_text import to_doc
from zhiraf import storage
from zhiraf.documents import doc_format, opener
from zhiraf.documents.docx_format import read_docx
from zhiraf.documents.model import DocumentError, Replacement


@needs_soffice
def test_doc_round_trip_through_libreoffice(tmp_path):
    src = to_doc(make_docx(tmp_path / "Приказ.docx", P(R("Так же был ограничен размер."))), tmp_path)
    doc = doc_format.open_doc(src, converter=doc_format.LibreOffice(SOFFICE))
    assert doc.kind == "doc" and doc.saved_as == "doc" and doc.notice is None
    assert doc.paragraphs[0].text == "Так же был ограничен размер."
    report = opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith("Приказ (исправлено).doc") and report.applied == 1
    assert "Также был ограничен размер." in doc_format.extract_doc_text(report.path)
    tmpdir = doc.source["tmpdir"]
    opener.close_document(doc)
    assert not os.path.exists(tmpdir)


@needs_soffice
def test_without_office_text_is_saved_as_docx(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Так же был"))), tmp_path)
    doc = doc_format.open_doc(src, converter=None)
    assert doc.saved_as == "docx" and "как .docx" in doc.notice
    report = opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert report.path.endswith(".docx")
    assert read_docx(report.path).paragraphs[0].text == "Также был"


class FailingConverter:
    name = "Сломанный"

    def to_docx(self, src, outdir):
        raise doc_format.ConversionError("timeout")


@needs_soffice
def test_failed_conversion_gives_message_and_cleans_temp(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Текст"))), tmp_path)
    with pytest.raises(DocumentError) as e:
        doc_format.open_doc(src, converter=FailingConverter())
    assert "a.doc" in str(e.value)
    assert os.listdir(storage.tmp_dir()) == []


def test_find_converter_uses_libreoffice_on_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/opt/lo/soffice" if name == "soffice" else None)
    found = doc_format.find_converter()
    assert isinstance(found, doc_format.LibreOffice) and found.soffice == "/opt/lo/soffice"


def test_find_converter_none_without_office(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(doc_format, "_word_installed", lambda: False)
    monkeypatch.setattr(doc_format, "_installed_soffice", lambda: None)
    assert doc_format.find_converter() is None


# controller requirements on top of the brief

class FailingSaver:
    name = "Сломанный"

    def to_doc(self, src_docx, dst):
        raise doc_format.ConversionError("boom")


@needs_soffice
def test_failed_save_keeps_document_usable_and_leaves_no_extra_temp(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Так же был"))), tmp_path)
    doc = doc_format.open_doc(src, converter=doc_format.LibreOffice(SOFFICE))
    doc.source["converter"] = FailingSaver()
    with pytest.raises(DocumentError) as e:
        opener.save_document(doc, [Replacement(0, 0, 6, "Также")])
    assert "a (исправлено).doc" in str(e.value)
    assert os.listdir(storage.tmp_dir()) == [os.path.basename(doc.source["tmpdir"])]
    assert os.listdir(doc.source["tmpdir"]) == [os.path.basename(doc.source["docx"])]
    opener.close_document(doc)
    assert os.listdir(storage.tmp_dir()) == []


@needs_soffice
def test_text_only_never_writes_doc_extension(tmp_path):
    src = to_doc(make_docx(tmp_path / "a.docx", P(R("Так же был"))), tmp_path)
    doc = doc_format.open_doc(src, converter=None)
    report = doc_format.save_doc(doc, [Replacement(0, 0, 6, "Также")], str(tmp_path / "out.doc"))
    assert report.path.endswith("out.docx") and os.path.exists(report.path)
    assert not os.path.exists(str(tmp_path / "out.doc"))


def test_word_not_used_off_windows():
    assert doc_format._word_installed() is False


# Word through a fake comtypes (Word itself is never started)

class FakeDocument:
    def __init__(self, log, fail):  # no SaveAs2 attribute: the code must fall back to SaveAs (Word 2007)
        self.log, self.fail = log, fail

    def SaveAs(self, path, file_format):
        self.log.append(("SaveAs", file_format))
        with open(path, "wb") as f:
            f.write(b"partial")
        if self.fail:
            raise RuntimeError("disk full")

    def Close(self, save):
        self.log.append(("Close", save))


class FakeDocuments:
    def __init__(self, word):
        self.word = word

    def Open(self, **kwargs):
        self.word.log.append(("Open", kwargs, self.word.__dict__.get("AutomationSecurity")))
        return FakeDocument(self.word.log, self.word.fail)


class FakeWord:
    def __init__(self, log, fail):
        self.log, self.fail = log, fail
        self.Documents = FakeDocuments(self)

    def Quit(self):
        self.log.append(("Quit",))


@pytest.fixture
def fake_word(monkeypatch):
    import sys
    import types
    state = types.SimpleNamespace(log=[], fail=False)
    client = types.ModuleType("comtypes.client")
    client.CreateObject = lambda name: FakeWord(state.log, state.fail)
    com = types.ModuleType("comtypes")
    com.client = client
    com.CoInitialize = lambda: state.log.append(("CoInitialize",))
    com.CoUninitialize = lambda: state.log.append(("CoUninitialize",))
    monkeypatch.setitem(sys.modules, "comtypes", com)
    monkeypatch.setitem(sys.modules, "comtypes.client", client)
    return state


def test_word_to_doc_is_safe(tmp_path, fake_word):
    src, dst = tmp_path / "in.docx", tmp_path / "out.doc"
    src.write_bytes(b"x")
    doc_format.Word().to_doc(str(src), str(dst))
    names = [e[0] for e in fake_word.log]
    assert names == ["CoInitialize", "Open", "SaveAs", "Close", "Quit", "CoUninitialize"]
    opened = fake_word.log[1]
    assert opened[2] == 3                                   # macros disabled before Open
    kw = opened[1]
    assert kw["ReadOnly"] is True and kw["AddToRecentFiles"] is False and kw["ConfirmConversions"] is False
    assert kw["PasswordDocument"] and kw["PasswordDocument"] == kw["WritePasswordDocument"]
    assert fake_word.log[2] == ("SaveAs", doc_format.WD_FORMAT_DOC)  # SaveAs2 missing: Word 2007 fallback
    assert dst.read_bytes() == b"partial" and not os.path.exists(str(dst) + ".part")
    assert os.listdir(storage.tmp_dir()) == []


def test_word_failed_save_leaves_no_partial_file(tmp_path, fake_word):
    fake_word.fail = True
    src, dst = tmp_path / "in.docx", tmp_path / "out.doc"
    src.write_bytes(b"x")
    with pytest.raises(doc_format.ConversionError):
        doc_format.Word().to_doc(str(src), str(dst))
    names = [e[0] for e in fake_word.log]
    assert names[-3:] == ["Close", "Quit", "CoUninitialize"]
    assert not dst.exists() and not os.path.exists(str(dst) + ".part")
    assert os.listdir(storage.tmp_dir()) == []


def test_word_to_docx_uses_xml_document_format(tmp_path, fake_word):
    src = tmp_path / "in.doc"
    src.write_bytes(b"x")
    out = doc_format.Word().to_docx(str(src), str(tmp_path))
    assert out.endswith("in.docx") and os.path.exists(out)
    assert fake_word.log[2] == ("SaveAs", 12)
    assert os.listdir(storage.tmp_dir()) == []


@needs_soffice
def test_libreoffice_to_doc_replaces_existing_destination(tmp_path):
    docx = make_docx(tmp_path / "a.docx", P(R("Текст")))
    dst = tmp_path / "out.doc"
    dst.write_bytes(b"old")
    doc_format.LibreOffice(SOFFICE).to_doc(str(docx), str(dst))
    assert dst.read_bytes()[:4] == b"\xd0\xcf\x11\xe0" and not os.path.exists(str(dst) + ".part")
    assert os.listdir(storage.tmp_dir()) == []
