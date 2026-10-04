"""Throwaway spike: compare correction pipelines on gold, clean-official and public sets."""
import collections
import difflib
import json
import os
import sys

sys.path.insert(0, "/home/general/vm/win7/payload")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from infer_onnx import normalize  # noqa: E402
from guards import TOKEN, prepare  # noqa: E402
import policy  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__)) + "/"
SCORE_TOKEN = __import__("re").compile(r"\w+(?:-\w+)*|[^\w\s]")


def load_jsonl(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


TECH_DOCS = ("05-Tekhnicheskiy_proekt", "7_Formirovanie_trebovaniy_ZI_GIS", "4_Trebovania_TZI_117",
             "3_NPA_bez_GT_ZK_2024", "6_Kadry_NPA", "9_Upravlenie_uyazvimostyami_v_IS", "PZ_", "KP_", "VKR_",
             "ipfire_kursovoy_vpn", "referat_SolarWinds")


def is_tech(doc):
    """Service/technical documents (closest to the target: orders, reports, TЗ, threat models, regulations)."""
    return doc.startswith(TECH_DOCS)


def load_sets():
    raw_docs = {r["src"]: r["raw"] for r in load_jsonl(BASE + "doc-results-guarded.jsonl")}
    doc_of = {r["src"]: r["doc"] for r in load_jsonl(BASE + "doc-results-guarded.jsonl")}
    sets = {"dev": [], "test": []}
    # batches 1-4: first gold (400), 5-8: expansion (600), 9-22: expansion (2100); a batch counts
    # only once both passes exist, so a half-annotated batch never enters the scores
    n_batches = 1
    while os.path.exists(BASE + "gold-verify-%d.json" % n_batches):
        n_batches += 1
    for n in range(1, n_batches):
        annot = json.load(open(BASE + "gold-annot-%d.json" % n, encoding="utf-8"))
        verify = json.load(open(BASE + "gold-verify-%d.json" % n, encoding="utf-8"))
        for a, v in zip(annot, verify):
            disputed = [m["fragment"] for m in v.get("missed", [])]
            disputed += [c["fragment"] for c in v.get("checks", []) if c["verdict"] == "disagree"]
            split = "dev" if a["id"].startswith("dev") else "test"
            sets[split].append({"src": a["sentence"], "gold": a["gold"], "raw": raw_docs[a["sentence"]],
                                "disputed": disputed, "doc": doc_of.get(a["sentence"], "")})
    sets["official"] = [{"src": r["src"], "gold": r["src"], "raw": r["raw"], "disputed": []}
                        for r in load_jsonl(BASE + "official-results.jsonl")]
    gold_mdg = {r["src"]: r["gold"] for r in load_jsonl(BASE + "mdg-sentences.jsonl")}
    sets["public"] = [{"src": r["src"], "gold": gold_mdg[r["src"]], "raw": r["raw"], "disputed": []}
                      for r in load_jsonl(BASE + "mdg-results.jsonl")]
    return sets


def edits(src, out):
    a, b = SCORE_TOKEN.findall(normalize(src)), SCORE_TOKEN.findall(normalize(out))
    result = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            result.add((i1, i2, tuple(b[j1:j2]), tuple(a[i1:i2])))
    return result


def disputed_ranges(src, fragments):
    tokens = SCORE_TOKEN.findall(normalize(src))
    ranges = []
    for frag in fragments:
        ft = SCORE_TOKEN.findall(normalize(frag))
        for i in range(len(tokens) - len(ft) + 1):
            if ft and tokens[i:i + len(ft)] == ft:
                ranges.append((i, i + len(ft)))
    return ranges


def is_comma(edit):
    _, _, after, before = edit
    return set(after + before) == {","}


def score(items, outputs):
    c = collections.Counter()
    for item, out in zip(items, outputs):
        gold = {e[:3] for e in edits(item["src"], item["gold"])}
        gold_full = {e[:3]: e for e in edits(item["src"], item["gold"])}
        system = edits(item["src"], out)
        ranges = disputed_ranges(item["src"], item["disputed"])
        for e in system:
            group = "comma" if is_comma(e) else "other"
            if e[:3] in gold:
                c[group + "_tp"] += 1
            elif any(e[0] < r[1] and e[1] > r[0] or e[0] == r[0] for r in ranges):
                c["ignored"] += 1
            else:
                c[group + "_fp"] += 1
        produced = {e[:3] for e in system}
        for key, e in gold_full.items():
            if key not in produced:
                c[("comma" if is_comma(e) else "other") + "_fn"] += 1
    return c


# ---------- systems ----------

def sage_policy(item, mode):
    marker, body = prepare(item["src"])
    raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
    if mode == "raw":
        return marker + raw_body
    text, _ = policy.apply_policy(body, raw_body, mode)
    return marker + text


def apply_commas(text, preds, threshold, allow_remove=True):
    """Insert/remove commas after words according to RUPunct probabilities."""
    from rupunct import WORD as RW
    matches = list(RW.finditer(text))
    pieces, last = [], 0
    for m, (_, p) in zip(matches, preds):
        pieces.append(text[last:m.end()])
        last = m.end()
        tail = text[m.end():]
        has_comma = tail.startswith(",")
        if p >= threshold and not has_comma and tail[:1] in (" ",) and not tail.lstrip()[:1] in ("—", "–", "-", ")", ":", ";", "."):
            pieces.append(",")
        elif allow_remove and has_comma and p <= 1 - threshold:
            last += 1
    pieces.append(text[last:])
    return "".join(pieces)


def rupunct_only(item, preds, threshold):
    marker, body = prepare(item["src"])
    return marker + apply_commas(body, preds, threshold)


def combined(item, preds, mode, threshold):
    """SAGE policy for words + RUPunct for commas (SAGE comma edits dropped)."""
    marker, body = prepare(item["src"])
    raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
    words_text, _ = policy.apply_policy(body, raw_body, "words")
    return marker + apply_commas(words_text, preds, threshold, allow_remove=(mode == "add+rm"))


def arbiter(item, preds, mode):
    """SAGE policy, but comma edits survive only when RUPunct agrees."""
    marker, body = prepare(item["src"])
    raw_body = item["raw"][len(marker):] if item["raw"].startswith(marker) else item["raw"]
    text, _ = policy.apply_policy(body, raw_body, mode)
    agreed = apply_commas(body, preds, 0.5)
    # keep a SAGE comma edit only if the RUPunct version of body has the same comma state
    from rupunct import author_commas
    w_text, c_text = author_commas(text)
    w_agreed, c_agreed = author_commas(agreed)
    w_body, c_body = author_commas(body)
    if not (len(c_text) == len(c_agreed) == len(c_body)):
        return marker + text
    final = []
    for i in range(len(c_body)):
        final.append(c_text[i] if c_text[i] == c_agreed[i] else c_body[i])
    return marker + set_commas(text, final)


def set_commas(text, flags):
    from rupunct import WORD as RW
    matches = list(RW.finditer(text))
    pieces, last = [], 0
    for m, flag in zip(matches, flags):
        pieces.append(text[last:m.end()])
        last = m.end()
        tail = text[m.end():m.end() + 3]
        # same notion of "comma after the word" as rupunct.author_commas (may follow ) » ")
        has_comma = tail.startswith(",") or tail.lstrip(" )»\"”").startswith(",")
        if flag and not has_comma:
            pieces.append(",")
        elif not flag and tail.startswith(","):
            last += 1
    pieces.append(text[last:])
    return "".join(pieces)


def main():
    sets = load_sets()
    policy.preload_lexicon([x for s in sets.values() for i in s for x in (i["src"], i["raw"], i["gold"])])
    preds = {}
    for size in sys.argv[1:]:
        cache = BASE + "rupunct-body-%s.json" % size
        if os.path.exists(cache):
            preds[size] = json.load(open(cache, encoding="utf-8"))
            continue
        from rupunct import RUPunct, author_commas
        model = RUPunct("/home/general/vm/win7/models/RUPunct_%s" % size, threads=8)
        preds[size] = {}
        for s in sets.values():
            for item in s:
                # RUPunct sees exactly the text the edits are applied to: no list marker
                words, _ = author_commas(prepare(item["src"])[1])
                if item["src"] not in preds[size] and words:
                    preds[size][item["src"]] = model.predict(words)
        json.dump(preds[size], open(cache, "w", encoding="utf-8"), ensure_ascii=False)

    systems = {
        "SAGE как есть": lambda i: sage_policy(i, "raw"),
        "SAGE + защита": lambda i: sage_policy(i, "guards"),
        "SAGE политика C": lambda i: sage_policy(i, "C"),
        "SAGE C + удаление запятых": lambda i: sage_policy(i, "C+rm"),
    }
    for size in preds:
        p = preds[size]
        systems["RUPunct-%s (0.5)" % size] = lambda i, p=p: rupunct_only(i, p.get(i["src"], []), 0.5)
        systems["RUPunct-%s (0.9)" % size] = lambda i, p=p: rupunct_only(i, p.get(i["src"], []), 0.9)
        systems["C слова + RUPunct-%s запятые 0.9" % size] = lambda i, p=p: combined(i, p.get(i["src"], []), "add+rm", 0.9)
        systems["C + арбитр RUPunct-%s" % size] = lambda i, p=p: arbiter(i, p.get(i["src"], []), "C+rm")

    for set_name in ("dev", "official", "public"):
        items = sets[set_name]
        print("\n=== %s (%d предложений) ===" % (set_name, len(items)))
        print("%-38s %8s %8s %8s | %8s %8s %8s | %6s" % ("система", "зап.TP", "зап.FP", "зап.FN", "сл.TP", "сл.FP", "сл.FN", "точн."))
        for name, fn in systems.items():
            outputs = [fn(i) for i in items]
            c = score(items, outputs)
            tp, fp = c["comma_tp"] + c["other_tp"], c["comma_fp"] + c["other_fp"]
            precision = tp / max(1, tp + fp)
            print("%-38s %8d %8d %8d | %8d %8d %8d | %5.0f%%" % (
                name, c["comma_tp"], c["comma_fp"], c["comma_fn"], c["other_tp"], c["other_fp"], c["other_fn"], 100 * precision))


if __name__ == "__main__":
    main()
