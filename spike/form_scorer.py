"""Throwaway spike: masked-LM scoring of alternative word forms (rubert-tiny2).

For every inflectable word, pymorphy proposes the other forms of the same
lexeme; each variant is scored by pseudo-log-likelihood of the word's own
subtokens. A large gain of the best alternative over the author's form means
the author's form probably does not fit the sentence.
"""
import re

import pymorphy3
import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

morph = pymorphy3.MorphAnalyzer()
WORD = re.compile(r"[А-Яа-яЁё]+")
POS = {"NOUN", "ADJF", "PRTF", "VERB"}
FEATURES = ("case", "number", "gender", "person")


class FormScorer:
    def __init__(self, path, threads=8):
        torch.set_num_threads(threads)
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForMaskedLM.from_pretrained(path).eval()

    def alternatives(self, word):
        best = [p for p in morph.parse(word) if p.score >= 0.1 and p.tag.POS in POS]
        forms = set()
        for p in best:
            for f in p.lexeme:
                if f.tag.POS != p.tag.POS or f.word == word.lower():
                    continue
                if p.tag.POS == "VERB" and (f.tag.tense != p.tag.tense or f.tag.mood != p.tag.mood):
                    continue
                if p.tag.POS in ("ADJF", "PRTF") and "Supr" in f.tag:
                    continue
                forms.add(f.word)
        return sorted(forms)

    def _pll_batch(self, variants):
        """variants: list of (prefix, word, suffix). Returns PLL of the word's subtokens for each."""
        inputs, owners, targets = [], [], []
        for k, (prefix, word, suffix) in enumerate(variants):
            pre = self.tok(prefix, add_special_tokens=False)["input_ids"]
            mid = self.tok(word, add_special_tokens=False)["input_ids"]
            suf = self.tok(suffix, add_special_tokens=False)["input_ids"]
            ids = [self.tok.cls_token_id] + pre + mid + suf + [self.tok.sep_token_id]
            for j in range(len(mid)):
                masked = list(ids)
                pos = 1 + len(pre) + j
                masked[pos] = self.tok.mask_token_id
                inputs.append(masked)
                owners.append(k)
                targets.append((pos, mid[j]))
        width = max(len(x) for x in inputs)
        batch = torch.full((len(inputs), width), self.tok.pad_token_id)
        attn = torch.zeros((len(inputs), width), dtype=torch.long)
        for r, x in enumerate(inputs):
            batch[r, :len(x)] = torch.tensor(x)
            attn[r, :len(x)] = 1
        scores = [0.0] * len(variants)
        with torch.inference_mode():
            for start in range(0, len(inputs), 256):
                logits = self.model(input_ids=batch[start:start + 256], attention_mask=attn[start:start + 256]).logits
                logp = logits.log_softmax(-1)
                for r in range(logp.shape[0]):
                    pos, tid = targets[start + r]
                    scores[owners[start + r]] += float(logp[r, pos, tid])
        return scores

    def score_sentence(self, text):
        """For each candidate word: (start, end, word, best_alternative, gain)."""
        result = []
        for m in WORD.finditer(text):
            word = m.group(0)
            if len(word) < 3 or word[0].isupper():
                continue
            alts = self.alternatives(word)
            if not alts:
                continue
            prefix, suffix = text[:m.start()], text[m.end():]
            scores = self._pll_batch([(prefix, word, suffix)] + [(prefix, a, suffix) for a in alts])
            best = max(range(1, len(scores)), key=lambda i: scores[i])
            result.append((m.start(), m.end(), word, alts[best - 1], scores[best] - scores[0]))
        return result
