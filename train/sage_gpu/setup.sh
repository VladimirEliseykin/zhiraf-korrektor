#!/bin/bash
# one-time setup on a fresh vast.ai PyTorch instance (RTX 5090, torch >= 2.7 with CUDA 12.8 comes with the image). Upload the pack to /root/zhiraf first.
source /venv/main/bin/activate
cd /root/zhiraf
uv pip install -q -r requirements-gpu.txt
mkdir -p models/sage-95m runs
for f in config.json generation_config.json added_tokens.json special_tokens_map.json tokenizer_config.json vocab.json merges.txt model.safetensors; do
  curl -sSL --fail -o models/sage-95m/$f https://huggingface.co/ai-forever/sage-fredt5-distilled-95m/resolve/main/$f || echo "DOWNLOAD FAILED $f"
done
# the original weights, as used for the local checks (e005b48a...)
sha256sum models/sage-95m/model.safetensors | cut -c1-16
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
from transformers import AutoTokenizer
t = AutoTokenizer.from_pretrained("models/sage-95m")
assert t("Привет, мир.")["input_ids"] == [50357, 37954, 16, 2309, 18], "tokenizer must prepend <LM> (50357)"
print("tokenizer ok")
PY
wc -l data/sage_err.jsonl data/sage_clean.jsonl
