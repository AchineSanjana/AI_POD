"""Audit logging subsystem for tenant-managed product catalogue mutations.

Appends every change (who, when, action, product_ids_count, product_ids, details)
to unique part files under:
data/catalog/{tenant_id}/audit/{YYYY-MM-DD}/part-{timestamp_ms}-{pid}-{random}.jsonl
via StorageBackend, ensuring zero write collisions across uvicorn workers and S3.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import secrets
import time
from typing import Any

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend

logger = logging.getLogger(__name__)


def record_catalog_audit(
    tenant_id: str,
    who: str,
    action: str,
    product_ids: list[str],
    details: dict[str, Any] | None = None,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Record an audit entry for a catalog mutation in an isolated part file.

    Args:
        tenant_id: Tenant identifier.
        who: Identity/credential performing the action (API key or account ID).
        action: Name of the action (create, update, archive, restore, delete, bulk_*, upload_commit, undo, seed).
        product_ids: List of affected product IDs.
        details: Optional dictionary containing additional context.
        storage: Optional StorageBackend instance.

    Returns:
        The generated audit record dict.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")
    pid = os.getpid()
    ts_ms = int(time.time() * 1000)
    rand_hex = secrets.token_hex(4)

    record = {
        "tenant_id": str(tenant_id),
        "who": str(who),
        "when": now_iso,
        "action": str(action),
        "product_ids_count": len(product_ids),
        "product_ids": [str(pid_) for pid_ in product_ids[:100]],  # store up to 100 IDs for compactness
        "details": details or {},
    }

    if storage is None:
        storage = get_storage_backend()

    audit_path = (
        f"data/catalog/{tenant_id}/audit/{date_str}/part-{ts_ms}-{pid}-{rand_hex}.jsonl"
    )

    try:
        content = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        storage.write_file(audit_path, content)
    except Exception as exc:
        logger.warning(
            "Failed writing catalog audit record for tenant '%s' to '%s': %s",
            tenant_id,
            audit_path,
            exc,
        )

    return record


def get_catalog_history(
    tenant_id: str,
    limit: int = 50,
    storage: StorageBackend | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the most recent audit records for a tenant, sorted newest first.

    Args:
        tenant_id: Tenant identifier.
        limit: Maximum number of history records to return (default: 50).
        storage: Optional StorageBackend instance.

    Returns:
        List of audit record dicts sorted by 'when' descending.
    """
    if storage is None:
        storage = get_storage_backend()

    prefix = f"data/catalog/{tenant_id}/audit/"
    try:
        files = storage.list_files(prefix)
    except Exception as exc:
        logger.warning("Failed listing audit files for tenant '%s': %s", tenant_id, exc)
        return []

    if not files:
        return []

    # Read part files (only JSONL files)
    records: list[dict[str, Any]] = []
    # Reverse sort by path to read newest dates/files first
    sorted_files = sorted(files, reverse=True)

    for file_path in sorted_files:
        if not file_path.endswith(".jsonl"):
            continue
        try:
            raw_bytes = storage.read_file(file_path)
            if not raw_bytes:
                continue
            text = raw_bytes.decode("utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    records.append(data)
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Failed reading audit file '%s': %s", file_path, exc)

        # Optimization: stop early if we have collected plenty of records
        if len(records) >= limit * 3:
            break

    # Sort descending by timestamp
    records.sort(key=lambda r: r.get("when", ""), reverse=True)
    return records[:limit]

