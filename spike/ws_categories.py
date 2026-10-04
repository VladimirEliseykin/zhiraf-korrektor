"""Throwaway spike: count documents in Russian Wikisource categories of official acts."""
import json
import sys
import urllib.parse
import urllib.request

API = "https://ru.wikisource.org/w/api.php"
HEADERS = {"User-Agent": "spellcheck-spike/0.1 (offline proofreading research)"}


def members(category, kind):
    titles, cont = [], {}
    while True:
        params = {"action": "query", "list": "categorymembers", "cmtitle": category, "cmtype": kind,
                  "cmlimit": "500", "format": "json"}
        params.update(cont)
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=HEADERS)
        data = json.load(urllib.request.urlopen(req, timeout=60))
        titles += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titles
        cont = data["continue"]


if __name__ == "__main__":
    for cat in sys.argv[1:]:
        pages = members(cat, "page")
        subcats = members(cat, "subcat")
        print("%5d pages, %3d subcats  %s" % (len(pages), len(subcats), cat))
        for s in subcats[:15]:
            print("        sub:", s)
