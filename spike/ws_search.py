"""Throwaway spike: find official documents on Russian Wikisource."""
import json
import sys
import urllib.parse
import urllib.request

API = "https://ru.wikisource.org/w/api.php"

for query in sys.argv[1:]:
    params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                     "format": "json", "srlimit": 8})
    req = urllib.request.Request(API + "?" + params, headers={"User-Agent": "spellcheck-spike/0.1"})
    data = json.load(urllib.request.urlopen(req, timeout=60))
    print("==", query)
    for hit in data["query"]["search"]:
        print("  %7d  %s" % (hit["size"], hit["title"]))
