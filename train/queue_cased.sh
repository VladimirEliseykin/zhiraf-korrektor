#!/bin/sh
# Training queue (2026-10-04): every model retrained with the cased tokenizer (no lowercasing,
# no accent stripping). Runs one after another on the Arc GPU; each run resumes from its checkpoint.
# Commas specialist = round 3 recipe; forms specialist = round 5 recipe warm-started from it.
PY=/home/general/vm/win7/venv-train/bin/python
T=/home/general/vm/win7/train/tagger.py
C=/home/general/vm/win7/corpus/round2.jsonl
R=/home/general/vm/win7/runs
S=/home/general/vm/win7/spike
EX="$S/official-sentences.jsonl $S/mdg-sentences.jsonl $S/synth-dev.json $S/synth-test.json"
for n in $(seq 1 22); do EX="$EX $S/gold-annot-$n.json"; done
LOG=$R/queue-cased.log

run() {
  name=$1; shift
  echo "=== $name start $(date)" >> $LOG
  $PY -u $T train --corpus $C --exclude $EX --out $R/$name "$@" 2>&1 | grep --line-buffered -v -i -E "warn|numpy|_xpu_get" >> $R/$name.log
  echo "=== $name exit $? $(date)" >> $LOG
  [ -f $R/$name/model.pt ] || exit 1
}

run base-cased-commas --base /home/general/vm/win7/models/ruBert-base --epochs 2 --batch 32 --lr 5e-5 --uniform-placement
run base-cased-forms --base /home/general/vm/win7/models/ruBert-base --init $R/base-cased-commas --epochs 1 --batch 32 --lr 3e-5 --p-clean 0.7 --max-edits 2 --p-single 0.8
run large-cased-commas --base /home/general/vm/win7/models/ruBert-large --epochs 2 --batch 16 --lr 2e-5 --uniform-placement
run large-cased-forms --base /home/general/vm/win7/models/ruBert-large --init $R/large-cased-commas --epochs 1 --batch 16 --lr 2e-5 --p-clean 0.7 --max-edits 2 --p-single 0.8
echo "=== queue done $(date)" >> $LOG
