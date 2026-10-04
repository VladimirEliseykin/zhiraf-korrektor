"""Check documents from a JSON file and report findings, time and memory.

Usage: python run_check.py <models_dir> <docs.json> <out.json> [threads]
docs.json: {"document name": ["sentence", ...], ...}
"""
import json
import os
import platform
import sys
import time

import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spellcheck.checker import Checker  # noqa: E402


def peak_mb(process):
    info = process.memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows: the true peak of the process working set
    return round(peak / 2 ** 20) if peak else None


def main():
    models_dir, docs_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    process = psutil.Process()
    docs = json.load(open(docs_path, encoding="utf-8"))
    engine = Checker(models_dir, threads, process)
    started = time.perf_counter()
    findings, stages = {}, {}
    for name, sentences in docs.items():
        findings[name] = engine.check_document(sentences)
        stages[name] = dict(engine.stats)
    total = time.perf_counter() - started
    n = sum(len(s) for s in docs.values())
    vm = psutil.virtual_memory()
    summary = {
        "platform": platform.platform(), "python": platform.python_version(), "threads": threads,
        "sentences": n, "seconds_total": round(total, 1), "seconds_per_sentence": round(total / n, 2),
        "peak_process_mb": peak_mb(process), "stages": stages,
        "system_total_mb": round(vm.total / 2 ** 20), "system_available_mb_at_end": round(vm.available / 2 ** 20),
        "errors": sum(f["level"] == "error" for fs in findings.values() for s in fs for f in s),
        "checks": sum(f["level"] == "check" for fs in findings.values() for s in fs for f in s),
    }
    json.dump({"summary": summary, "findings": findings}, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
