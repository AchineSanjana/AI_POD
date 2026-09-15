"""Storage abstraction module supporting local and cloud backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.storage.base_storage import StorageBackend
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage

if TYPE_CHECKING:
    pass


def get_storage_backend(config: dict | None = None) -> StorageBackend:
    """Instantiate and return the configured StorageBackend implementation.

    Reads ``config['storage']`` and environment variables:
      - ``backend``: 'local' (default) or 's3' (overridden by $STORAGE_BACKEND)
      - ``s3_bucket``: S3 bucket name (overridden by $STORAGE_S3_BUCKET or $S3_BUCKET)
      - ``s3_prefix``: Root prefix (overridden by $STORAGE_S3_PREFIX or $S3_PREFIX)
      - ``local_base_dir``: Root for local storage (overridden by $STORAGE_LOCAL_BASE_DIR)

    Args:
        config: Loaded config dict. If None, loaded via ``load_config()``.

    Returns:
        StorageBackend: An instance of :class:`LocalStorage` or :class:`S3Storage`.

    Raises:
        ValueError: If backend is unknown or required settings are missing.
    """
    if config is None:
        from src.utils.config import load_config
        config = load_config()

    storage_cfg = config.get("storage", {})
    backend = os.environ.get(
        "STORAGE_BACKEND", storage_cfg.get("backend", "local")
    ).strip().lower()

    if backend == "local":
        base_dir = os.environ.get(
            "STORAGE_LOCAL_BASE_DIR", storage_cfg.get("local_base_dir")
        )
        return LocalStorage(base_dir=base_dir)
    elif backend == "s3":
        bucket_name = os.environ.get(
            "STORAGE_S3_BUCKET",
            os.environ.get("S3_BUCKET", storage_cfg.get("s3_bucket")),
        )
        if not bucket_name:
            raise ValueError(
                "Missing required 'storage.s3_bucket' in config "
                "or 'STORAGE_S3_BUCKET' env var when backend is 's3'."
            )
        prefix = os.environ.get(
            "STORAGE_S3_PREFIX",
            os.environ.get("S3_PREFIX", storage_cfg.get("s3_prefix", "")),
        )
        return S3Storage(bucket_name=bucket_name, prefix=prefix)
    else:
        raise ValueError(
            f"Unsupported storage backend '{backend}'. Expected 'local' or 's3'."
        )


__all__ = [
    "StorageBackend",
    "LocalStorage",
    "S3Storage",
    "get_storage_backend",
]
