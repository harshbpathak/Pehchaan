import os

import pytest

from pehchan.models import Embedder, RelevanceModel
from pehchan.semantic import classify


@pytest.mark.models
@pytest.mark.skipif(
    os.getenv("PEHCHAN_MODELS") != "1", reason="requires downloaded local checkpoints"
)
def test_real_local_models_paraphrase_and_negation():
    import numpy as np

    embedder = Embedder()
    vectors = embedder.encode(
        [
            "5G technology is spreading coronavirus",
            "Coronavirus is being spread by 5G technology.",
            "Purple carrots generate satellite navigation signals.",
        ]
    )
    scores = np.array(vectors) @ np.array(vectors).T
    assert scores[0, 1] > 0.8 and scores[0, 1] > scores[0, 2]
    nli = RelevanceModel()
    premise = "5G technology is spreading coronavirus"
    positive = "Coronavirus is being spread by 5G technology."
    negative = "5G technology does not spread coronavirus."
    outputs = nli.assess_pairs(
        [(premise, positive), (positive, premise), (premise, negative), (negative, premise)]
    )
    assert classify(outputs[0], outputs[1], float(scores[0, 1])).relation == "SAME_PROPOSITION"
    assert classify(outputs[2], outputs[3], 0.8).relation == "CONTRADICTION"
