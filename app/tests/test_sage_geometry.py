import collections
import os

import pytest

import zhiraf  # noqa: F401  (puts the engine on sys.path)
from spellcheck.sage import past_geometry

Input = collections.namedtuple("Input", "name shape")


def decoder_inputs(heads, head_dim=64):
    inputs = [Input("encoder_attention_mask", ["batch_size", "encoder_sequence_length"]),
              Input("input_ids", ["batch_size", "decoder_sequence_length"])]
    for layer in range(2):
        for kind in ("decoder.key", "decoder.value", "encoder.key", "encoder.value"):
            inputs.append(Input("past_key_values.%d.%s" % (layer, kind),
                                ["batch_size", heads, "past_decoder_sequence_length", head_dim]))
    return inputs


def test_95m_geometry():
    assert past_geometry(decoder_inputs(6)) == (6, 64)


def test_large_geometry():
    assert past_geometry(decoder_inputs(16)) == (16, 64)


def test_symbolic_shape_falls_back_to_the_95m_values():
    inputs = [Input("past_key_values.0.decoder.key", ["batch_size", "heads", "length", "dim"])]
    assert past_geometry(inputs) == (6, 64)
    assert past_geometry([]) == (6, 64)


LARGE = os.environ.get("ZHIRAF_SAGE_LARGE", "")


@pytest.mark.skipif(not os.path.exists(os.path.join(LARGE, "tokenizer.json")),
                    reason="set ZHIRAF_SAGE_LARGE to the large SAGE folder")
def test_large_tokenizer_adds_the_lm_prefix():
    from tokenizers import Tokenizer
    ids = Tokenizer.from_file(os.path.join(LARGE, "tokenizer.json")).encode("Привет, мир.").ids
    assert ids[0] == 50357


@pytest.mark.skipif(not os.path.exists(os.path.join(LARGE, "decoder_model_merged.onnx")),
                    reason="set ZHIRAF_SAGE_LARGE to the large SAGE folder")
def test_large_model_loads_with_its_own_geometry():
    from spellcheck.sage import Sage
    model = Sage(LARGE, threads=2)
    assert (model.num_heads, model.head_dim) == (16, 64)
    assert model.correct("Привет, мир.").startswith("Привет")
