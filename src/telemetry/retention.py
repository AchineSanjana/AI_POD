"""Telemetry retention cleanup.

Deletes day folders and part files older than telemetry.retention_days (default 30).
Called during scheduled retraining or administrative maintenance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import load_config

logger = logging.getLogger(__name__)


def cleanup_old_telemetry(
    tenant_id: str | None = None,
    retention_days: int | None = None,
    storage: StorageBackend | None = None,
    config: dict[str, Any] | None = None,
) -> int:
    """Delete telemetry part files older than retention_days.

    Args:
        tenant_id: Optional tenant to clean up. If None, cleans across all tenants.
        retention_days: Optional override for retention days (defaults to config value or 30).
        storage: Optional storage backend instance.
        config: Optional loaded configuration dictionary.

    Returns:
        int: Number of deleted part files.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    if retention_days is None:
        retention_days = int(
            config.get("telemetry", {}).get("retention_days", 30)
        )

    if storage is None:
        storage = get_storage_backend(config)

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d")

    # Discover target files
    if tenant_id:
        prefix = f"data/telemetry/{tenant_id}/"
    else:
        prefix = "data/telemetry/"

    candidate_files = storage.list_files(prefix)
    deleted_count = 0

    for path in candidate_files:
        # Expected path pattern: data/telemetry/{tenant_id}/{YYYY-MM-DD}/part-*.jsonl
        parts = path.replace("\\", "/").split("/")
        if len(parts) >= 4 and parts[0] == "data" and parts[1] == "telemetry":
            date_str = parts[3]
            # Check if valid YYYY-MM-DD and older than cutoff_date
            if len(date_str) == 10 and date_str < cutoff_date:
                try:
                    if storage.delete_file(path):
                        deleted_count += 1
                except Exception as exc:
                    logger.debug("Failed deleting old telemetry file %s: %s", path, exc)

    logger.info(
        "Cleaned up %d telemetry part files older than %d days (cutoff=%s, tenant=%s)",
        deleted_count,
        retention_days,
        cutoff_date,
        tenant_id or "all",
    )
    return deleted_count

