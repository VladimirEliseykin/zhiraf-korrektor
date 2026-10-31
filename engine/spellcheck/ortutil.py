"""onnxruntime session settings shared by the taggers and SAGE (memory first: a 4 GB machine)."""
import ctypes
import gc


def session_options(ort, threads):
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    # the arena keeps every size it ever grew to and the memory pattern pre-plans a block per input shape: with a new
    # sentence length at every call both only pin memory (outputs are the same either way)
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    return options


def release_memory():
    """After a model is dropped: collect it and hand the freed heap pages back to the system (glibc; no-op elsewhere)."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
