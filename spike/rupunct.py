"""Throwaway spike: RUPunct as a comma checker for existing text.

Strip punctuation, let the model restore it word by word, then compare the
restored commas with the author's commas. Returns per-word gap flags.
"""
import re
import sys

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

WORD = re.compile(r"[\w]+(?:[-‑][\w]+)*")


def author_commas(text):
    """Words of text and, for each word, whether the author put a comma right after it."""
    words, commas = [], []
    for m in WORD.finditer(text):
        words.append(m.group(0))
        tail = text[m.end():m.end() + 3]
        commas.append(tail.lstrip(" )»\"”").startswith(",") or tail.startswith(","))
    return words, commas


class RUPunct:
    def __init__(self, path, threads=4):
        torch.set_num_threads(threads)
        self.tokenizer = AutoTokenizer.from_pretrained(path, strip_accents=False, add_prefix_space=True)
        self.model = AutoModelForTokenClassification.from_pretrained(path).eval()
        self.labels = self.model.config.id2label

    def predict(self, words):
        """For each word: (comma_predicted, probability_of_comma)."""
        enc = self.tokenizer([w.lower() for w in words], is_split_into_words=True,
                             return_tensors="pt", truncation=True, max_length=512)
        with torch.inference_mode():
            logits = self.model(**enc).logits[0]
        probs = logits.softmax(-1)
        comma_ids = [i for i, l in self.labels.items() if l.endswith("_COMMA")]
        result = [(False, 0.0)] * len(words)
        seen = set()
        for pos, wid in enumerate(enc.word_ids()):
            if wid is None or wid in seen:
                continue
            seen.add(wid)
            p = float(probs[pos, comma_ids].sum())
            result[wid] = (p > 0.5, p)
        return result


if __name__ == "__main__":
    model = RUPunct(sys.argv[1])
    for text in sys.argv[2:]:
        words, commas = author_commas(text)
        for w, c, (pred, p) in zip(words, commas, model.predict(words)):
            mark = "" if c == pred else ("  <-- нет запятой у автора" if pred else "  <-- лишняя у автора?")
            print("%-20s автор:%-5s модель:%-5s p=%.2f%s" % (w, c, pred, p, mark))
