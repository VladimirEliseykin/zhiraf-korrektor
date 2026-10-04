"""What the program remembers in the user's profile: dictionary, settings, recent documents, temp files.

Never document text: the dictionary holds single words, the recent list file paths and counters.
"""
import json
import os
import shutil
import sys
import time

APP_NAME = "Жираф.Корректор"
DEFAULT_SETTINGS = {"show_checks": True, "strict_mode": False, "remember_recent": True}
MAX_RECENT = 20


def _base(kind):
    override = os.environ.get("ZHIRAF_HOME")
    if override:
        return override if kind == "data" else os.path.join(override, "tmp")
    if sys.platform == "win32":
        root = os.environ.get("APPDATA" if kind == "data" else "LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, APP_NAME) if kind == "data" else os.path.join(root, APP_NAME, "tmp")
    if kind == "data":
        return os.path.join(os.path.expanduser("~"), ".local", "share", "zhiraf-korrektor")
    return os.path.join(os.path.expanduser("~"), ".cache", "zhiraf-korrektor", "tmp")


def data_dir():
    path = _base("data")
    os.makedirs(path, exist_ok=True)
    return path


def tmp_dir():
    path = _base("tmp")
    os.makedirs(path, exist_ok=True)
    return path


def clean_tmp():
    """Temp copies of documents must not outlive the program, also after a crash."""
    shutil.rmtree(_base("tmp"), ignore_errors=True)
    tmp_dir()


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return default  # a damaged file must not stop the program


class Dictionary:
    """The user's words: never flagged again. One word per line, compared without case."""

    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "словарь.txt")
        self._words = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8-sig") as f:
                for line in f:
                    self._remember(line.strip())

    def _remember(self, word):
        if word:
            self._words.setdefault(word.lower(), word)

    def __contains__(self, word):
        return word.strip().lower() in self._words

    def __len__(self):
        return len(self._words)

    def words(self):
        return sorted(self._words.values(), key=str.lower)

    def add(self, word):
        self._remember(word.strip())
        self._save()

    def remove(self, word):
        self._words.pop(word.strip().lower(), None)
        self._save()

    def export(self, path):
        _write_atomic(path, "\n".join(self.words()) + "\n")

    def import_from(self, path):
        before = len(self._words)
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                self._remember(line.strip())
        self._save()
        return len(self._words) - before

    def _save(self):
        _write_atomic(self.path, "\n".join(self.words()) + "\n")


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "настройки.json")
        self._values = dict(DEFAULT_SETTINGS)
        stored = _read_json(self.path, {})
        if isinstance(stored, dict):
            self._values.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})

    def __getitem__(self, key):
        return self._values[key]

    def set(self, key, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        self._values[key] = value
        _write_atomic(self.path, json.dumps(self._values, ensure_ascii=False, indent=1))


class Recent:
    """Recently opened documents: path, time and counters; no text, no findings."""

    def __init__(self, settings, path=None):
        self.settings = settings
        self.path = path or os.path.join(data_dir(), "недавние.json")
        items = _read_json(self.path, [])
        self._items = items if isinstance(items, list) else []

    def items(self):
        return list(self._items)

    def touch(self, path, stats=None):
        if not self.settings["remember_recent"]:
            return
        key = os.path.normcase(os.path.abspath(path))
        old = [i for i in self._items if os.path.normcase(os.path.abspath(i["path"])) == key]
        self._items = [i for i in self._items if i not in old]
        kept = old[0].get("stats", {}) if old else {}
        self._items.insert(0, {"path": os.path.abspath(path), "opened_at": time.time(), "stats": stats or kept})
        del self._items[MAX_RECENT:]
        self._save()

    def clear(self):
        self._items = []
        self._save()

    def _save(self):
        _write_atomic(self.path, json.dumps(self._items, ensure_ascii=False, indent=1))
