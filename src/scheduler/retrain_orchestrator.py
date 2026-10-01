"""Scheduled model retraining orchestrator for Amazon EventBridge / cron triggers.

Executes the nightly (or periodic) scheduled retrain workflow:
1. Discovers all tenants.
2. For each tenant marked 'ready_to_train' that has never been trained: kicks off their
   first training run using the background training mechanism from Step 15.5.
3. For each already-trained tenant: kicks off a retrain incorporating any newly arrived
   interaction data since their last run.
4. Prevents collisions by detecting active/queued training runs for a tenant and skipping them.
5. Produces, logs, and persists a comprehensive per-tenant summary report.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any

from src.api.onboarding import (
    _ACTIVE_TRAINING_THREADS,
    _load_training_status,
    _save_training_status,
    _start_background_training,
)
from src.scheduler.readiness_checker import discover_all_tenants, is_tenant_untrained
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import load_config

logger = logging.getLogger(__name__)


def run_scheduled_retraining(
    config: dict | None = None,
    storage: StorageBackend | None = None,
    wait_for_completion: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Execute scheduled model retraining cycle across all tenants.

    Args:
        config: Loaded project configuration.
        storage: Configured storage backend.
        wait_for_completion: If True, blocks until all spawned training threads finish.
        timeout_seconds: Timeout in seconds when wait_for_completion is True.

    Returns:
        dict summary report conforming to ScheduledRetrainResponse.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    if storage is None:
        storage = get_storage_backend(config)

    now_iso = datetime.now(timezone.utc).isoformat()
    all_tenants = discover_all_tenants(config=config, storage=storage)
    logger.info("Starting scheduled retraining cycle across %d tenants at %s...", len(all_tenants), now_iso)

    first_trainings_count = 0
    retrainings_count = 0
    skipped_in_progress_count = 0
    skipped_other_count = 0
    tenant_summaries: list[dict[str, Any]] = []
    spawned_threads: list[threading.Thread] = []

    for tenant_id in all_tenants:
        current_status_data = _load_training_status(tenant_id, storage=storage)
        curr_status = current_status_data.get("status") if current_status_data else None
        active_thread = _ACTIVE_TRAINING_THREADS.get(tenant_id)
        is_thread_alive = bool(active_thread and active_thread.is_alive())

        # 1. Collision check: Is a training run already active or queued for this tenant?
        if is_thread_alive or curr_status in ("queued", "running"):
            logger.info("Collision avoided: training already in progress for tenant '%s' (status=%s)", tenant_id, curr_status)
            skipped_in_progress_count += 1
            tenant_summaries.append(
                {
                    "tenant_id": tenant_id,
                    "tenant_type": "in_progress",
                    "action": "skipped",
                    "status": "skipped",
                    "reason": f"Training job for tenant '{tenant_id}' is already in progress ({curr_status}).",
                    "message": "Collision avoided: existing training run preserved untouched.",
                }
            )
            continue

        untrained = is_tenant_untrained(tenant_id, storage=storage)

        # 2. Case A: New tenant marked ready-to-train that has never been trained
        if untrained:
            if curr_status in ("ready_to_train", "ready-to-train"):
                logger.info("Triggering first training run for newly ready tenant '%s'...", tenant_id)
                _save_training_status(
                    tenant_id=tenant_id,
                    status_val="queued",
                    message=f"Scheduled first training run for newly ready tenant '{tenant_id}' queued.",
                    storage=storage,
                )
                th = _start_background_training(tenant_id=tenant_id, config=config)
                spawned_threads.append(th)
                first_trainings_count += 1
                tenant_summaries.append(
                    {
                        "tenant_id": tenant_id,
                        "tenant_type": "new_ready",
                        "action": "first_training",
                        "status": "queued",
                        "reason": None,
                        "message": f"First training run successfully kicked off for tenant '{tenant_id}'.",
                    }
                )
            else:
                logger.debug("Skipping untrained tenant '%s': not marked ready-to-train (status=%s)", tenant_id, curr_status)
                skipped_other_count += 1
                tenant_summaries.append(
                    {
                        "tenant_id": tenant_id,
                        "tenant_type": "below_threshold",
                        "action": "skipped",
                        "status": "skipped",
                        "reason": f"Untrained tenant '{tenant_id}' has not met training thresholds (status={curr_status}).",
                        "message": "Untrained tenant skipped until thresholds are crossed.",
                    }
                )
            continue

        # 3. Case B: Already-trained tenant -> kick off retrain using latest interaction data
        logger.info("Triggering retrain for already-trained tenant '%s'...", tenant_id)
        _save_training_status(
            tenant_id=tenant_id,
            status_val="queued",
            message=f"Scheduled retrain run for tenant '{tenant_id}' queued with latest interactions.",
            storage=storage,
        )
        th = _start_background_training(tenant_id=tenant_id, config=config)
        spawned_threads.append(th)
        retrainings_count += 1
        tenant_summaries.append(
            {
                "tenant_id": tenant_id,
                "tenant_type": "already_trained",
                "action": "retrain",
                "status": "queued",
                "reason": None,
                "message": f"Retrain run successfully kicked off for tenant '{tenant_id}'.",
            }
        )

    # If caller requested blocking until completion (e.g. CLI or test)
    if wait_for_completion and spawned_threads:
        logger.info("Waiting up to %.1fs for %d background training thread(s)...", timeout_seconds, len(spawned_threads))
        for th in spawned_threads:
            th.join(timeout=timeout_seconds)

    report: dict[str, Any] = {
        "status": "ok",
        "timestamp": now_iso,
        "total_tenants_checked": len(all_tenants),
        "first_trainings_triggered": first_trainings_count,
        "retrainings_triggered": retrainings_count,
        "skipped_in_progress": skipped_in_progress_count,
        "skipped_other": skipped_other_count,
        "summaries": tenant_summaries,
    }

    # 4. Log per-tenant summary
    logger.info("================ SCHEDULED RETRAINING SUMMARY ================")
    logger.info("Timestamp: %s", now_iso)
    logger.info(
        "Total checked: %d | First train: %d | Retrains: %d | In-progress skipped: %d | Other skipped: %d",
        len(all_tenants),
        first_trainings_count,
        retrainings_count,
        skipped_in_progress_count,
        skipped_other_count,
    )
    for s in tenant_summaries:
        logger.info(
            "  -> Tenant '%s' [%s]: action='%s', status='%s', reason='%s'",
            s["tenant_id"],
            s["tenant_type"],
            s["action"],
            s["status"],
            s.get("reason") or "None",
        )
    logger.info("==============================================================")

    # 5. Persist audit summary to storage so operators can check without watching live
    try:
        report_bytes = json.dumps(report, indent=2).encode("utf-8")
        storage.write_file("status/scheduled_retrain_latest.json", report_bytes)
    except Exception as exc:
        logger.warning("Could not persist status/scheduled_retrain_latest.json: %s", exc)

    return report
