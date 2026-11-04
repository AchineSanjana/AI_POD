"""Dashboard API endpoints for AI_POD tenant administration.

Provides:
- GET /v1/dashboard/overview: Health, status, metrics, requests today, active keys.
- GET /v1/dashboard/models: 4-model tournament leaderboard sorted by NDCG@5.
- GET /v1/dashboard/analytics: 7-day volume, top recommended products, fallback rate.
- GET /v1/dashboard/events: Latest real client interaction events.

Protected by `get_tenant_for_admin_action` (Bearer JWT or private sk- key).
Never fabricates metrics: unknown = null, nothing yet = 0 or empty list.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.api.auth import TENANT_KEY_RECORDS, get_tenant_for_admin_action, load_tenant_auth
from src.api.schemas import (
    DashboardAnalyticsResponse,
    DashboardDailyEvent,
    DashboardDatasetStats,
    DashboardEventItem,
    DashboardEventsResponse,
    DashboardModelLeaderboardItem,
    DashboardModelMetrics,
    DashboardModelsResponse,
    DashboardOverviewResponse,
    DashboardTopProduct,
)
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.telemetry.reader import _get_product_names, get_tenant_events, get_tenant_telemetry
from src.utils.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)

MODEL_METADATA = [
    {
        "id": "xgboost",
        "name": "Learned Ranking (XGBoost)",
        "color": "#10b981",
    },
    {
        "id": "hybrid",
        "name": "Dynamic Hybrid Ensemble",
        "color": "#06b6d4",
    },
    {
        "id": "collaborative",
        "name": "Collaborative Filtering (SVD)",
        "color": "#818cf8",
    },
    {
        "id": "content",
        "name": "Content-Based (Profile Cosine)",
        "color": "#3b82f6",
    },
]


def _format_time_ago(ts_str: str | None) -> str:
    """Format an ISO timestamp into a human-friendly relative time string."""
    if not ts_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff_sec = max(0.0, (now - dt).total_seconds())
        if diff_sec < 60:
            return "Just now"
        elif diff_sec < 3600:
            return f"{int(diff_sec // 60)}m ago"
        elif diff_sec < 86400:
            return f"{int(diff_sec // 3600)}h ago"
        elif diff_sec < 172800:
            return "Yesterday"
        else:
            return dt.strftime("%b %d")
    except Exception:
        return str(ts_str)[:16]


def _load_status_file(tenant_id: str, storage: StorageBackend) -> dict[str, Any] | None:
    """Read status/{tenant_id}.json from storage."""
    path = f"status/{tenant_id}.json"
    if not storage.exists(path):
        return None
    try:
        content = storage.read_file(path)
        return json.loads(content.decode("utf-8"))
    except Exception as exc:
        logger.debug("Failed reading status file for tenant %s: %s", tenant_id, exc)
        return None


def _get_or_compute_dataset_stats(
    tenant_id: str,
    status_data: dict[str, Any] | None,
    storage: StorageBackend,
) -> dict[str, int] | None:
    """Return dataset stats {customers, products, interactions}.

    If missing from status_data, computes line counts from processed CSVs
    and caches them in a separate file (status/{tenant_id}_dataset_stats.json).
    NEVER writes to status/{tenant_id}.json.
    """
    if status_data and "dataset" in status_data and isinstance(status_data["dataset"], dict):
        ds = status_data["dataset"]
        if ds.get("customers") is not None or ds.get("products") is not None or ds.get("interactions") is not None:
            return ds

    # Check separate cached stats file in storage
    stats_cache_path = f"status/{tenant_id}_dataset_stats.json"
    if storage.exists(stats_cache_path):
        try:
            cached_content = storage.read_file(stats_cache_path)
            cached_stats = json.loads(cached_content.decode("utf-8"))
            if isinstance(cached_stats, dict):
                return cached_stats
        except Exception as exc:
            logger.debug("Failed reading dataset stats cache for %s: %s", tenant_id, exc)

    cust_path = f"data/processed/{tenant_id}/customers.csv"
    prod_path = f"data/processed/{tenant_id}/products.csv"
    inter_path = f"data/processed/{tenant_id}/interactions.csv"

    if tenant_id == "telco_default":
        if not storage.exists(cust_path) and storage.exists("data/processed/customers.csv"):
            cust_path = "data/processed/customers.csv"
        if not storage.exists(prod_path) and storage.exists("data/processed/products.csv"):
            prod_path = "data/processed/products.csv"
        if not storage.exists(inter_path) and storage.exists("data/processed/interactions.csv"):
            inter_path = "data/processed/interactions.csv"

    has_any = storage.exists(cust_path) or storage.exists(prod_path) or storage.exists(inter_path)
    if not has_any:
        return None

    def _count_lines(p: str) -> int | None:
        if not storage.exists(p):
            return None
        try:
            raw = storage.read_file(p)
            lines = raw.decode("utf-8", errors="replace").splitlines()
            return max(0, len(lines) - 1)
        except Exception:
            return None

    c_count = _count_lines(cust_path)
    p_count = _count_lines(prod_path)
    i_count = _count_lines(inter_path)

    stats = {
        "customers": c_count,
        "products": p_count,
        "interactions": i_count,
    }

    try:
        stats_bytes = json.dumps(stats, indent=2).encode("utf-8")
        storage.write_file(stats_cache_path, stats_bytes)
    except Exception as exc:
        logger.debug("Failed writing dataset stats cache for %s: %s", tenant_id, exc)

    return stats


def _get_active_key_count(tenant_id: str) -> int:
    """Return count of active API keys issued for tenant."""
    if not TENANT_KEY_RECORDS:
        load_tenant_auth()
    return sum(
        1 for r in TENANT_KEY_RECORDS.values() if r.get("tenant_id") == tenant_id
    )


# ---------------------------------------------------------------------------
# GET /v1/dashboard/overview
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Get tenant dashboard overview",
    description="Retrieve high-level status, metrics, requests served today, and key counts.",
)
def get_dashboard_overview(
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> DashboardOverviewResponse:
    cfg = load_config()
    storage = get_storage_backend(cfg)

    status_data = _load_status_file(tenant_id, storage)
    ds_stats = _get_or_compute_dataset_stats(tenant_id, status_data, storage)

    # Telemetry requests today (excludes test traffic)
    telem = get_tenant_telemetry(tenant_id, days=1, storage=storage)
    requests_today = telem.get("requests_today", 0)

    # Active API keys
    key_count = _get_active_key_count(tenant_id)

    status_str = "not_started"
    ready = False
    winning_model = None
    winner_key = None
    metrics = None
    last_trained = None

    if status_data:
        status_str = status_data.get("status") or "not_started"
        ready = bool(status_data.get("ready", False))
        winning_model = status_data.get("winner_model")
        winner_key = status_data.get("winner_key")

        # Stalled check: if running/queued > 15m without update
        updated_at = status_data.get("updated_at")
        if status_str in ("queued", "running") and updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - dt).total_seconds() > 15 * 60:
                    status_str = "stalled"
            except (ValueError, TypeError):
                pass

        # Extract winning model metrics
        all_metrics = status_data.get("metrics")
        if isinstance(all_metrics, dict):
            if winner_key and winner_key in all_metrics and isinstance(all_metrics[winner_key], dict):
                wm = all_metrics[winner_key]
                metrics = DashboardModelMetrics(
                    ndcg=wm.get("ndcg"),
                    precision=wm.get("precision"),
                    recall=wm.get("recall"),
                )
            elif "ndcg" in all_metrics:
                metrics = DashboardModelMetrics(
                    ndcg=all_metrics.get("ndcg"),
                    precision=all_metrics.get("precision"),
                    recall=all_metrics.get("recall"),
                )

        if status_str == "completed" or ready:
            last_trained = status_data.get("updated_at") or status_data.get("started_at")

    dataset_schema = None
    if ds_stats:
        dataset_schema = DashboardDatasetStats(
            customers=ds_stats.get("customers"),
            products=ds_stats.get("products"),
            interactions=ds_stats.get("interactions"),
        )

    return DashboardOverviewResponse(
        tenant_id=tenant_id,
        status=status_str,
        ready=ready,
        winning_model=winning_model,
        winner_key=winner_key,
        metrics=metrics,
        dataset_stats=dataset_schema,
        requests_today=requests_today,
        active_key_count=key_count,
        last_trained=last_trained,
    )


# ---------------------------------------------------------------------------
# GET /v1/dashboard/models
# ---------------------------------------------------------------------------


@router.get(
    "/models",
    response_model=DashboardModelsResponse,
    summary="Get model tournament leaderboard",
    description="Retrieve tournament performance breakdown across all 4 candidate models sorted by NDCG@5.",
)
def get_dashboard_models(
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> DashboardModelsResponse:
    cfg = load_config()
    storage = get_storage_backend(cfg)

    status_data = _load_status_file(tenant_id, storage)
    ds_stats = _get_or_compute_dataset_stats(tenant_id, status_data, storage)

    status_str = "not_started"
    winner_key = None
    winner_name = None
    winner_metrics = None
    last_trained = None

    models_state = {}
    metrics_state = {}

    if status_data:
        status_str = status_data.get("status") or "not_started"
        winner_key = status_data.get("winner_key")
        winner_name = status_data.get("winner_model")
        models_state = status_data.get("models") or {}
        metrics_state = status_data.get("metrics") or {}

        # Stalled check
        updated_at = status_data.get("updated_at")
        if status_str in ("queued", "running") and updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - dt).total_seconds() > 15 * 60:
                    status_str = "stalled"
            except (ValueError, TypeError):
                pass

        if status_str == "completed" or status_data.get("ready"):
            last_trained = status_data.get("updated_at") or status_data.get("started_at")

        if winner_key and isinstance(metrics_state, dict) and winner_key in metrics_state:
            wm = metrics_state[winner_key]
            if isinstance(wm, dict):
                winner_metrics = DashboardModelMetrics(
                    ndcg=wm.get("ndcg"),
                    precision=wm.get("precision"),
                    recall=wm.get("recall"),
                )

    leaderboard: list[DashboardModelLeaderboardItem] = []

    for meta in MODEL_METADATA:
        m_id = meta["id"]
        m_name = meta["name"]
        color = meta["color"]

        # Determine individual model status
        m_status = models_state.get(m_id)
        if not m_status:
            if status_str == "completed":
                m_status = "done"
            elif status_str in ("running", "queued", "stalled", "failed"):
                m_status = status_str
            else:
                m_status = "not_started"

        m_metrics = metrics_state.get(m_id) if isinstance(metrics_state, dict) else None
        ndcg = m_metrics.get("ndcg") if isinstance(m_metrics, dict) else None
        prec = m_metrics.get("precision") if isinstance(m_metrics, dict) else None
        rec = m_metrics.get("recall") if isinstance(m_metrics, dict) else None

        is_winner = bool(winner_key and m_id == winner_key)

        leaderboard.append(
            DashboardModelLeaderboardItem(
                id=m_id,
                name=m_name,
                ndcg=ndcg,
                precision=prec,
                recall=rec,
                status=m_status,
                is_winner=is_winner,
                color=color,
            )
        )

    # Sort leaderboard by NDCG descending (None values sorted to end)
    leaderboard.sort(
        key=lambda m: (m.ndcg is not None, m.ndcg if m.ndcg is not None else -1.0),
        reverse=True,
    )

    dataset_schema = None
    if ds_stats:
        dataset_schema = DashboardDatasetStats(
            customers=ds_stats.get("customers"),
            products=ds_stats.get("products"),
            interactions=ds_stats.get("interactions"),
        )

    return DashboardModelsResponse(
        tenant_id=tenant_id,
        status=status_str,
        winner_key=winner_key,
        winner_name=winner_name,
        winner_metrics=winner_metrics,
        models=leaderboard,
        dataset_stats=dataset_schema,
        last_trained=last_trained,
    )


# ---------------------------------------------------------------------------
# GET /v1/dashboard/analytics
# ---------------------------------------------------------------------------


@router.get(
    "/analytics",
    response_model=DashboardAnalyticsResponse,
    summary="Get recommendation and event analytics",
    description="Retrieve event volumes, top recommended products, and recommendation stats over N days.",
)
def get_dashboard_analytics(
    days: int = Query(7, ge=1, le=90, description="Time window in days"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> DashboardAnalyticsResponse:
    cfg = load_config()
    storage = get_storage_backend(cfg)

    # Excludes test traffic automatically
    telem = get_tenant_telemetry(tenant_id, days=days, storage=storage)

    daily_events: list[DashboardDailyEvent] = []
    for d in telem.get("events_by_day", []):
        d_str = d.get("date", "")
        day_label = d_str
        try:
            day_label = datetime.strptime(d_str, "%Y-%m-%d").strftime("%a")
        except Exception:
            pass

        counts = d.get("counts", {})
        daily_events.append(
            DashboardDailyEvent(
                date=d_str,
                day=day_label,
                views=counts.get("view", 0),
                clicks=counts.get("click", 0),
                cart_adds=counts.get("add_to_cart", 0),
                purchases=counts.get("purchase", 0),
                total=d.get("total", 0),
            )
        )

    top_products = [
        DashboardTopProduct(
            product_id=p["product_id"],
            name=p["product_name"],
            recs=p["count"],
        )
        for p in telem.get("top_products", [])
    ]

    return DashboardAnalyticsResponse(
        tenant_id=tenant_id,
        days=days,
        total_events=telem.get("total_events", 0),
        total_recommendations=telem.get("total_recommendations", 0),
        requests_today=telem.get("requests_today", 0),
        fallback_rate=telem.get("fallback_rate"),
        ctr=telem.get("ctr"),
        events_by_day=daily_events,
        top_products=top_products,
    )


# ---------------------------------------------------------------------------
# GET /v1/dashboard/events
# ---------------------------------------------------------------------------


@router.get(
    "/events",
    response_model=DashboardEventsResponse,
    summary="Get recent tracking events",
    description="Retrieve the latest real interaction events for the tenant.",
)
def get_dashboard_events(
    limit: int = Query(20, ge=1, le=100, description="Max events to return"),
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> DashboardEventsResponse:
    cfg = load_config()
    storage = get_storage_backend(cfg)

    events_raw = get_tenant_events(tenant_id, limit=limit, storage=storage)
    prod_names = _get_product_names(tenant_id, storage)

    items: list[DashboardEventItem] = []
    for ev in events_raw:
        pid = ev.get("product_id")
        pname = prod_names.get(pid) if pid else None
        ts = ev.get("ts")
        time_ago = _format_time_ago(ts)

        items.append(
            DashboardEventItem(
                ts=ts,
                event_type=ev.get("event_type", "view"),
                product_id=pid,
                product_name=pname,
                session_id=ev.get("session_id"),
                customer_id=ev.get("customer_id"),
                time_ago=time_ago,
            )
        )

    return DashboardEventsResponse(
        tenant_id=tenant_id,
        events=items,
    )

