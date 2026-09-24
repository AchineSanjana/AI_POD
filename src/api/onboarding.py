"""Onboarding API endpoints for dataset upload, validation, confirmation, and training."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import threading
from typing import Any

import pandas as pd
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from scripts.onboard_tenant import _apply_overrides, save_tenant_to_config
from src.api.auth import get_current_tenant
from src.api.rate_limiter import check_rate_limit
from src.api.recommendations import clear_model_cache
from src.api.schemas import (
    ColumnProfileInfo,
    OnboardConfirmRequest,
    OnboardConfirmResponse,
    OnboardStatusResponse,
    OnboardTrainRequest,
    OnboardTrainResponse,
    OnboardUploadResponse,
    OnboardValidateRequest,
    OnboardValidateResponse,
)
from src.data.adapters.generic_config_adapter import GenericConfigAdapter
from src.models.ranking_model import LearnedRankingRecommender
from src.onboarding.config_generator import (
    _validate_tenant_config,
    generate_review_summary,
    generate_tenant_config,
)
from src.onboarding.profiler import profile_dataframe
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import PROJECT_ROOT, get_tenant_config, load_config, resolve_path
from src.utils.persistence import save_model

logger = logging.getLogger(__name__)

# Active background training threads tracked by tenant_id
_ACTIVE_TRAINING_THREADS: dict[str, threading.Thread] = {}


def _get_status_file_path(tenant_id: str) -> str:
    """Logical path to tenant training status file."""
    return f"status/{tenant_id}.json"


def _save_training_status(
    tenant_id: str,
    status_val: str,
    message: str,
    storage: StorageBackend,
    model_path: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist tenant training status JSON in storage."""
    data = {
        "tenant_id": tenant_id,
        "status": status_val,
        "status_url": "/v1/onboard/status",
        "message": message,
        "model_path": model_path,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps(data, indent=2).encode("utf-8")
    storage.write_file(_get_status_file_path(tenant_id), payload)
    return data


def _load_training_status(
    tenant_id: str,
    storage: StorageBackend,
) -> dict[str, Any] | None:
    """Read tenant training status JSON from storage if it exists."""
    path = _get_status_file_path(tenant_id)
    if not storage.exists(path):
        return None
    try:
        content = storage.read_file(path)
        return json.loads(content.decode("utf-8"))
    except Exception:
        return None


def _execute_training_job(tenant_id: str, config: dict) -> None:
    """Worker function that runs data adaptation and model training in the background."""
    storage = get_storage_backend(config)
    _save_training_status(
        tenant_id=tenant_id,
        status_val="running",
        message=f"Training job for tenant '{tenant_id}' is running.",
        storage=storage,
    )
    try:
        tenant_cfg = get_tenant_config(config, tenant_id)
        adapter = GenericConfigAdapter(tenant_cfg, storage=storage)
        customers, products, interactions = adapter.run()
        model = LearnedRankingRecommender(
            customer_specs=tenant_cfg.customers.features
        ).fit(
            customers=customers,
            products=products,
            interactions=interactions,
        )

        model_path = f"models/{tenant_id}/final_model.joblib"
        save_model(model, model_path, storage=storage)
        clear_model_cache()

        _save_training_status(
            tenant_id=tenant_id,
            status_val="complete",
            message=f"Model successfully trained and saved to {model_path} for tenant '{tenant_id}'.",
            storage=storage,
            model_path=model_path,
        )
    except Exception as exc:
        logger.exception("Training failed for tenant %s: %s", tenant_id, exc)
        _save_training_status(
            tenant_id=tenant_id,
            status_val="failed",
            message=f"Training failed for tenant '{tenant_id}': {exc}",
            storage=storage,
            error=str(exc),
        )
    finally:
        _ACTIVE_TRAINING_THREADS.pop(tenant_id, None)


def _start_background_training(tenant_id: str, config: dict) -> None:
    """FastAPI BackgroundTasks entrypoint: spawns worker thread and tracks it."""
    thread = threading.Thread(
        target=_execute_training_job,
        args=(tenant_id, config),
        name=f"train-worker-{tenant_id}",
        daemon=True,
    )
    _ACTIVE_TRAINING_THREADS[tenant_id] = thread
    thread.start()


router = APIRouter(
    prefix="/onboard",
    tags=["onboard"],
    dependencies=[Depends(check_rate_limit(scope="onboarding"))],
)


@router.post(
    "/upload",
    response_model=OnboardUploadResponse,
    summary="Upload raw tenant dataset",
    description="Upload raw dataset content (CSV format or JSON with csv_content/source_path) for tenant onboarding.",
)
async def upload_dataset(
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
) -> OnboardUploadResponse:
    """Upload raw dataset file for the authenticated tenant."""
    content_type = request.headers.get("content-type", "").lower()
    raw_bytes: bytes = b""
    target_filename = f"{tenant_id}_raw.csv"

    if "application/json" in content_type:
        try:
            body_json = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Malformed JSON in request body")

        if not isinstance(body_json, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")

        if "csv_content" in body_json:
            content = str(body_json["csv_content"]).strip()
            if not content:
                raise HTTPException(
                    status_code=400, detail="Uploaded dataset content cannot be empty"
                )
            raw_bytes = content.encode("utf-8")
        elif "source_path" in body_json and body_json["source_path"]:
            src_p = resolve_path(body_json["source_path"])
            if not src_p.exists():
                src_p = Path(body_json["source_path"])
            if not src_p.exists():
                raise HTTPException(
                    status_code=400, detail=f"Source file not found: {body_json['source_path']}"
                )
            raw_bytes = src_p.read_bytes()
        else:
            raise HTTPException(
                status_code=400,
                detail="JSON upload payload must provide 'csv_content' or 'source_path'",
            )
    else:
        raw_bytes = await request.body()

    if not raw_bytes or not raw_bytes.strip():
        raise HTTPException(status_code=400, detail="Uploaded dataset content cannot be empty")

    try:
        df = pd.read_csv(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV dataset: {exc}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Dataset must contain at least one row of data")

    dest_path = resolve_path(f"data/raw/{target_filename}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(raw_bytes)

    rel_path = f"data/raw/{target_filename}"
    return OnboardUploadResponse(
        tenant_id=tenant_id,
        file_path=rel_path,
        rows=len(df),
        columns=list(df.columns),
        message=f"Successfully uploaded {len(df)} rows and {len(df.columns)} columns for tenant '{tenant_id}'.",
    )


def _resolve_tenant_data_file(tenant_id: str, custom_file: str | None = None) -> Path:
    """Find the raw dataset path for a tenant."""
    if custom_file:
        p = resolve_path(custom_file)
        if not p.exists():
            p = Path(custom_file)
        if p.exists():
            return p
        raise HTTPException(status_code=404, detail=f"Specified data file not found: {custom_file}")

    # Check uploaded raw dataset
    uploaded = resolve_path(f"data/raw/{tenant_id}_raw.csv")
    if uploaded.exists():
        return uploaded

    # Check config.yaml data_source.path if tenant is already declared
    try:
        cfg = load_config()
        if tenant_id in cfg.get("tenants", {}):
            t_cfg = get_tenant_config(cfg, tenant_id)
            ds_path = resolve_path(t_cfg.data_source.path)
            if ds_path.exists():
                return ds_path
    except Exception:
        pass

    raise HTTPException(
        status_code=404,
        detail=f"No raw dataset found for tenant '{tenant_id}'. Upload one first via /v1/onboard/upload.",
    )


@router.post(
    "/validate",
    response_model=OnboardValidateResponse,
    summary="Validate and profile tenant dataset",
    description="Inspects the tenant's raw dataset, auto-generates candidate configuration, and flags ambiguous fields.",
)
def validate_dataset(
    payload: OnboardValidateRequest | None = None,
    tenant_id: str = Depends(get_current_tenant),
) -> OnboardValidateResponse:
    """Validate and profile the tenant's raw dataset."""
    data_file_path = _resolve_tenant_data_file(
        tenant_id, custom_file=payload.data_file if payload else None
    )

    try:
        df = pd.read_csv(data_file_path)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Unable to read dataset at {data_file_path}: {exc}"
        )

    if df.empty:
        raise HTTPException(status_code=400, detail="Raw dataset contains no rows")

    try:
        report = profile_dataframe(df)
        try:
            rel_path = str(data_file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            rel_path = str(data_file_path).replace("\\", "/")

        candidate_config = generate_tenant_config(report, tenant_id=tenant_id, data_source_path=rel_path)
        summary = generate_review_summary(report)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Profiling failed for dataset: {exc}"
        )

    needs_review = [
        ColumnProfileInfo(
            name=c.name,
            inferred_type=c.suggested_dtype,
            suggested_dtype=c.suggested_dtype,
            confidence_score=c.confidence_score,
            needs_review=c.needs_review,
            review_reason=c.review_reason,
        )
        for c in report
        if c.needs_review
    ]

    return OnboardValidateResponse(
        tenant_id=tenant_id,
        is_valid=True,
        candidate_config=candidate_config,
        needs_review=needs_review,
        summary=summary,
    )


@router.post(
    "/confirm",
    response_model=OnboardConfirmResponse,
    summary="Confirm and save tenant configuration",
    description="Applies column decisions/overrides, validates configuration schema, and saves the block into config.yaml.",
)
def confirm_onboarding(
    payload: OnboardConfirmRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> OnboardConfirmResponse:
    """Validate and persist the tenant's configuration in config.yaml."""
    data_file_path = _resolve_tenant_data_file(tenant_id)
    df = pd.read_csv(data_file_path)
    report = profile_dataframe(df)

    if payload.candidate_config:
        config_block = dict(payload.candidate_config)
    else:
        try:
            rel_path = str(data_file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            rel_path = str(data_file_path).replace("\\", "/")
        config_block = generate_tenant_config(report, tenant_id=tenant_id, data_source_path=rel_path)

    if payload.overrides:
        _apply_overrides(config_block, report, payload.overrides)

    try:
        _validate_tenant_config(config_block, tenant_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Tenant configuration validation failed: {exc}"
        )

    try:
        save_tenant_to_config(tenant_id, config_block)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to persist configuration to config.yaml: {exc}"
        )

    return OnboardConfirmResponse(
        tenant_id=tenant_id,
        status="confirmed",
        config_saved=True,
        message=f"Configuration for tenant '{tenant_id}' successfully saved to config.yaml.",
    )


@router.post(
    "/train",
    response_model=OnboardTrainResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Train recommendation model for tenant",
    description="Asynchronously executes data adapter transformations and trains the recommendation model in the background.",
)
def train_tenant(
    background_tasks: BackgroundTasks,
    payload: OnboardTrainRequest | None = None,
    tenant_id: str = Depends(get_current_tenant),
) -> OnboardTrainResponse:
    """Asynchronously train and persist recommendation model artifacts for the authenticated tenant."""
    config = load_config()
    tenants = config.get("tenants", {})
    if tenant_id not in tenants:
        raise HTTPException(
            status_code=404,
            detail=f"Tenant '{tenant_id}' configuration not found in config.yaml. Run /v1/onboard/confirm first.",
        )

    try:
        tenant_cfg = get_tenant_config(config, tenant_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid tenant configuration for '{tenant_id}': {exc}"
        )

    data_file = resolve_path(tenant_cfg.data_source.path)
    if not data_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Raw dataset file '{tenant_cfg.data_source.path}' not found on disk.",
        )

    storage = get_storage_backend(config)

    # Check if a training job is already active for this tenant
    current_status = _load_training_status(tenant_id, storage=storage)
    active_thread = _ACTIVE_TRAINING_THREADS.get(tenant_id)
    if (
        (active_thread and active_thread.is_alive())
        or (current_status and current_status.get("status") in ("queued", "running"))
    ):
        return OnboardTrainResponse(
            tenant_id=tenant_id,
            status=current_status.get("status", "running") if current_status else "running",
            status_url="/v1/onboard/status",
            message=f"Training job for tenant '{tenant_id}' is already in progress.",
            trained=False,
            model_path=None,
        )

    # Persist initial 'queued' status
    _save_training_status(
        tenant_id=tenant_id,
        status_val="queued",
        message=f"Training job for tenant '{tenant_id}' has been queued.",
        storage=storage,
    )

    # Dispatch to FastAPI BackgroundTasks
    background_tasks.add_task(_start_background_training, tenant_id=tenant_id, config=config)

    return OnboardTrainResponse(
        tenant_id=tenant_id,
        status="queued",
        status_url="/v1/onboard/status",
        message=f"Training job for tenant '{tenant_id}' accepted and queued in background.",
        trained=False,
        model_path=None,
    )


@router.get(
    "/status",
    response_model=OnboardStatusResponse,
    summary="Get tenant onboarding lifecycle status",
    description="Inspects background training status and artifact readiness for the authenticated tenant.",
)
def get_onboarding_status(
    tenant_id: str = Depends(get_current_tenant),
) -> OnboardStatusResponse:
    """Check the onboarding status and artifact readiness for the authenticated tenant."""
    config = load_config()
    tenants = config.get("tenants", {})
    has_config = tenant_id in tenants

    has_data = False
    raw_candidate = resolve_path(f"data/raw/{tenant_id}_raw.csv")
    if raw_candidate.exists():
        has_data = True
    elif has_config:
        try:
            t_cfg = get_tenant_config(config, tenant_id)
            if resolve_path(t_cfg.data_source.path).exists():
                has_data = True
        except Exception:
            pass

    storage = get_storage_backend(config)
    model_path = f"models/{tenant_id}/final_model.joblib"
    has_model = storage.exists(model_path)
    if not has_model and tenant_id == "telco_default":
        has_model = storage.exists("models/final_model.joblib")
        if has_model:
            model_path = "models/final_model.joblib"

    # 1. Check if an explicit training status file exists in storage
    status_data = _load_training_status(tenant_id, storage=storage)
    if status_data:
        train_status = status_data.get("status")
        if train_status in ("queued", "running"):
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status=train_status,
                has_data=has_data,
                has_config=has_config,
                has_model=False,
                model_path=None,
                error=None,
                message=status_data.get(
                    "message", f"Training is currently {train_status} for tenant '{tenant_id}'."
                ),
            )
        elif train_status == "failed":
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="failed",
                has_data=has_data,
                has_config=has_config,
                has_model=has_model,
                model_path=None,
                error=status_data.get("error"),
                message=status_data.get(
                    "message", f"Training failed for tenant '{tenant_id}': {status_data.get('error')}"
                ),
            )
        elif train_status == "complete":
            saved_model_path = status_data.get("model_path") or model_path
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="complete",
                has_data=has_data,
                has_config=has_config,
                has_model=True,
                model_path=saved_model_path,
                error=None,
                message=status_data.get(
                    "message",
                    f"Model successfully trained and saved to {saved_model_path} for tenant '{tenant_id}'.",
                ),
            )

    # 2. Fall back to inferred onboarding state when no status file exists
    if has_model and has_config:
        status_str = "active"
        msg = f"Tenant '{tenant_id}' is active and ready to serve recommendations."
    elif has_config and has_data:
        status_str = "ready_to_train"
        msg = f"Tenant '{tenant_id}' configuration is confirmed. Call /v1/onboard/train to build model."
    elif has_data:
        status_str = "needs_configuration"
        msg = f"Tenant '{tenant_id}' dataset is uploaded. Call /v1/onboard/validate to inspect schema."
    else:
        status_str = "not_started"
        msg = f"Tenant '{tenant_id}' has not uploaded data. Call /v1/onboard/upload to begin."

    return OnboardStatusResponse(
        tenant_id=tenant_id,
        status=status_str,
        has_data=has_data,
        has_config=has_config,
        has_model=has_model,
        model_path=model_path if has_model else None,
        error=None,
        message=msg,
    )
