"""The stage names and their relative cost; no heavy imports, so the window can read them cheaply."""

STAGES = ("rules", "commas", "forms", "sage")  # value per second of waiting: rules are instant, SAGE is slowest
STAGE_COST = {"rules": 0.003, "commas": 0.1, "forms": 0.1, "sage": 0.5}  # s/sentence, Windows 7 VM (job5)
