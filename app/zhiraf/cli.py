"""Check a document from the command line (and the whole core end to end):

    python -m zhiraf.cli check <file> [--accept-errors] [--out path] [--models folder]
"""
import argparse
import sys
import time

from . import models_dir as default_models_dir
from . import storage
from .documents.model import DocumentError
from .documents.opener import close_document, open_document, save_document
from .review import ReviewSession
from .segment import split_sentences
from .worker import CheckJob


def plan_sentences(paragraphs):
    sentences, where = [], []
    for index, text in enumerate(paragraphs):
        for start, end in split_sentences(text):
            sentences.append(text[start:end])
            where.append((index, start))
    return sentences, where


def check_file(path, models, accept_errors=False, out=None, factories=None, stages=None, threads=2, report=None):
    storage.clean_tmp()
    settings = storage.Settings()
    doc = open_document(path)
    try:
        paragraphs = [p.text for p in doc.paragraphs]
        sentences, where = plan_sentences(paragraphs)
        session = ReviewSession(paragraphs, storage.Dictionary())
        job = CheckJob(models, sentences, context=sentences, stages=stages, strict=settings["strict_mode"],
                       threads=threads, factories=factories)
        job.start()
        try:
            while not job.finished:
                for message in job.poll(timeout=0.5):
                    if message[0] == "findings":
                        paragraph, offset = where[message[2]]
                        session.add_findings(paragraph, offset, message[3])
                if report is not None:
                    report(job.progress)
        finally:
            job.close()
        if job.error is not None:
            raise RuntimeError(job.error[1])
        if accept_errors:
            session.accept_all_errors()
        saved = save_document(doc, session.replacements(), out)
        counts = session.counts()
        storage.Recent(settings).touch(path, {"fixed": counts["fixed"], "skipped": counts["skipped"],
                                              "handled": counts["total"] - counts["errors"] - counts["checks"],
                                              "total": counts["total"]})
        return {"counts": counts, "saved": saved.path, "applied": saved.applied,
                "not_applied": len(saved.skipped), "notice": doc.notice}
    finally:
        close_document(doc)


def _progress_line(progress):
    remaining = progress.remaining_seconds()
    tail = "" if remaining is None else " · осталось ≈ %d мин" % max(1, round(remaining / 60))
    sys.stderr.write("\rПроверено %d%%%s   " % (round(progress.fraction() * 100), tail))
    sys.stderr.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="zhiraf")
    commands = parser.add_subparsers(dest="command")
    check = commands.add_parser("check", help="проверить документ и сохранить исправленную копию")
    check.add_argument("path")
    check.add_argument("--accept-errors", action="store_true", help="принять все уверенные исправления")
    check.add_argument("--out", default=None)
    check.add_argument("--models", default=None)
    check.add_argument("--factories", default=None, help=argparse.SUPPRESS)  # tests: fake models
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help()
        return 1
    started = time.time()
    try:
        result = check_file(args.path, args.models or default_models_dir(), args.accept_errors, args.out,
                            factories=args.factories, report=_progress_line)
    except DocumentError as e:
        sys.stderr.write("\n%s\n" % e)
        return 2
    c = result["counts"]
    sys.stderr.write("\n")
    print("Ошибки: %d · Проверить: %d · Исправлено: %d · Пропущено: %d" % (c["errors"], c["checks"], c["fixed"],
                                                                          c["skipped"]))
    if result["not_applied"]:
        print("Не удалось применить исправлений: %d (мешает табуляция или разрыв строки)" % result["not_applied"])
    if result["notice"]:
        print(result["notice"])
    print("Сохранено: %s (%.0f с)" % (result["saved"], time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
