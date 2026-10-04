"""Extract clean modern Russian official-document sentences from a ruwikisource dump.

Usage: python corpus_extract.py <dump.xml.bz2> <out.jsonl> [exclude_titles.txt]
Keeps main-namespace pages whose titles look like official acts, skips
pre-reform orthography, strips wiki markup and writes one sentence per line.
"""
import bz2
import json
import re
import sys
import xml.etree.ElementTree as ET

import mwparserfromhell

TITLE = re.compile(r"^(Федеральный (конституционный )?закон|Закон Российской Федерации|Закон РФ|"
                   r"Постановление|Указ Президента|Распоряжение|Приказ|Кодекс|Гражданский кодекс|"
                   r"Трудовой кодекс|Налоговый кодекс|Уголовный кодекс|Конституция Российской Федерации|"
                   r"Положение|Определение Конституционного Суда|Решение)", re.I)
# second pass (2026-10-03): administrative/technical genres the target documents belong to
ADMIN_TITLE = re.compile(r"^(Методика|Методические (рекомендации|указания)|Инструкция|Регламент|"
                         r"Административный регламент|Порядок|Требования|Письмо|Перечень|Правила|"
                         r"Рекомендации|Типовое положение|Концепция|Стратегия|Доктрина|Программа|"
                         r"Информационное письмо|Разъяснение|Обзор|Доклад)", re.I)
OLD_ORTHOGRAPHY = re.compile(r"[ѣіѳѵ]|ъ\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?…;:])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"\d")


def checkable(s):
    words = s.split()
    if len(words) < 5 or len(words) > 60:
        return False
    letters = len(CYRILLIC.findall(s))
    if letters < 0.6 * len(s.replace(" ", "")) or len(LATIN.findall(s)) > 0.1 * letters:
        return False
    if len(DIGIT.findall(s)) > 0.15 * len(s) or "\t" in s or "...." in s or "|" in s or "=" in s:
        return False
    return s[-1] in ".!?…:;"


def clean(wikitext):
    code = mwparserfromhell.parse(wikitext)
    for tag in code.filter_tags(recursive=True):
        if str(tag.tag).lower() in ("ref", "table", "math", "references", "sup", "sub"):
            try:
                code.remove(tag)
            except ValueError:
                pass
    text = code.strip_code(normalize=True, collapse=True)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^[\s*#:;]+", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def main():
    dump, out_path = sys.argv[1], sys.argv[2]
    exclude = set()
    if len(sys.argv) > 3:
        exclude = {l.strip() for l in open(sys.argv[3], encoding="utf-8") if l.strip()}
    title_re = ADMIN_TITLE if len(sys.argv) > 4 and sys.argv[4] == "admin" else TITLE
    seen = set()
    pages = kept = 0
    with bz2.open(dump, "rb") as f, open(out_path, "w", encoding="utf-8") as out:
        title = ns = None
        for event, elem in ET.iterparse(f, events=("end",)):
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "title":
                title = elem.text or ""
            elif tag == "ns":
                ns = elem.text
            elif tag == "text":
                text = elem.text or ""
                if ns == "0" and title_re.match(title) and not any(title.startswith(e) for e in exclude) \
                        and not text.lstrip().lower().startswith("#перенаправление") \
                        and not text.lstrip().lower().startswith("#redirect") and not OLD_ORTHOGRAPHY.search(text[:5000]):
                    pages += 1
                    for paragraph in clean(text):
                        for s in SENTENCE_END.split(paragraph):
                            s = s.strip()
                            if s in seen or not checkable(s):
                                continue
                            seen.add(s)
                            out.write(json.dumps({"doc": title, "src": s}, ensure_ascii=False) + "\n")
                            kept += 1
                    if pages % 500 == 0:
                        print("pages %d sentences %d" % (pages, kept), flush=True)
            elif tag == "page":
                elem.clear()
    print("done: pages %d sentences %d" % (pages, kept))


if __name__ == "__main__":
    main()
