"""Stage names, their relative cost and model folders; no heavy imports, so the window can read them cheaply."""
import os

STAGES = ("rules", "commas", "forms", "sage")  # value per second of waiting: rules are instant, SAGE is slowest
STAGE_COST = {"rules": 0.003, "commas": 0.1, "forms": 0.1, "sage": 0.5}  # s/sentence per model pass, Windows 7 VM (job5)
MAX_STAGE_MODELS = 3


def model_folders(models_dir, stage):
    """Model folders of a tagger stage: <stage>, <stage>-2, <stage>-3 (a second and third opinion).

    The main folder is always first, present or not (a missing main model must fail loudly in its stage).
    An extra folder counts only when it holds a complete model, and the list stops at the first gap, so a
    missing or half-copied optional model just leaves a stage with fewer models.
    """
    folders = [os.path.join(models_dir, stage)]
    for k in range(2, MAX_STAGE_MODELS + 1):
        folder = os.path.join(models_dir, "%s-%d" % (stage, k))
        has_model = any(os.path.isfile(os.path.join(folder, n)) for n in ("model.onnx", "model-int8.onnx"))
        if not (has_model and os.path.isfile(os.path.join(folder, "labels.json"))):
            break
        folders.append(folder)
    return folders
