"""Turn downloaded FSTEC documents into clean training sentences.

Usage: python fstec_extract.py <fstec_dir> <out.jsonl>
Expects <fstec_dir>/manifest.jsonl, pages/*.html and files/* from fstec_fetch.py, and plain-text
copies of odt/docx/doc/rtf in <fstec_dir>/txt/ (soffice --headless --convert-to txt:Text).
PDF text comes from pdftotext; lines are joined into paragraphs and words split by a line-end
hyphen are glued back only when the glued word is known to the dictionary. Sentences with
lowercase words unknown to pymorphy (garbled extraction, typos) are dropped.
"""
import collections
import html as htmlmod
import json
import os
import re
import subprocess
import sys

import pymorphy3

from corpus_extract import SENTENCE_END, checkable

morph = pymorphy3.MorphAnalyzer()
LOWER_WORD = re.compile(r"\b[а-яё]+(?:-[а-яё]+)*\b")
BODY = re.compile(r'<div class="com-content-article__body">(.*?)(?:<div[^>]*dropfiles|<div class="com-content-article__links|$)', re.S)
TAG = re.compile(r"<[^>]+>")
BLOCK_END = re.compile(r"</(p|div|li|h\d|tr)>|<br\s*/?>", re.I)
PAGE_NUMBER = re.compile(r"^\s*(-\s*)?\d{1,3}(\s*-)?\s*$")
LIST_MARKER = re.compile(r"^\s*(\d+(\.\d+)*(\(\d+\))?|[а-яёa-z]{1,2})\)\s")
LIST_START = re.compile(r"^\s*(\d+(\.\d+)*[.)]?\s|[а-яa-z]\)\s|[-–—•]\s)")


def known(word):
    return all(morph.word_is_known(p) for p in word.lower().split("-") if p)


def garbled(word):
    """Extraction damage: a line-break hyphen left inside a word ("подконт-рольными") or a lost
    hyphen between compound parts ("программноаппаратных" from "программно-аппаратных")."""
    if "-" in word and known(word.replace("-", "")):
        return True
    for i in range(5, len(word) - 3):
        if word[i - 1] in "оеи" and known(word[:i]) and known(word[i:]):
            return True
    return False


def no_typos(sentence, doc_freq):
    # domain terms unknown to pymorphy ("виртуализации", "категорирования") are exactly the
    # vocabulary of the target documents: keep them when they recur in at least two documents
    for w in LOWER_WORD.findall(sentence):
        if known(w):
            continue
        if garbled(w) or doc_freq[w] < 2:
            return False
    return True


def whole(sentence):
    """Reject table-of-contents leaders and fragments cut inside quotes or brackets."""
    if "……" in sentence or ".." in sentence:
        return False
    body = LIST_MARKER.sub("", sentence, count=1)  # "а) ...", "12) ..." are list items, not open brackets
    return body.count("«") == body.count("»") and body.count("(") == body.count(")")


def repair(sentence):
    """Undo extraction damage in words; garbled() describes the two kinds."""
    def fix(m):
        w = m.group(0)
        if known(w) or not garbled(w):
            return w
        if "-" in w and known(w.replace("-", "")):
            return w.replace("-", "")
        for i in range(5, len(w) - 3):
            if w[i - 1] in "оеи" and known(w[:i]) and known(w[i:]):
                return w[:i] + "-" + w[i:]
        return w
    return LOWER_WORD.sub(fix, sentence)


def html_paragraphs(raw):
    m = BODY.search(raw)
    if not m:
        return []
    text = BLOCK_END.sub("\n", m.group(1))
    text = htmlmod.unescape(TAG.sub("", text)).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", l).strip() for l in text.split("\n") if l.strip()]


def txt_paragraphs(path):
    # soffice writes manual line breaks inside a paragraph as newlines; in these documents such a
    # break follows a space ("Федеральной службы \nпо ..."), a real paragraph end does not
    text = open(path, encoding="utf-8-sig", errors="replace").read().replace("\xa0", " ")
    text = re.sub(r" \r?\n", " ", text)
    return [re.sub(r"\s+", " ", l).strip() for l in text.split("\n") if l.strip()]


def pdf_paragraphs(path):
    text = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, text=True).stdout
    paragraphs = []
    for block in re.split(r"\n\s*\n|\f", text):
        lines = [l.strip() for l in block.split("\n") if l.strip() and not PAGE_NUMBER.match(l)]
        current = ""
        for line in lines:
            if not current:
                current = line
            elif LIST_START.match(line) and current[-1:] in ".;:":
                paragraphs.append(current)
                current = line
            elif current.endswith("-") and line[:1].islower():
                head = current.rsplit(" ", 1)[-1][:-1]
                tail = line.split(" ", 1)[0]
                glued = head + re.match(r"[\w-]*", tail).group(0)
                current = current[:-1] + line if known(glued) else current + line
            else:
                current += " " + line
        if current:
            paragraphs.append(current)
    return paragraphs


def document_paragraphs(root, rec):
    paragraphs = []
    page = os.path.join(root, "pages", rec["slug"] + ".html")
    if os.path.exists(page):
        paragraphs += html_paragraphs(open(page, encoding="utf-8", errors="replace").read())
    for name in rec["files"]:
        stem, ext = os.path.splitext(name)
        if ext == ".pdf":
            paragraphs += pdf_paragraphs(os.path.join(root, "files", name))
        elif os.path.exists(os.path.join(root, "txt", stem + ".txt")):
            paragraphs += txt_paragraphs(os.path.join(root, "txt", stem + ".txt"))
    return paragraphs


def main():
    root, out_path = sys.argv[1], sys.argv[2]
    docs = [(json.loads(l), None) for l in open(os.path.join(root, "manifest.jsonl"), encoding="utf-8")]
    docs = [(rec, document_paragraphs(root, rec)) for rec, _ in docs]
    doc_freq = collections.Counter()
    for _, paragraphs in docs:
        doc_freq.update({w for p in paragraphs for w in LOWER_WORD.findall(p) if not known(w)})
    seen = set()
    kept = dropped = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for rec, paragraphs in docs:
            for paragraph in paragraphs:
                for s in SENTENCE_END.split(paragraph):
                    s = repair(s.strip())
                    if s in seen or not checkable(s):
                        continue
                    seen.add(s)
                    if not whole(s) or not no_typos(s, doc_freq):
                        dropped += 1
                        continue
                    out.write(json.dumps({"doc": "fstec:" + rec["slug"], "src": s}, ensure_ascii=False) + "\n")
                    kept += 1
    print("done: documents %d, sentences %d, dropped as garbled/typos %d" % (len(docs), kept, dropped))


if __name__ == "__main__":
    main()
