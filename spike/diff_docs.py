"""Throwaway spike: word-level diffs of model changes, grouped by change type."""
import collections
import difflib
import json
import re
import sys

sys.path.insert(0, "/home/general/vm/win7/payload")
from infer_onnx import normalize  # noqa: E402

TOKEN = re.compile(r"\w+(?:-\w+)*|[^\w\s]")


def edits(src, out):
    a, b = TOKEN.findall(normalize(src)), TOKEN.findall(normalize(out))
    result = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            result.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return result


def kind(before, after):
    if before.lower() == after.lower():
        return "регистр"
    if set(before + after) <= set(",") and (before or after):
        return "запятая"
    if re.fullmatch(r"[^\w\s]*", before) and re.fullmatch(r"[^\w\s]*", after):
        return "другая пунктуация"
    if before.replace(" ", "") == after.replace(" ", "").replace("-", "") or after.replace(" ", "") == before.replace(" ", "").replace("-", ""):
        return "слитно/раздельно/дефис"
    if not before or not after:
        return "вставка/удаление слова"
    return "замена слова"


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    items = [json.loads(line) for line in open(in_path, encoding="utf-8")]
    changed = [i for i in items if i["changed"]]
    kinds = collections.Counter()
    rows = []
    for item in changed:
        item_edits = edits(item["src"], item["out"])
        item["edits"] = [{"from": b, "to": a, "kind": kind(b, a)} for b, a in item_edits]
        kinds.update(e["kind"] for e in item["edits"])
        rows.append(item)
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("sentences:", len(items))
    print("changed:", len(changed))
    print("digits changed:", sum(i["digits_changed"] for i in items))
    print("edits total:", sum(kinds.values()))
    for k, v in kinds.most_common():
        print("  %-26s %d" % (k, v))


if __name__ == "__main__":
    main()
