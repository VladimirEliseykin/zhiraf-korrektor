"""Predictions of tagger runs for the public benchmark (dev2 + test2), cached in <run>/bench-preds2.json.

Usage: python predict_public.py <run_dir>...   (CPU; sentences already in the cache are skipped)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ensemble_eval as ee  # noqa: E402
import tagger_eval as te  # noqa: E402


def main():
    pub = ee.load_public()
    items = pub["dev2"] + pub["test2"]
    for run in sys.argv[1:]:
        path = os.path.join(run, "bench-preds2.json")
        cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        missing = [i for i in items if i["src"] not in cache]
        if missing:
            tagger = te.EditTagger(run)
            for n, item in enumerate(missing):
                marker, body = te.prepare(item["src"])
                cache[item["src"]] = (marker, body, "", tagger.predict(body))
            tmp = path + ".tmp"
            json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, path)
            del tagger
        print("done", os.path.basename(run), len(missing), flush=True)


if __name__ == "__main__":
    main()
