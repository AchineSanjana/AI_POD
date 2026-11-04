"""In-memory telemetry collector and non-blocking background flusher.

Records:
1. Recommendation requests: {ts, customer_id, top_n, fallback, reason, latency_ms, source, recommended_products}
2. Tracked events: {ts, event_type, product_id, session_id, customer_id}

Writes each batch to a unique part file:
data/telemetry/{tenant_id}/{YYYY-MM-DD}/part-{utc_timestamp}-{pid}-{random}.jsonl
via StorageBackend, preventing write collisions across workers or S3.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import secrets
import threading
from typing import Any

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import load_config

logger = logging.getLogger(__name__)

_BUFFER: list[dict[str, Any]] = []
_BUFFER_LOCK = threading.Lock()

_FLUSHER_THREAD: threading.Thread | None = None
_FLUSHER_STOP_EVENT = threading.Event()


def record_recommendation(
    tenant_id: str,
    customer_id: str,
    top_n: int,
    fallback: bool,
    reason: str | None,
    latency_ms: float,
    source: str = "live",
    recommended_products: list[str] | None = None,
) -> None:
    """Record a recommendation request in the telemetry buffer without raising or blocking."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        rec = {
            "type": "recommendation",
            "tenant_id": str(tenant_id),
            "ts": now_iso,
            "customer_id": str(customer_id),
            "top_n": int(top_n),
            "fallback": bool(fallback),
            "reason": str(reason) if reason else None,
            "latency_ms": round(float(latency_ms), 2),
            "source": str(source or "live"),
            "recommended_products": [str(p) for p in (recommended_products or [])],
        }
        with _BUFFER_LOCK:
            _BUFFER.append(rec)
    except Exception as exc:
        logger.debug("Failed recording recommendation telemetry: %s", exc)


def record_event(
    tenant_id: str,
    event_type: str,
    product_id: str | None,
    session_id: str | None,
    customer_id: str | None = None,
    ts: str | None = None,
) -> None:
    """Record an interaction event in the telemetry buffer without raising or blocking."""
    try:
        now_iso = ts or datetime.now(timezone.utc).isoformat()
        rec = {
            "type": "event",
            "tenant_id": str(tenant_id),
            "ts": now_iso,
            "event_type": str(event_type),
            "product_id": str(product_id) if product_id else None,
            "session_id": str(session_id) if session_id else None,
            "customer_id": str(customer_id) if customer_id else None,
        }
        with _BUFFER_LOCK:
            _BUFFER.append(rec)
    except Exception as exc:
        logger.debug("Failed recording interaction event telemetry: %s", exc)


def flush_telemetry(storage: StorageBackend | None = None) -> int:
    """Flush all buffered telemetry records to StorageBackend part files.

    Writes to:
    data/telemetry/{tenant_id}/{YYYY-MM-DD}/part-{utc_timestamp}-{pid}-{random}.jsonl
    """
    with _BUFFER_LOCK:
        if not _BUFFER:
            return 0
        items = list(_BUFFER)
        _BUFFER.clear()

    if not items:
        return 0

    if storage is None:
        try:
            cfg = load_config()
            storage = get_storage_backend(cfg)
        except Exception as exc:
            logger.warning("Could not initialize storage for telemetry flush: %s", exc)
            # Re-queue on failure
            with _BUFFER_LOCK:
                _BUFFER.extend(items)
            return 0

    # Group records by (tenant_id, date_str)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for it in items:
        t_id = it.get("tenant_id") or "unknown"
        ts = it.get("ts") or datetime.now(timezone.utc).isoformat()
        date_str = ts[:10]  # YYYY-MM-DD
        grouped[(t_id, date_str)].append(it)

    flushed_count = 0
    now_utc = datetime.now(timezone.utc)
    ts_compact = now_utc.strftime("%Y%m%d%H%M%S%f")
    pid = os.getpid()

    for (t_id, date_str), records in grouped.items():
        try:
            rand_hex = secrets.token_hex(4)
            part_filename = f"part-{ts_compact}-{pid}-{rand_hex}.jsonl"
            storage_path = f"data/telemetry/{t_id}/{date_str}/{part_filename}"

            lines = [json.dumps(r) for r in records]
            content = ("\n".join(lines) + "\n").encode("utf-8")
            storage.write_file(storage_path, content)
            flushed_count += len(records)
        except Exception as exc:
            logger.warning("Failed flushing telemetry part for tenant %s: %s", t_id, exc)

    return flushed_count


def _flusher_loop(interval: float) -> None:
    while not _FLUSHER_STOP_EVENT.wait(interval):
        try:
            flush_telemetry()
        except Exception as exc:
            logger.warning("Error in background telemetry flusher: %s", exc)


def start_telemetry_flusher(interval: float = 5.0, interval_seconds: float | None = None) -> None:
    """Start the background telemetry flush thread."""
    if interval_seconds is not None:
        interval = interval_seconds
    global _FLUSHER_THREAD
    if _FLUSHER_THREAD is not None and _FLUSHER_THREAD.is_alive():
        return

    _FLUSHER_STOP_EVENT.clear()
    _FLUSHER_THREAD = threading.Thread(
        target=_flusher_loop,
        args=(interval,),
        name="telemetry-flusher",
        daemon=True,
    )
    _FLUSHER_THREAD.start()
    logger.info("Started background telemetry flusher (interval=%.1fs)", interval)


def stop_telemetry_flusher() -> None:
    """Stop the background telemetry flush thread and join."""
    global _FLUSHER_THREAD
    _FLUSHER_STOP_EVENT.set()
    if _FLUSHER_THREAD is not None:
        _FLUSHER_THREAD.join(timeout=3.0)
        _FLUSHER_THREAD = None
    logger.info("Stopped background telemetry flusher")


def clear_telemetry_buffer() -> None:
    """Clear in-memory buffer (primarily for test isolation)."""
    with _BUFFER_LOCK:
        _BUFFER.clear()
