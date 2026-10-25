#!/bin/bash
# Rented GPU, SAGE fine-tune. sage-fredt5-distilled-95m (T5, 95M) on real error pairs: commas, word forms, spelling, joined/hyphen
# (data/sage_err.jsonl 8450 pairs + data/sage_clean.jsonl 15786 src==gold: 1459 hard negatives, 4327 normalised-clean pairs,
# 10000 official-corpus sentences). 5% held out, best checkpoint by greedy exact match. bf16 autocast, batch 32, max len 192, 3 epochs.
# Runs (each writes a plain HF model dir runs/<name>/ with the best weights + tokenizer + train_summary.json):
#   sage-a: lr 5e-5, clean share 0.6      sage-b: lr 1e-4, clean share 0.6      sage-c: lr 5e-5, clean share 0.4
set -o pipefail
W=/root/zhiraf
PY=/venv/main/bin/python
R=$W/runs
LOG=$R/queue.log
BASE=$W/models/sage-95m

run() {
  name=$1; shift
  [ -f $R/$name/done ] && return 0
  for attempt in 1 2 3; do
    echo "=== $name start (attempt $attempt) $(date)" >> $LOG
    rm -f $R/$name/log.jsonl
    $PY -u $W/train/sage_finetune.py --data $W/data --out $R/$name --base $BASE --batch 32 --max-len 192 --epochs 3 "$@" 2>&1 \
      | { grep --line-buffered -v -i -E "warn|numpy" >> $R/$name.log; true; }
    status=${PIPESTATUS[0]}
    echo "=== $name exit $status $(date)" >> $LOG
    if [ $status -eq 0 ] && [ -f $R/$name/model.safetensors ]; then
      touch $R/$name/done
      return 0
    fi
    sleep 20
  done
  echo "=== $name failed, skipped $(date)" >> $LOG
}

run sage-a --lr 5e-5 --clean-share 0.6 --seed 11
run sage-b --lr 1e-4 --clean-share 0.6 --seed 12
run sage-c --lr 5e-5 --clean-share 0.4 --seed 13
for n in sage-a sage-b sage-c; do
  [ -f $R/$n/train_summary.json ] && echo "$n: $(grep -o '"score": [0-9.]*' $R/$n/train_summary.json | head -1)" >> $LOG
done
echo "=== sage done $(date)" >> $LOG
echo "=== sage done"
