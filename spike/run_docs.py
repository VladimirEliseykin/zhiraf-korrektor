"""Throwaway spike: run the ONNX corrector over all document sentences in parallel."""
import json
import multiprocessing
import sys

sys.path.insert(0, "/home/general/vm/win7/payload")
sys.path.insert(0, "/home/general/vm/win7/spike")
from infer_onnx import Corrector, normalize, postprocess, digits  # noqa: E402
from guards import apply_guarded, prepare  # noqa: E402

MODEL_DIR = "/home/general/vm/win7/payload/model-onnx"
corrector = None


def init_worker():
    global corrector
    corrector = Corrector(MODEL_DIR, 3)


def work(item):
    marker, body = prepare(item["src"])
    raw = postprocess(body, corrector.correct(body))
    guarded, accepted, rejected = apply_guarded(body, raw)
    out = marker + guarded
    item["raw"] = marker + raw
    item["out"] = out
    item["accepted"] = accepted
    item["rejected"] = rejected
    item["changed"] = normalize(out) != normalize(item["src"])
    item["digits_changed"] = digits(out) != digits(item["src"])
    return item


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, encoding="utf-8") as f:
        items = [json.loads(line) for line in f]
    with multiprocessing.Pool(4, initializer=init_worker) as pool, open(out_path, "w", encoding="utf-8") as out:
        for done, item in enumerate(pool.imap(work, items, chunksize=8), 1):
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
            if done % 500 == 0:
                print(done, flush=True)
    print("finished", len(items))


if __name__ == "__main__":
    main()
