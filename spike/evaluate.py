"""Throwaway spike: compare SAGE models on document-style Russian sentences."""
import argparse
import json
import re
import time

import psutil
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


def normalize(text):
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("«", '"').replace("»", '"')
    text = re.sub(r"\b([А-ЯA-Z])\. (?=[А-ЯA-Z]\.)", r"\1.", text)
    return re.sub(r"\s+", " ", text).strip()


def postprocess(src, out):
    """Undo harmless model habits the real app would also undo."""
    out = out.strip()
    if src and src[-1] in ".:;!?" and (not out or out[-1] not in ".:;!?"):
        out += src[-1]
    if "№" in src:
        out = re.sub(r"\bN(?=\s?\d)", "№", out)
    return out


def digits(text):
    return re.findall(r"\d+", text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--testset", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--int8", action="store_true")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--beams", type=int, default=1)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    process = psutil.Process()
    rss_before = process.memory_info().rss

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model, torch_dtype=torch.float32)
    model.eval()
    if args.int8:
        model = torch.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
    rss_loaded = process.memory_info().rss

    cases = json.load(open(args.testset, encoding="utf-8"))
    results = []
    peak_rss = rss_loaded
    total_time = 0.0
    for case in cases:
        inputs = tokenizer(case["src"], return_tensors="pt")
        started = time.perf_counter()
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_length=int(inputs["input_ids"].size(1) * 1.5) + 10,
                num_beams=args.beams,
            )
        elapsed = time.perf_counter() - started
        total_time += elapsed
        peak_rss = max(peak_rss, process.memory_info().rss)
        output = postprocess(case["src"], tokenizer.decode(outputs[0], skip_special_tokens=True))
        is_control = case["src"] == case["gold"]
        results.append({
            "src": case["src"],
            "gold": case["gold"],
            "out": output,
            "control": is_control,
            "exact": normalize(output) == normalize(case["gold"]),
            "changed": normalize(output) != normalize(case["src"]),
            "digits_changed": digits(output) != digits(case["src"]),
            "seconds": round(elapsed, 2),
        })

    errors = [r for r in results if not r["control"]]
    controls = [r for r in results if r["control"]]
    summary = {
        "model": args.model.rstrip("/").split("/")[-1] + (" int8" if args.int8 else " fp32"),
        "threads": args.threads,
        "beams": args.beams,
        "fixed_exactly": f'{sum(r["exact"] for r in errors)}/{len(errors)}',
        "controls_damaged": f'{sum(r["changed"] for r in controls)}/{len(controls)}',
        "sentences_with_digits_changed": f'{sum(r["digits_changed"] for r in results)}/{len(results)}',
        "avg_seconds_per_sentence": round(total_time / len(results), 2),
        "model_memory_mb": round((rss_loaded - rss_before) / 2**20),
        "peak_process_mb": round(peak_rss / 2**20),
    }
    json.dump({"summary": summary, "results": results}, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
