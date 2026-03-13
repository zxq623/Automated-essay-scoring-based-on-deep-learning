from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
from transformers import RobertaConfig, RobertaModel, RobertaTokenizerFast


class MLP(torch.nn.Module):
    def __init__(self, input_size: int) -> None:
        super().__init__()
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(input_size, 256),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.3),
            torch.nn.Linear(256, 96),
            torch.nn.ReLU(),
            torch.nn.Dropout(0.3),
            torch.nn.Linear(96, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x)


@dataclass
class EssayScoreResult:
    essay_set: int
    scaled_score: float
    score: int


class EssayScoringService:
    def __init__(self, package_path: str | Path, device: str = "cpu") -> None:
        self.package_path = Path(package_path)
        self.device = torch.device(device)
        self.package = self._load_package(self.package_path)

        self.best_checkpoint = self.package["best_model"] if "best_model" in self.package else self.package
        self.tokenizer = self._build_tokenizer()
        self.score_ranges: dict[int, dict[str, int]] = self._build_score_ranges()

        self.roberta = self._build_roberta().to(self.device)
        input_size = self._infer_input_size()
        self.mlp = self._build_mlp(input_size).to(self.device)

    @staticmethod
    def _load_package(package_path: Path) -> dict[str, Any]:
        try:
            return torch.load(package_path, map_location="cpu", weights_only=False)
        except TypeError:
            return torch.load(package_path, map_location="cpu")

    def _build_score_ranges(self) -> dict[int, dict[str, int]]:
        if "score_ranges" in self.package:
            return {
                int(k): {"min": int(v["min"]), "max": int(v["max"])}
                for k, v in self.package["score_ranges"].items()
            }

        dataset_path = self.package_path.parent / "data" / "training_set_rel3.tsv"
        if dataset_path.exists():
            import pandas as pd

            df = pd.read_csv(dataset_path, sep="\t", encoding="latin1")
            out: dict[int, dict[str, int]] = {}
            grouped = df.groupby("essay_set")["domain1_score"]
            for essay_set, scores in grouped:
                out[int(essay_set)] = {"min": int(scores.min()), "max": int(scores.max())}
            return out

        scalers = self.best_checkpoint.get("score_scalers", {})
        return {int(k): {"min": 0, "max": 100} for k in scalers}

    def _infer_input_size(self) -> int:
        if "input_size" in self.package:
            return int(self.package["input_size"])
        return int(self.best_checkpoint["model_state_dict"]["layers.0.weight"].shape[1])

    def _build_roberta(self) -> RobertaModel:
        if "roberta_config" in self.package and "roberta_state_dict" in self.package:
            roberta = RobertaModel(RobertaConfig.from_dict(self.package["roberta_config"]))
            roberta.load_state_dict(self.package["roberta_state_dict"])
        else:
            # Fallback for lightweight checkpoints.
            roberta = RobertaModel.from_pretrained("roberta-base")
        roberta.eval()
        return roberta

    def _build_tokenizer(self):
        # Prefer tokenizer bundled in checkpoint, but fallback when the
        # serialized object is incompatible with current transformers version.
        if "tokenizer" in self.package:
            tokenizer = self.package["tokenizer"]
            try:
                tokenizer(
                    ["tokenizer health check"],
                    padding=True,
                    truncation=True,
                    max_length=32,
                    return_tensors="pt",
                )
                return tokenizer
            except Exception:
                pass
        return RobertaTokenizerFast.from_pretrained("roberta-base")

    def _build_mlp(self, input_size: int) -> MLP:
        model = MLP(input_size)
        model.load_state_dict(self.best_checkpoint["model_state_dict"])
        model.eval()
        return model

    def available_essay_sets(self) -> list[int]:
        return sorted(self.score_ranges.keys())

    def _embed_essays(self, essays: list[str], batch_size: int = 8) -> np.ndarray:
        vectors: list[np.ndarray] = []
        self.roberta.eval()

        with torch.no_grad():
            for idx in range(0, len(essays), batch_size):
                batch_essays = essays[idx : idx + batch_size]
                encoded = self.tokenizer(
                    batch_essays,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                encoded = {k: v.to(self.device) for k, v in encoded.items()}
                output = self.roberta(**encoded)
                batch_embeddings = output.last_hidden_state.mean(dim=1).cpu().numpy()
                vectors.append(batch_embeddings)

        if not vectors:
            return np.empty((0, self.roberta.config.hidden_size), dtype=np.float32)
        return np.concatenate(vectors, axis=0).astype(np.float32)

    def _predict_scaled(self, embeddings: np.ndarray, batch_size: int = 128) -> np.ndarray:
        tensor_embeddings = torch.from_numpy(np.asarray(embeddings)).float()
        loader = DataLoader(TensorDataset(tensor_embeddings), batch_size=batch_size, shuffle=False)

        preds: list[np.ndarray] = []
        self.mlp.eval()
        with torch.no_grad():
            for (inputs,) in loader:
                inputs = inputs.to(self.device)
                outputs = self.mlp(inputs)
                preds.append(outputs.cpu().numpy().ravel())

        if not preds:
            return np.array([], dtype=np.float32)
        return np.concatenate(preds)

    def _inverse_scale_score(self, scaled_pred: float, essay_set: int) -> float:
        scalers = self.best_checkpoint["score_scalers"]
        scaler_key = essay_set if essay_set in scalers else str(essay_set)
        if scaler_key not in scalers:
            raise ValueError(f"essay_set={essay_set} not found in score_scalers")

        mean = float(scalers[scaler_key]["mean"])
        std = float(scalers[scaler_key].get("std", scalers[scaler_key].get("scale", 1.0)))
        if std == 0:
            std = 1.0
        raw_score = scaled_pred * std + mean

        score_min = self.score_ranges[essay_set]["min"]
        score_max = self.score_ranges[essay_set]["max"]
        return float(np.clip(raw_score, score_min, score_max))

    def _normalize_score(self, score: float, essay_set: int) -> float:
        score_min = float(self.score_ranges[essay_set]["min"])
        score_max = float(self.score_ranges[essay_set]["max"])
        if score_max <= score_min:
            return 0.0
        norm = (score - score_min) / (score_max - score_min)
        norm = float(np.clip(norm, 0.0, 1.0))
        return norm * 100.0

    def _fuse_unknown_score(self, scaled_pred: float) -> int:
        normalized_scores: list[float] = []
        for essay_set in self.available_essay_sets():
            score = float(self._inverse_scale_score(scaled_pred, essay_set))
            normalized_scores.append(self._normalize_score(score, essay_set))
        if not normalized_scores:
            return 0
        final_score = float(np.mean(normalized_scores))
        return int(np.rint(np.clip(final_score, 0.0, 100.0)))

    def score(self, essays: list[str], essay_sets: list[int]) -> list[EssayScoreResult]:
        if len(essays) != len(essay_sets):
            raise ValueError("Length mismatch between essays and essay_sets")
        if not essays:
            return []

        for es in essay_sets:
            if es not in self.score_ranges:
                raise ValueError(
                    f"Unsupported essay_set={es}. Supported sets: {self.available_essay_sets()}"
                )

        embeddings = self._embed_essays(essays)
        scaled_preds = self._predict_scaled(embeddings)

        results: list[EssayScoreResult] = []
        for scaled_pred, essay_set in zip(scaled_preds, essay_sets):
            raw_score = float(self._inverse_scale_score(float(scaled_pred), essay_set))
            final_score = int(np.rint(raw_score))
            results.append(
                EssayScoreResult(
                    essay_set=essay_set,
                    scaled_score=float(scaled_pred),
                    score=final_score,
                )
            )

        return results

    def score_unknown(self, essays: list[str]) -> list[dict[str, Any]]:
        if not essays:
            return []

        embeddings = self._embed_essays(essays)
        scaled_preds = self._predict_scaled(embeddings)

        results: list[dict[str, Any]] = []
        for scaled_pred in scaled_preds:
            final_score = self._fuse_unknown_score(float(scaled_pred))
            results.append(
                {
                    "essay_set": "unknown",
                    "scaled_score": float(scaled_pred),
                    "score": final_score,
                }
            )
        return results
