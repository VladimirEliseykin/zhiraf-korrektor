"""Rewrite ONNX models so that the weights live in a side file (<name>.onnx.data) next to the graph.

    python to_external.py SRC_MODELS_DIR DST_MODELS_DIR [folder ...]

onnxruntime maps such a file instead of reading it into the process: the pages are loaded on first use, the
embedding rows nobody asks for are never read and the system can drop a page under memory pressure. Peak memory of
a 1.7 GB ruBERT-large session falls from ~2.2 GB to ~1.3 GB; the graph and the weights are the same bytes, so
outputs are bit-identical. Copies the other files of each folder (tokenizer, labels). Needs: onnx (not in venv-app).
"""
import os
import shutil
import sys

import onnx

THRESHOLD = 1024  # tensors smaller than this stay inside the graph


def convert(src, dst):
    model = onnx.load(src)
    onnx.save_model(model, dst, save_as_external_data=True, all_tensors_to_one_file=True,
                    location=os.path.basename(dst) + ".data", size_threshold=THRESHOLD)


def main(argv):
    src_root, dst_root = argv[0], argv[1]
    folders = argv[2:] or sorted(d for d in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, d)))
    for folder in folders:
        os.makedirs(os.path.join(dst_root, folder), exist_ok=True)
        for name in os.listdir(os.path.join(src_root, folder)):
            src, dst = os.path.join(src_root, folder, name), os.path.join(dst_root, folder, name)
            if name.endswith(".onnx"):
                convert(src, dst)
            else:
                shutil.copyfile(src, dst)
        print("converted", folder, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
