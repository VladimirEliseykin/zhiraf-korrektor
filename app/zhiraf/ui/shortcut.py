"""The offer to put a shortcut on the desktop at the first start of the shipped program."""
import os
import sys

from PySide2.QtWidgets import QMessageBox

from .. import ROOT

LAUNCHER_NAME = "Жираф.Корректор.exe"
LINK_NAME = "Жираф.Корректор.lnk"
QUESTION = "Создать ярлык «Жираф.Корректор» на рабочем столе?"
FAILED = "Не удалось создать ярлык: рабочий стол недоступен."
CSIDL_DESKTOPDIRECTORY = 0x10
MAX_PATH = 260


def launcher_path():
    """The launcher of the shipped folder; None in development and off Windows (no offer there)."""
    path = os.path.join(ROOT, LAUNCHER_NAME)
    return path if sys.platform == "win32" and os.path.isfile(path) else None


def desktop_dir():
    """The user's desktop folder, or None when Windows cannot tell."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) != 0:
            return None
        return buf.value or None
    except (AttributeError, OSError, ValueError):
        return None


def create_desktop_shortcut(target, desktop):
    """Write <desktop>\\Жираф.Корректор.lnk pointing at target; OSError on any failure."""
    link = os.path.join(desktop, LINK_NAME)
    try:
        from comtypes.client import CreateObject
        from comtypes.persist import IPersistFile
        from comtypes.shelllink import ShellLink
        shell_link = CreateObject(ShellLink)
        shell_link.SetPath(target)
        shell_link.SetWorkingDirectory(os.path.dirname(target))
        shell_link.SetIconLocation(target, 0)
        shell_link.QueryInterface(IPersistFile).Save(link, True)
    except OSError:
        raise
    except Exception as exc:   # COM errors are not OSError subclasses everywhere
        raise OSError(str(exc))
    return link


def _ask_in_window(window):
    return window._say("question", QUESTION, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


def offer_shortcut(window, settings, ask=None, create=create_desktop_shortcut):
    """Ask once whether to create the desktop shortcut; any answer is remembered and the question never repeats."""
    target = launcher_path()
    if target is None or settings["shortcut_offered"]:
        return
    desktop = desktop_dir()
    if desktop is not None and os.path.exists(os.path.join(desktop, LINK_NAME)):
        _remember(settings)   # already there: nothing to ask, nothing to overwrite
        return
    try:
        agreed = (ask or _ask_in_window)(window)
    except RuntimeError:
        return   # the window is gone before the answer: ask again next time
    _remember(settings)
    if not agreed:
        return
    try:
        if desktop is None:
            raise OSError("no desktop")
        create(target, desktop)
    except OSError:
        try:
            window._notify(FAILED, kind="shortcut")
        except RuntimeError:
            pass   # window closed meanwhile


def _remember(settings):
    try:
        settings.set("shortcut_offered", True)
    except OSError:
        pass
