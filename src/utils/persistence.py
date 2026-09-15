"""Persistence helpers for saving and loading trained models."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import joblib

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend


def save_model(
    model: Any,
    path: str | Path,
    storage: StorageBackend | None = None,
) -> Path:
    """Serialize a model using joblib and write via storage backend.

    Args:
        model: Any Python model object serializable by joblib.
        path: Destination path or key.
        storage: Optional StorageBackend instance. If None, default backend is used.

    Returns:
        Path: Path representation of the destination.
    """
    if storage is None:
        storage = get_storage_backend()

    buf = io.BytesIO()
    joblib.dump(model, buf)
    storage.write_file(str(path), buf.getvalue())
    return Path(path)


def load_model(
    path: str | Path,
    storage: StorageBackend | None = None,
) -> Any:
    """Load a serialized model from storage backend using joblib.

    Args:
        path: Path or key of the model artifact.
        storage: Optional StorageBackend instance. If None, default backend is used.

    Returns:
        Any: Deserialized model object.
    """
    if storage is None:
        storage = get_storage_backend()

    content = storage.read_file(str(path))
    buf = io.BytesIO(content)
    return joblib.load(buf)