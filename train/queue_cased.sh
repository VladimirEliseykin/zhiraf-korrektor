#!/bin/bash
# Training queue (2026-10-04): every model retrained with the cased tokenizer (no lowercasing,
# no accent stripping). Runs one after another on the Arc GPU; each run resumes from its checkpoint.
# A stage counts as done only when the trainer itself exits 0: model.pt already exists after the
# first epoch, so a run killed later (memory pressure, 2026-10-05) used to pass as finished.
set -o pipefail
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
  [ -f $R/$name/done ] && return 0
  for attempt in 1 2 3 4 5 6; do
    echo "=== $name start (attempt $attempt) $(date)" >> $LOG
    # grep exits 1 when it filters out every line; only the trainer's status matters
    $PY -u $T train --corpus $C --exclude $EX --out $R/$name "$@" 2>&1 \
      | { grep --line-buffered -v -i -E "warn|numpy|_xpu_get" >> $R/$name.log; true; }
    status=$?
    echo "=== $name exit $status $(date)" >> $LOG
    if [ $status -eq 0 ]; then
      touch $R/$name/done
      return 0
    fi
    sleep 300  # resumes from checkpoint.pt; a pause lets a memory spike of another program pass
  done
  echo "=== $name failed 6 times, queue stopped $(date)" >> $LOG
  exit 1
}

run base-cased-commas --base /home/general/vm/win7/models/ruBert-base --epochs 2 --batch 32 --lr 5e-5 --uniform-placement
run base-cased-forms --base /home/general/vm/win7/models/ruBert-base --init $R/base-cased-commas --epochs 1 --batch 32 --lr 3e-5 --p-clean 0.7 --max-edits 2 --p-single 0.8
run large-cased-commas --base /home/general/vm/win7/models/ruBert-large --epochs 2 --batch 16 --lr 2e-5 --uniform-placement
run large-cased-forms --base /home/general/vm/win7/models/ruBert-large --init $R/large-cased-commas --epochs 1 --batch 16 --lr 2e-5 --p-clean 0.7 --max-edits 2 --p-single 0.8
echo "=== queue done $(date)" >> $LOG
