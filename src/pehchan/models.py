"""Pinned, local-only model inference. Downloading is an explicit setup action."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
NLI_MODEL = "cross-encoder/nli-deberta-v3-small"
NLI_REVISION = "fa2804872c3b4bd748f38c0185cc85775361e735"
DIMENSION = 384
MODEL_SPECS = {"embedding": (EMBED_MODEL, EMBED_REVISION), "nli": (NLI_MODEL, NLI_REVISION)}


def model_root() -> Path:
    return Path(
        os.getenv("PEHCHAN_MODEL_DIR", str(Path(__file__).resolve().parents[2] / ".models"))
    )


def download_models() -> dict:
    from huggingface_hub import snapshot_download

    result = {}
    for kind, (repo, revision) in MODEL_SPECS.items():
        destination = model_root() / kind
        snapshot_download(
            repo_id=repo,
            revision=revision,
            local_dir=str(destination),
            allow_patterns=["*.json", "model.safetensors", "*.model"],
        )
        (destination / "pehchan-model.json").write_text(
            json.dumps({"model": repo, "revision": revision}, indent=2) + "\n", encoding="utf-8"
        )
        result[kind] = {"model": repo, "revision": revision, "path": str(destination)}
    return result


def local_model_path(kind: str) -> Path:
    path = model_root() / kind
    marker = path / "pehchan-model.json"
    expected_model, expected_revision = MODEL_SPECS[kind]
    if not marker.exists() or not (path / "model.safetensors").exists():
        raise RuntimeError("Local models are missing. Run: python -m pehchan.cli download-models")
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    if metadata != {"model": expected_model, "revision": expected_revision}:
        raise RuntimeError("Local model revision mismatch; rerun download-models.")
    return path


def configure_torch():
    import torch

    torch.set_num_threads(max(1, min(8, int(os.getenv("PEHCHAN_TORCH_THREADS", "4")))))
    return torch


class Embedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer

        configure_torch()
        self.model = SentenceTransformer(
            str(local_model_path("embedding")),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        dimension = getattr(
            self.model, "get_embedding_dimension", self.model.get_sentence_embedding_dimension
        )()
        if dimension != DIMENSION:
            raise RuntimeError("Unexpected embedding dimension.")

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).tolist()


class RelevanceModel:
    def __init__(self):
        from sentence_transformers import CrossEncoder

        self.torch = configure_torch()
        self.model = CrossEncoder(
            str(local_model_path("nli")),
            device="cpu",
            max_length=512,
            local_files_only=True,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )

    def assess_pairs(self, pairs: list[tuple[str, str]]) -> list[dict]:
        if not pairs:
            return []
        # The published model uses contradiction, entailment, neutral in this order.
        scores = self.model.predict(
            pairs, batch_size=8, show_progress_bar=False, activation_fn=self.torch.nn.Softmax(dim=1)
        )
        return [
            dict(zip(("contradiction", "entailment", "neutral"), map(float, row))) for row in scores
        ]

    def fits(self, a: str, b: str) -> bool:
        return len(self.model.tokenizer(a, b, truncation=False)["input_ids"]) <= 512


@lru_cache(maxsize=2048)
def language(text: str) -> dict:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 0
    try:
        top = detect_langs(text)[0]
        return {"code": top.lang, "score": round(top.prob, 6)}
    except LangDetectException:
        return {"code": "und", "score": 0.0}
