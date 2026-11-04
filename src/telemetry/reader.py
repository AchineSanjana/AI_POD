"""Telemetry reader and aggregation engine.

Reads part files for a tenant over requested date ranges:
data/telemetry/{tenant_id}/{YYYY-MM-DD}/part-*.jsonl
Aggregates recommendations, event volumes, and top recommended products.
Caches aggregate results for 30 seconds and caps files read per request.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import logging
import time
from typing import Any

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.telemetry.collector import _BUFFER, _BUFFER_LOCK
from src.utils.config import load_config

logger = logging.getLogger(__name__)

# TTL Cache: (tenant_id, days) -> (cached_at_timestamp, result_dict)
_AGGREGATE_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 30.0
MAX_FILES_PER_REQUEST = 500


def clear_telemetry_cache() -> None:
    """Clear in-memory telemetry reader cache (useful for tests)."""
    _AGGREGATE_CACHE.clear()


def _get_product_names(tenant_id: str, storage: StorageBackend) -> dict[str, str]:
    """Load product_id -> product_name mapping from processed storage."""
    product_path = f"data/processed/{tenant_id}/products.csv"
    if not storage.exists(product_path) and tenant_id == "telco_default":
        if storage.exists("data/processed/products.csv"):
            product_path = "data/processed/products.csv"

    if not storage.exists(product_path):
        return {}

    try:
        content = storage.read_file(product_path)
        text = content.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return {}

        norm_header = [h.strip() for h in header]
        id_idx = 0
        name_idx = None

        for candidate in ("product_id", "item_id", "StockCode", "id"):
            if candidate in norm_header:
                id_idx = norm_header.index(candidate)
                break

        for candidate in ("product_name", "title", "Description", "name"):
            if candidate in norm_header:
                name_idx = norm_header.index(candidate)
                break

        if name_idx is None:
            return {}

        lookup = {}
        for row in reader:
            if len(row) > max(id_idx, name_idx):
                pid = row[id_idx].strip()
                name = row[name_idx].strip()
                if pid and name:
                    lookup[pid] = name
        return lookup
    except Exception as exc:
        logger.debug("Failed reading product names for %s: %s", tenant_id, exc)
        return {}


def get_tenant_telemetry(
    tenant_id: str,
    days: int = 7,
    storage: StorageBackend | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Aggregate telemetry records for a tenant across the past N days.

    Caches results for 30 seconds.
    Excludes test traffic (source='test').
    """
    now_mono = time.monotonic()
    cache_key = (tenant_id, days)

    if use_cache and cache_key in _AGGREGATE_CACHE:
        cached_at, data = _AGGREGATE_CACHE[cache_key]
        if now_mono - cached_at < _CACHE_TTL_SECONDS:
            return data

    if storage is None:
        cfg = load_config()
        storage = get_storage_backend(cfg)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    today_str = today.strftime("%Y-%m-%d")

    date_list = [today - timedelta(days=i) for i in reversed(range(days))]
    date_strs = [d.strftime("%Y-%m-%d") for d in date_list]

    total_recommendations = 0
    requests_today = 0
    fallback_count = 0
    product_rec_counter: Counter[str] = Counter()
    daily_events: dict[str, Counter[str]] = {ds: Counter() for ds in date_strs}

    files_read = 0

    # 1. Read persisted part files from storage
    for ds in date_strs:
        if files_read >= MAX_FILES_PER_REQUEST:
            break
        prefix = f"data/telemetry/{tenant_id}/{ds}/"
        part_files = storage.list_files(prefix)
        for pf in part_files:
            if files_read >= MAX_FILES_PER_REQUEST:
                break
            files_read += 1
            try:
                content = storage.read_file(pf)
                for line in content.decode("utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    r_type = rec.get("type")

                    if r_type == "recommendation":
                        # CRITICAL: Exclude test traffic from all dashboard metrics
                        if rec.get("source") == "test":
                            continue
                        total_recommendations += 1
                        rec_date = rec.get("ts", "")[:10]
                        if rec_date == today_str:
                            requests_today += 1
                        if rec.get("fallback"):
                            fallback_count += 1
                        for pid in rec.get("recommended_products", []):
                            if pid:
                                product_rec_counter[str(pid)] += 1

                    elif r_type == "event":
                        rec_date = rec.get("ts", "")[:10]
                        if rec_date in daily_events:
                            ev_type = rec.get("event_type", "view")
                            daily_events[rec_date][ev_type] += 1
            except Exception as exc:
                logger.debug("Failed parsing telemetry part file %s: %s", pf, exc)

    # 2. Merge un-flushed in-memory buffer records for real-time responsiveness
    with _BUFFER_LOCK:
        buffered = list(_BUFFER)

    for rec in buffered:
        if rec.get("tenant_id") != tenant_id:
            continue
        r_type = rec.get("type")
        if r_type == "recommendation":
            if rec.get("source") == "test":
                continue
            total_recommendations += 1
            rec_date = rec.get("ts", "")[:10]
            if rec_date == today_str:
                requests_today += 1
            if rec.get("fallback"):
                fallback_count += 1
            for pid in rec.get("recommended_products", []):
                if pid:
                    product_rec_counter[str(pid)] += 1
        elif r_type == "event":
            rec_date = rec.get("ts", "")[:10]
            if rec_date in daily_events:
                ev_type = rec.get("event_type", "view")
                daily_events[rec_date][ev_type] += 1

    # Product names enrichment
    prod_names = _get_product_names(tenant_id, storage)
    top_products = []
    for pid, count in product_rec_counter.most_common(5):
        top_products.append({
            "product_id": pid,
            "product_name": prod_names.get(pid, pid),
            "count": count,
        })

    # Daily events summary
    events_by_day = []
    total_events = 0
    for ds in date_strs:
        counts = daily_events[ds]
        day_total = sum(counts.values())
        total_events += day_total
        events_by_day.append({
            "date": ds,
            "counts": dict(counts),
            "total": day_total,
        })

    fallback_rate = (
        round(fallback_count / total_recommendations, 4)
        if total_recommendations > 0
        else None
    )

    result = {
        "days": days,
        "total_recommendations": total_recommendations,
        "requests_today": requests_today,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_rate,
        "ctr": None,  # Computed honestly only if tracking click-attribution; else null
        "total_events": total_events,
        "events_by_day": events_by_day,
        "top_products": top_products,
    }

    if use_cache:
        _AGGREGATE_CACHE[cache_key] = (now_mono, result)

    return result


def get_tenant_events(
    tenant_id: str,
    limit: int = 20,
    storage: StorageBackend | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the latest real interaction events for a tenant, sorted newest first."""
    if storage is None:
        cfg = load_config()
        storage = get_storage_backend(cfg)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    events: list[dict[str, Any]] = []

    # 1. Un-flushed in-memory buffer
    with _BUFFER_LOCK:
        for rec in reversed(_BUFFER):
            if rec.get("tenant_id") == tenant_id and rec.get("type") == "event":
                events.append({
                    "ts": rec.get("ts"),
                    "event_type": rec.get("event_type"),
                    "product_id": rec.get("product_id"),
                    "session_id": rec.get("session_id"),
                    "customer_id": rec.get("customer_id"),
                })
                if len(events) >= limit * 2:
                    break

    # 2. Check recent days from storage (today and yesterday)
    recent_dates = [today - timedelta(days=i) for i in range(3)]
    for d in recent_dates:
        if len(events) >= limit * 2:
            break
        ds = d.strftime("%Y-%m-%d")
        prefix = f"data/telemetry/{tenant_id}/{ds}/"
        part_files = sorted(storage.list_files(prefix), reverse=True)
        for pf in part_files:
            if len(events) >= limit * 2:
                break
            try:
                content = storage.read_file(pf)
                lines = content.decode("utf-8", errors="replace").splitlines()
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("type") == "event":
                        events.append({
                            "ts": rec.get("ts"),
                            "event_type": rec.get("event_type"),
                            "product_id": rec.get("product_id"),
                            "session_id": rec.get("session_id"),
                            "customer_id": rec.get("customer_id"),
                        })
                        if len(events) >= limit * 2:
                            break
            except Exception as exc:
                logger.debug("Failed reading event part %s: %s", pf, exc)

    # Sort all collected events by ts descending and limit
    events.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
    return events[:limit]

