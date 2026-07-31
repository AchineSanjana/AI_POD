"""Persistence helpers for saving and loading trained models."""

from __future__ import annotations

from pathlib import Path

import joblib


def save_model(model: object, path: str | Path) -> Path:
    """Serialize a model to disk using joblib."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_path)
    return output_path


def load_model(path: str | Path) -> object:
    """Load a serialized model from disk using joblib."""
    return joblib.load(Path(path))