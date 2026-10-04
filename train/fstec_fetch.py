"""Download FSTEC documents on technical information protection (pages + attached files).

Usage: python fstec_fetch.py <listing.html> <out_dir> <ca_bundle.pem>
fstec.ru is signed by the Russian Trusted CA (Ministry of Digital Development), which is not
in the system store, so the bundle is passed explicitly instead of trusting it system-wide.
For each document the editable copy (odt/docx/doc/rtf) is preferred over PDF: no hyphenation,
headers or page numbers mixed into the text. One request per second.
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://fstec.ru"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
DOC_LINK = re.compile(r'href="(/dokumenty/vse-dokumenty/[^"]+)"')
FILE_LINK = re.compile(r'href="(https://fstec\.ru/files/[^"]+\.(pdf|odt|docx|doc|rtf))"', re.I)
PREFERENCE = ("odt", "docx", "doc", "rtf", "pdf")


def get(ctx, url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return r.read()


def main():
    listing, out_dir, bundle = sys.argv[1:4]
    ctx = ssl.create_default_context(cafile=bundle)
    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "files"), exist_ok=True)
    links = sorted(set(DOC_LINK.findall(open(listing, encoding="utf-8").read())))
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    done = set()
    if os.path.exists(manifest_path):
        done = {json.loads(l)["page"] for l in open(manifest_path, encoding="utf-8")}
    with open(manifest_path, "a", encoding="utf-8") as manifest:
        for n, path in enumerate(links, 1):
            if path in done:
                continue
            slug = path.rstrip("/").rsplit("/", 1)[-1]
            record = {"page": path, "slug": slug, "files": []}
            try:
                html = get(ctx, BASE + path)
                open(os.path.join(out_dir, "pages", slug + ".html"), "wb").write(html)
                files = {}
                for url, ext in FILE_LINK.findall(html.decode("utf-8", "replace")):
                    files.setdefault(ext.lower(), url)
                for ext in PREFERENCE:
                    if ext in files:
                        time.sleep(1)
                        name = "%s.%s" % (slug, ext)
                        open(os.path.join(out_dir, "files", name), "wb").write(get(ctx, urllib.parse.quote(files[ext], safe=":/%")))
                        record["files"].append(name)
                        break
            except Exception as e:  # keep going; the manifest records what failed
                record["error"] = repr(e)
            manifest.write(json.dumps(record, ensure_ascii=False) + "\n")
            manifest.flush()
            print("%d/%d %s %s" % (n, len(links), slug[:70], record.get("error") or ",".join(record["files"]) or "-"), flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
