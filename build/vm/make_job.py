"""Assemble the job folder for the Windows 7 VM (host only).

Usage: python -m build.vm.make_job <job_dir> <samples_dir>
<samples_dir> holds Образец.docx, Образец.doc and sample.docx (made by docfactory, kept outside git).
The forbidden-module lists come from build.prune; they are written next to win_check.py because build/ is not
shipped to the VM.
"""
import json
import os
import shutil
import sys
import time

from build import prune

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = ("Образец.docx", "Образец.doc", "sample.docx")


def forbidden_rules():
    stdlib = [name for name in prune.FORBIDDEN_STDLIB if not name.endswith(".dll")]
    qt = ["PySide2." + name.rstrip("*") for name in prune.FORBIDDEN_QT
          if name.startswith("Qt") and not name.startswith("Qt5") and "/" not in name]
    return {"stdlib": stdlib, "qt": qt}


def make_job(job_dir, samples_dir):
    shutil.rmtree(job_dir, ignore_errors=True)
    os.makedirs(os.path.join(job_dir, "work"))
    for name in ("run.cmd", "win_check.py"):
        shutil.copy(os.path.join(HERE, name), job_dir)
    with open(os.path.join(job_dir, "forbidden.json"), "w", encoding="utf-8") as f:
        json.dump(forbidden_rules(), f, ensure_ascii=False, indent=1)
    for name in SAMPLES:
        shutil.copy(os.path.join(samples_dir, name), os.path.join(job_dir, "work", name))
    with open(os.path.join(job_dir, "id.txt"), "w", encoding="ascii") as f:   # a new id makes the VM watcher run it
        f.write("job-%d\n" % int(time.time()))


if __name__ == "__main__":
    make_job(sys.argv[1], sys.argv[2])
