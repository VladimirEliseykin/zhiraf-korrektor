import os
import shutil
import struct
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LAUNCHER_C = os.path.join(ROOT, "build", "launcher", "launcher.c")
LOGO = os.path.join(ROOT, "app", "zhiraf", "ui", "art", "logo.png")
CACHE = os.path.expanduser("~/vm/win7/dist-cache")
TOOLCHAIN = os.path.join(CACHE, "toolchain")

needs_toolchain = pytest.mark.skipif(
    not os.path.isfile(os.path.join(TOOLCHAIN, "bin", "x86_64-w64-mingw32-clang")),
    reason="llvm-mingw is not unpacked in the dist cache")

SIZES = (16, 24, 32, 48, 64, 128, 256)


@pytest.fixture(scope="module")
def qapp():
    # a QApplication, never a bare QGuiApplication: later tests/ui tests need the widgets one
    from PySide2.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_make_icon_has_seven_sizes(tmp_path, qapp):
    from PySide2.QtGui import QImageReader
    from build.icon import make_icon
    ico = str(tmp_path / "z.ico")
    make_icon(LOGO, ico)
    reader = QImageReader(ico)
    assert reader.imageCount() == len(SIZES)
    got = []
    for i in range(reader.imageCount()):
        reader.jumpToImage(i)
        got.append(reader.size().width())
    assert sorted(got) == list(SIZES)
    # the ICO directory itself must agree with the Qt reader
    data = open(ico, "rb").read()
    assert struct.unpack("<HHH", data[:6]) == (0, 1, len(SIZES))


# ---- args_after_program, compiled with host clang from the shipped source ----

CASES = [
    (r'"C:\x\Жираф.Корректор.exe"', ""),
    (r'"C:\x y\Ж.exe" "C:\Мои документы\отчёт 2.docx"', r'"C:\Мои документы\отчёт 2.docx"'),
    (r'C:\x\Ж.exe a b', "a b"),
    (r'"C:\x\Ж.exe"  "a"', '"a"'),
    (r'C:\x\Ж.exe', ""),
    (r'"C:\x\Ж.exe"   ', ""),
    ("C:\\x\\\u0416.exe\ta", "a"),
]


@pytest.fixture(scope="module")
def parser_bin(tmp_path_factory):
    clang = shutil.which("clang")
    if clang is None:
        pytest.skip("host clang is not installed")
    out = str(tmp_path_factory.mktemp("lt") / "args_test")
    r = subprocess.run([clang, "-DLAUNCHER_TEST", "-Wall", "-Werror", "-o", out, LAUNCHER_C],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return out


def test_args_after_program(parser_bin):
    stdin = "".join(c + "\n" for c, _ in CASES)
    r = subprocess.run([parser_bin], input=stdin.encode("utf-8"), capture_output=True, timeout=30)
    assert r.returncode == 0
    lines = r.stdout.decode("utf-8").split("\n")[:len(CASES)]
    assert lines == [want for _, want in CASES]


# ---- the built exe ----

def _rva_to_off(sections, rva):
    for va, vsize, raw in sections:
        if va <= rva < va + max(vsize, 1):
            return rva - va + raw
    raise ValueError("rva outside sections: %x" % rva)


def parse_pe(path):
    d = open(path, "rb").read()
    assert d[:2] == b"MZ"
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    assert d[pe:pe + 4] == b"PE\0\0"
    machine, nsec, _, _, _, optsz, _ = struct.unpack_from("<HHIIIHH", d, pe + 4)
    opt = pe + 24
    magic = struct.unpack_from("<H", d, opt)[0]
    assert magic == 0x20B  # PE32+
    subsystem = struct.unpack_from("<H", d, opt + 68)[0]
    ddir = opt + 112
    dirs = [struct.unpack_from("<II", d, ddir + 8 * i) for i in range(16)]
    sec0 = opt + optsz
    sections = []
    for i in range(nsec):
        _, vsize, va, rawsize, raw = struct.unpack_from("<8sIIII", d, sec0 + 40 * i)
        sections.append((va, vsize, raw))
    # imports
    imports = []
    rva, size = dirs[1]
    if rva:
        off = _rva_to_off(sections, rva)
        while True:
            fields = struct.unpack_from("<IIIII", d, off)
            if not any(fields):
                break
            noff = _rva_to_off(sections, fields[3])
            imports.append(d[noff:d.index(b"\0", noff)].decode("ascii"))
            off += 20
    # resource top-level type ids
    types = []
    rrva, _ = dirs[2]
    if rrva:
        base = _rva_to_off(sections, rrva)
        named, ids = struct.unpack_from("<HH", d, base + 12)
        for i in range(named + ids):
            name, _off = struct.unpack_from("<II", d, base + 16 + 8 * i)
            if i >= named:
                types.append(name)
    return {"machine": machine, "subsystem": subsystem, "imports": imports, "res_types": types}


@pytest.fixture(scope="module")
def built(tmp_path_factory, qapp):
    from build.icon import make_icon
    from build.make_launcher import make_launcher
    tmp = tmp_path_factory.mktemp("exe")
    ico = str(tmp / "zhiraf.ico")
    make_icon(LOGO, ico)
    exe = str(tmp / "Жираф.Корректор.exe")
    make_launcher(TOOLCHAIN, exe, ico)
    return exe


@needs_toolchain
def test_exe_pe_properties(built):
    pe = parse_pe(built)
    assert pe["machine"] == 0x8664
    assert pe["subsystem"] == 2
    assert 14 in pe["res_types"]  # RT_GROUP_ICON
    assert 16 in pe["res_types"]  # RT_VERSION
    assert {i.upper() for i in pe["imports"]} <= {"KERNEL32.DLL", "USER32.DLL"}
    assert {i.upper() for i in pe["imports"]} == {"KERNEL32.DLL", "USER32.DLL"}
    for name in pe["imports"]:
        assert not name.lower().startswith("api-ms-win-crt") and name.lower() != "msvcrt.dll"
