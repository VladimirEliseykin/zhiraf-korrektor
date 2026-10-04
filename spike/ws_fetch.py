"""Throwaway spike: download official documents from Russian Wikisource as plain text."""
import html.parser
import os
import sys
import urllib.parse
import urllib.request

TITLES = [
    "Федеральный закон от 27.07.2006 № 152-ФЗ",
    "Федеральный закон от 20.02.1995 № 24-ФЗ",
    "Федеральный закон от 29.12.2022 № 572-ФЗ",
    "Указ Президента РФ от 31.12.2015 № 683",
    "Указ Президента РФ от 05.02.2010 № 146",
    "Постановление Правительства РФ от 26.05.1997 № 643",
    "Постановление Правительства РФ от 11.06.1996 № 698",
    "Приказ МПР РФ от 25.02.2010 № 50/Редакция 22.12.2010",
    "Перечень информации о деятельности ФСТЭК России, размещаемой в сети Интернет",
]
KEEP = {"p", "li", "dd"}
SKIP = {"table", "style", "script", "sup"}


class Extractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth_keep = 0
        self.depth_skip = 0
        self.buffer = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.depth_skip += 1
        elif tag in KEEP:
            self.depth_keep += 1

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.depth_skip = max(0, self.depth_skip - 1)
        elif tag in KEEP:
            self.depth_keep = max(0, self.depth_keep - 1)
            if self.depth_keep == 0:
                text = " ".join("".join(self.buffer).split())
                if text:
                    self.paragraphs.append(text)
                self.buffer = []

    def handle_data(self, data):
        if self.depth_keep and not self.depth_skip:
            self.buffer.append(data)


def main():
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)
    for n, title in enumerate(TITLES, 1):
        url = "https://ru.wikisource.org/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "render"})
        req = urllib.request.Request(url, headers={"User-Agent": "spellcheck-spike/0.1"})
        page = urllib.request.urlopen(req, timeout=120).read().decode("utf-8")
        extractor = Extractor()
        extractor.feed(page)
        with open(os.path.join(out_dir, "official_%02d.txt" % n), "w", encoding="utf-8") as f:
            f.write("\n".join(extractor.paragraphs))
        print("%2d  %6d chars  %s" % (n, sum(len(p) for p in extractor.paragraphs), title))


if __name__ == "__main__":
    main()
