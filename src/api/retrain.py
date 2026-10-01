"""API endpoints for scheduled model retraining (Amazon EventBridge & cron triggers)."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from src.api.rate_limiter import check_rate_limit
from src.api.schemas import ScheduledRetrainRequest, ScheduledRetrainResponse
from src.scheduler.retrain_orchestrator import run_scheduled_retraining
from src.storage import get_storage_backend
from src.utils.config import load_config

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/retrain",
    tags=["retrain"],
    dependencies=[Depends(check_rate_limit(scope="onboarding"))],
)


@router.post(
    "/scheduled",
    response_model=ScheduledRetrainResponse,
    summary="Trigger scheduled model retraining across tenants",
    description="Invoked by Amazon EventBridge or scheduled cron to train new ready-to-train tenants and retrain existing tenants.",
)
def trigger_scheduled_retrain(
    request: Request,
    payload: ScheduledRetrainRequest | None = None,
) -> dict[str, Any]:
    """Execute scheduled model retraining across all tenants.

    1. Checks for newly ready untrained tenants and dispatches their first training run.
    2. Checks for already-trained tenants and dispatches retrain with latest interaction data.
    3. Prevents collisions with active/queued training jobs.
    4. Logs and returns structured per-tenant summary report.
    """
    config = load_config()
    storage = get_storage_backend(config)

    wait = payload.wait_for_completion if payload else False
    timeout = payload.timeout_seconds if payload else 30.0

    report = run_scheduled_retraining(
        config=config,
        storage=storage,
        wait_for_completion=wait,
        timeout_seconds=timeout,
    )
    return report


@router.get(
    "/latest",
    response_model=ScheduledRetrainResponse,
    summary="Get latest scheduled retrain summary report",
    description="Retrieve the summary report produced by the most recent scheduled retraining run.",
)
def get_latest_scheduled_retrain() -> dict[str, Any]:
    """Return the audit log of the most recent scheduled retraining cycle."""
    config = load_config()
    storage = get_storage_backend(config)
    path = "status/scheduled_retrain_latest.json"
    if not storage.exists(path):
        raise HTTPException(
            status_code=404,
            detail="No scheduled retraining run has been executed yet.",
        )
    try:
        content = storage.read_file(path)
        return json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed reading latest retrain summary: {exc}")
