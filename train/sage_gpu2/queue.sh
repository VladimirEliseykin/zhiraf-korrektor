#!/bin/bash
# Rented GPU, SAGE round 2: much more data for the commas. ai-forever/sage-fredt5-distilled-95m (T5, 95M).
# data/: real pairs sage_err.jsonl 8450 + sage_clean.jsonl 15786 (as in pack9, 5% held out with --split-seed 12 = the held-out
# set of run sage-b, so models/sage-b has never seen it), synthetic synth_err.jsonl + synth_clean.jsonl (sage_synth.py: corrupt_realistic
# on the clean corpus, comma recipe rate 16 / form recipe rate 4 x1.5, eval sentences excluded). Real pairs count 3x per epoch.
# bf16 autocast, max len 192. Every run writes a plain HF dir runs/<name>/ (best by greedy exact match on the real held-out set).
#   sage2-a  (i)   from the original 95m (models/sage-95m): synthetic + real, 2 epochs, lr 1e-4, batch 64
#   sage2-b  (ii)  continue from run sage-b (models/sage-b): synthetic + real, 1 epoch, lr 3e-5, batch 64
#   sage2-c  (iii) continue from sage2-b: the real pairs only, 2 epochs, lr 2e-5, batch 32, clean share 0.6
# Order b, c, a: the continuation is the likelier winner, so its two stages come first.
set -o pipefail
W=/root/zhiraf
PY=/venv/main/bin/python
R=$W/runs
LOG=$R/queue.log
SYN="--synth-err $W/data/synth_err.jsonl --synth-clean $W/data/synth_clean.jsonl"

run() {
  name=$1; shift
  [ -f $R/$name/done ] && return 0
  for attempt in 1 2 3; do
    echo "=== $name start (attempt $attempt) $(date)" >> $LOG
    rm -f $R/$name/log.jsonl
    $PY -u $W/train/sage_finetune.py --data $W/data --out $R/$name --max-len 192 --split-seed 12 --evals-per-epoch 4 "$@" 2>&1 \
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

run sage2-b --base $W/models/sage-b $SYN --real-repeat 3 --clean-share 0.55 --lr 3e-5 --epochs 1 --batch 64 --seed 22
if [ -f $R/sage2-b/done ]; then
  run sage2-c --base $R/sage2-b --real-repeat 1 --clean-share 0.6 --lr 2e-5 --epochs 2 --batch 32 --seed 23
else
  echo "=== sage2-c skipped: sage2-b is missing $(date)" >> $LOG
fi
run sage2-a --base $W/models/sage-95m $SYN --real-repeat 3 --clean-share 0.55 --lr 1e-4 --epochs 2 --batch 64 --seed 21
for n in sage2-a sage2-b sage2-c; do
  [ -f $R/$n/train_summary.json ] && echo "$n: $(grep -o '"score": [0-9.]*' $R/$n/train_summary.json | head -1)" >> $LOG
done
echo "=== sage2 done $(date)" >> $LOG
echo "=== sage2 done"
