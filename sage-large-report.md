# SAGE-large (fine-tuned, int8) as the SAGE voter: evaluation

Branch `exp/26-sage-large`. Question: should the fine-tuned `ai-forever/sage-fredt5-large` (820M, int8 ONNX,
`runs/gpu-sagel/onnx-int8`) replace the current SAGE-95m voter (`engine/models/sage`, run sage-b)?

**Recommendation: do NOT adopt.** End to end it gives no gain (fixed 46% vs 46%, the confidence interval of every class
contains 0), it adds false "error" findings, it costs about 3.8x the SAGE time and about 1.2 GB more peak memory
(1.95 GB -> 3.14 GB on Linux), which on Win7 would be near the 4 GB limit.

## What was done

1. `engine/spellcheck/sage.py`: `num_heads` / `head_dim` were fixed at 6 / 64. They are now read from the shape
   `[batch, heads, length, head_dim]` of the decoder's first `past_key_values.*` input (`past_geometry`; fallback 6 / 64 when
   the shape is symbolic). 95m: 6 x 64, large: 16 x 64 (d_model 1024). Test: `app/tests/test_sage_geometry.py`
   (Python 3.7 syntax; the model tests run only with `ZHIRAF_SAGE_LARGE=<folder>`). The large tokenizer gives ids
   starting with 50357 for `Привет, мир.`, so the `<LM>` prefix holds, and the large model loads and corrects.
2. Same machine, same code, same day, `train/engine_eval.py` with 2 threads, run under `systemd-run` (MemoryMax=4G,
   CPUQuota=400%): baseline with `engine/models`, candidate with a folder of symlinks to `engine/models` where only `sage`
   points to the candidate. `engine/models` was not touched.
3. Split: engine_eval scores `dev + test` (the OLD gold, 3100 sentences, 349 gold edits) and the 1563 clean official
   sentences. dev2/test2 are not used (SAGE saw their source in pre-training). The full evaluation was run (no subset).
4. The baseline reproduces the documented numbers exactly (46 / 11 / 43; commas 79/131; endings 51/127; joined 18/35;
   case 2/17; false 0.6 / 1.8; official 0.1 / 0.8).

Environment note: `spike/bench.py` imports `infer_onnx.normalize` from `/home/general/vm/win7/payload`, which no longer
exists. For both runs I used a shim with `normalize()` copied from `spike/evaluate.py` (the same function), so the
baseline-vs-candidate comparison is like for like, and the baseline matches the documented figures.

## Results (old gold, 3100 sentences; official 1563 clean)

| | baseline (sage-b 95m) | candidate (large int8) |
|---|---|---|
| fixed / highlighted / missed | 46% / 11% / 43% | 46% / 11% / 44% |
| fixed edits (of 349) | 160 | 160 |
| false "error" per 100 | 0.6 (18) | 0.8 (26) |
| false "check" per 100 | 1.8 (56) | 1.9 (58) |
| official false error / check per 100 | 0.1 / 0.8 | 0.2 / 0.8 |

Per class, fixed (highlighted) with a paired bootstrap over sentences, 2000 resamples, 95% CI of the difference
(candidate minus baseline), computed by an ad-hoc script on the engine_eval findings (engine_eval itself prints no CI):

| class | gold | baseline | candidate | delta fixed [95% CI] | delta highlighted [95% CI] |
|---|---|---|---|---|---|
| commas | 131 | 79 (4) | 76 (4) | -3 [-8, 2] | 0 |
| endings | 127 | 51 (22) | 54 (19) | +3 [-3, 10] | -3 [-10, 3] |
| joined / hyphen | 35 | 18 (9) | 18 (9) | 0 [-4, 4] | 0 [-3, 3] |
| spelling / word | 20 | 8 (2) | 8 (2) | 0 | 0 |
| case | 17 | 2 (0) | 2 (0) | 0 | 0 |
| several words | 15 | 2 (3) | 2 (3) | 0 | 0 |
| other punctuation | 4 | 0 | 0 | 0 | 0 |
| all | 349 | 160 (40) | 160 (37) | 0 [-9, 9] | -3 [-10, 4] |

False "error" delta +8 findings, CI [0, 16] (dev +2 [-2, 7], test +6 [0, 12]). False "check" +2 [-2, 6]. Official
false error 2 -> 3, check 13 -> 12.

SAGE rules, right / place / false (old gold):

| rule | baseline | candidate |
|---|---|---|
| SAGE_ENDING (vote) | 12 / 1 / 2 | 15 / 0 / 1 |
| SAGE_TYPO | 4 / 0 / 0 | 4 / 0 / 11 |
| SAGE_JOIN | 10 / 0 / 1 | 10 / 0 / 0 |
| SAGE_COMMA_DEL (vote) | 9 / 0 / 1 | 6 / 0 / 0 |
| SAGE_CASE_LOWER | 2 / 0 / 0 | 2 / 0 / 0 |

The only real gain is 3 more endings voted correctly. It is paid for by 3 fewer comma deletions and by 11 false typo
corrections (the large model rewrites more words that the dictionary does not know; the typo class is kept on its own,
without voting, so these go straight to "error"). The held-out score parity (0.7743 vs 0.7715) is confirmed: the
extra size does not turn into engine gain, because the policy keeps only a few edit classes and both models agree on them.

## Cost

SAGE alone (150 random gold sentences, mean 139 chars, 2 threads, CPUQuota=200%, venv-app, onnxruntime 1.30):

| | s per sentence (mean / median / p90) | RSS after load | peak RSS |
|---|---|---|---|
| 95m int8 | 0.25 / 0.24 / 0.39 | 628 MB | 663 MB |
| large int8 | 0.95 / 0.80 / 1.65 | 2754 MB | 2754 MB |

(The same measurement in venv-train, onnxruntime 1.19, gave 0.24 and 0.97.) Large is 3.8x slower and 4.2x bigger.

Whole check process, `ru_maxrss` of engine_eval (all stages, models loaded one at a time):
baseline 1954 MB, candidate 3143 MB (+1.19 GB). The engine peaks at about 1.3 GB on Win7 vs 1.8 GB on Linux today; by the same
offset the candidate would be about 2.5 GB on Win7 with a 4 GB machine, and loading it needs ~2.7 GB for the SAGE step alone.
Wall time of the full evaluation (shared machine, other jobs ran at the same time, so only the ratio counts):
baseline 3612 s, candidate 8439 s for 4663 sentences, that is 0.77 vs 1.81 s per sentence for all stages, 2.3x. On the
Win7 target (about 0.5 s per sentence today) this would be roughly 1.2-1.5 s per sentence.

The int8 file agrees with fp32 on 97 of 100 sentences (export.log). Disk: 1.45 GB vs 0.48 GB.

## Verdict

Quality gain: 0 fixed edits, +3 endings / -3 commas inside the noise, +8 false errors. Cost: 3.8x SAGE time, +1.2 GB peak,
near the 3 GB line on Linux. The gain does not justify the cost. Keep SAGE-95m (sage-b). Not tried and not claimed: a
different voting policy for the large model (e.g. dropping its SAGE_TYPO, keeping only votes), which would at best add
about +3 endings and still cost the full memory and time.
