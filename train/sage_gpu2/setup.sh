#!/bin/bash
# One-time setup on a fresh vast.ai PyTorch instance (RTX 4090 / 5090; torch with CUDA comes with the image). Upload the pack to /root/zhiraf first.
# Needs no HuggingFace: the base model (models/sage-95m) and the run-b weights (models/sage-b) are in the pack. Starts the queue at the end.
source /venv/main/bin/activate
cd /root/zhiraf
uv pip install -q -r requirements-gpu.txt
mkdir -p runs
sha256sum models/sage-95m/model.safetensors models/sage-b/model.safetensors | cut -c1-16   # e005b48a... (original 95m), the run-b weights
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
from transformers import AutoTokenizer
for m in ("models/sage-95m", "models/sage-b"):
    t = AutoTokenizer.from_pretrained(m)
    assert t("Привет, мир.")["input_ids"] == [50357, 37954, 16, 2309, 18], m + ": the tokenizer must prepend <LM> (50357)"
print("tokenizers ok")
PY
wc -l data/*.jsonl
for f in data/sage_err.jsonl data/sage_clean.jsonl data/synth_err.jsonl data/synth_clean.jsonl models/sage-b/model.safetensors models/sage-95m/model.safetensors; do
  [ -f $f ] || echo "MISSING $f"
done
setsid nohup bash queue.sh > runs/nohup.out 2>&1 < /dev/null &
echo "queue started: tail -f runs/queue.log (ends with '=== sage2 done')"
