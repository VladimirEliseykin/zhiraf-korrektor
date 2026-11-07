"""Normalisation used when comparing a correction with the gold: no heavy imports, so light scripts can use it."""
import re


def normalize(text):
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace("«", '"').replace("»", '"')
    text = re.sub(r"\b([А-ЯA-Z])\. (?=[А-ЯA-Z]\.)", r"\1.", text)
    return re.sub(r"\s+", " ", text).strip()
