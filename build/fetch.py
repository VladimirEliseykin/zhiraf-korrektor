"""Pinned Windows dependencies: download with sha256 verification (host only)."""
import hashlib
import os
import shutil
import urllib.request
from collections import namedtuple

Dep = namedtuple("Dep", "name url sha256 kind")

LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deps.lock")


class HashMismatch(Exception):
    pass


def read_lock(path=LOCK):
    deps = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                raise ValueError("bad deps.lock line: %r" % line)
            deps.append(Dep(*parts))
    return deps


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(dep, cache_dir):
    """Return the cached file path, downloading and verifying it if needed."""
    os.makedirs(cache_dir, exist_ok=True)
    fname = os.path.basename(dep.url.split("?")[0])
    target = os.path.join(cache_dir, fname)
    if os.path.isfile(target):
        if _sha256(target) == dep.sha256:
            return target
        os.remove(target)
    part = target + ".part"
    try:
        with urllib.request.urlopen(dep.url) as src, open(part, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        got = _sha256(part)
        if got != dep.sha256:
            raise HashMismatch("%s: expected sha256 %s, got %s"
                               % (fname, dep.sha256, got))
        os.replace(part, target)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return target


def fetch_all(lock_path=LOCK, cache_dir=None):
    """Fetch every dependency; return {dep.name: path}."""
    return {d.name: fetch(d, cache_dir) for d in read_lock(lock_path)}


if __name__ == "__main__":
    import sys
    out = fetch_all(LOCK, sys.argv[1] if len(sys.argv) > 1 else
                    os.path.expanduser("~/vm/win7/dist-cache"))
    for k, v in out.items():
        print("OK", k, v)
