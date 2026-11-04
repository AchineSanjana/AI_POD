"""Telemetry module for AI_POD.

Collects non-blocking, multi-worker safe telemetry for recommendation requests
and interaction events, partitioned into daily part files.
"""

from __future__ import annotations

from src.telemetry.collector import (
    clear_telemetry_buffer,
    flush_telemetry,
    record_event,
    record_recommendation,
    start_telemetry_flusher,
    stop_telemetry_flusher,
)
from src.telemetry.reader import (
    clear_telemetry_cache,
    get_tenant_events,
    get_tenant_telemetry,
)
from src.telemetry.retention import cleanup_old_telemetry

__all__ = [
    "clear_telemetry_buffer",
    "clear_telemetry_cache",
    "cleanup_old_telemetry",
    "flush_telemetry",
    "get_tenant_events",
    "get_tenant_telemetry",
    "record_event",
    "record_recommendation",
    "start_telemetry_flusher",
    "stop_telemetry_flusher",
]

