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
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel

from scripts.onboard_tenant import _apply_overrides, save_tenant_to_config
from src.api.auth import (
    TENANT_AUTH_MAPPING,
    get_current_tenant,
    get_tenant_for_admin_action,
    load_tenant_auth,
)
from src.utils.atomic_yaml import atomic_dump_yaml, atomic_yaml_write_lock
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
from src.utils.config import (
    PROJECT_ROOT,
    get_tenant_auth_mapping,
    get_tenant_config,
    load_config,
    resolve_path,
)
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
    """Worker function that runs the multi-model tournament recommendation pipeline."""
    storage = get_storage_backend(config)
    try:
        from src.pipeline.run import run_tenant_pipeline

        run_tenant_pipeline(
            tenant_id=tenant_id,
            storage=storage,
            config=config,
        )
    except Exception as exc:
        logger.exception("Training failed for tenant %s: %s", tenant_id, exc)
    finally:
        _ACTIVE_TRAINING_THREADS.pop(tenant_id, None)


def _start_background_training(tenant_id: str, config: dict) -> threading.Thread:
    """FastAPI BackgroundTasks entrypoint: spawns worker thread and tracks it."""
    thread = threading.Thread(
        target=_execute_training_job,
        args=(tenant_id, config),
        name=f"train-worker-{tenant_id}",
        daemon=True,
    )
    _ACTIVE_TRAINING_THREADS[tenant_id] = thread
    thread.start()
    return thread


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
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> OnboardUploadResponse:
    """Upload raw dataset file for the authenticated tenant."""
    content_type = request.headers.get("content-type", "").lower()
    raw_bytes: bytes = b""
    target_filename = f"{tenant_id}_raw.csv"

    if "multipart/form-data" in content_type:
        form = await request.form()
        for _, value in form.items():
            if hasattr(value, "read"):
                raw_bytes = await value.read()
                break
            elif isinstance(value, str) and value.strip():
                raw_bytes = value.strip().encode("utf-8")
                break
    elif "application/json" in content_type:
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

    config = load_config()
    storage = get_storage_backend(config)
    rel_path = f"data/raw/{target_filename}"
    storage.write_file(rel_path, raw_bytes)

    return OnboardUploadResponse(
        tenant_id=tenant_id,
        file_path=rel_path,
        rows=len(df),
        columns=list(df.columns),
        message=f"Successfully uploaded {len(df)} rows and {len(df.columns)} columns for tenant '{tenant_id}'.",
    )


def _read_tenant_raw_data(
    tenant_id: str,
    storage: StorageBackend,
    custom_file: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Find and read the raw dataset for a tenant via storage."""
    if custom_file:
        clean = custom_file.replace("\\", "/").strip()
        if storage.exists(clean):
            return pd.read_csv(io.BytesIO(storage.read_file(clean))), clean
        p = resolve_path(custom_file)
        if p.exists():
            return pd.read_csv(p), custom_file
        raise HTTPException(
            status_code=404, detail=f"Specified data file not found: {custom_file}"
        )

    # Check uploaded raw dataset in storage
    uploaded = f"data/raw/{tenant_id}_raw.csv"
    if storage.exists(uploaded):
        return pd.read_csv(io.BytesIO(storage.read_file(uploaded))), uploaded
    up_local = resolve_path(uploaded)
    if up_local.exists():
        return pd.read_csv(up_local), uploaded

    # Check config.yaml data_source.path if tenant is already declared
    try:
        cfg = load_config()
        if tenant_id in cfg.get("tenants", {}):
            t_cfg = get_tenant_config(cfg, tenant_id)
            ds_path = t_cfg.data_source.path.replace("\\", "/").strip()
            if storage.exists(ds_path):
                return pd.read_csv(io.BytesIO(storage.read_file(ds_path))), ds_path
            loc_p = resolve_path(ds_path)
            if loc_p.exists():
                return pd.read_csv(loc_p), ds_path
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
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> OnboardValidateResponse:
    """Validate and profile the tenant's raw dataset."""
    config = load_config()
    storage = get_storage_backend(config)
    df, rel_path = _read_tenant_raw_data(
        tenant_id, storage, custom_file=payload.data_file if payload else None
    )

    if df.empty:
        raise HTTPException(status_code=400, detail="Raw dataset contains no rows")

    try:
        report = profile_dataframe(df)
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
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> OnboardConfirmResponse:
    """Validate and persist the tenant's configuration in config.yaml."""
    if payload.candidate_config:
        req_tenant = payload.candidate_config.get("tenant_id")
        if req_tenant and req_tenant != tenant_id and tenant_id != "admin":
            raise HTTPException(
                status_code=403,
                detail=f"Forbidden: You can only configure your own tenant ('{tenant_id}').",
            )
    config = load_config()
    storage = get_storage_backend(config)
    df, rel_path = _read_tenant_raw_data(tenant_id, storage)
    report = profile_dataframe(df)

    if payload.candidate_config:
        config_block = dict(payload.candidate_config)
    else:
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
    tenant_id: str = Depends(get_tenant_for_admin_action),
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

    storage = get_storage_backend(config)
    raw_path = tenant_cfg.data_source.path
    if not storage.exists(raw_path) and not resolve_path(raw_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Raw dataset file '{tenant_cfg.data_source.path}' not found in storage.",
        )

    # Multi-worker guard: check active thread in current process
    active_thread = _ACTIVE_TRAINING_THREADS.get(tenant_id)
    if active_thread and active_thread.is_alive():
        raise HTTPException(
            status_code=409,
            detail=f"Training job for tenant '{tenant_id}' is already in progress.",
        )

    # Multi-worker guard: check status/{tenant_id}.json in storage
    current_status = _load_training_status(tenant_id, storage=storage)
    if current_status and current_status.get("status") in ("queued", "running"):
        updated_at = current_status.get("updated_at")
        if updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                diff_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
                if diff_seconds < 15 * 60:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Training job for tenant '{tenant_id}' is already in progress "
                            f"on a worker ({int(diff_seconds)}s ago)."
                        ),
                    )
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=409,
                    detail=f"Training job for tenant '{tenant_id}' is already in progress.",
                )
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Training job for tenant '{tenant_id}' is already in progress.",
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
    tenant_id: str = Depends(get_tenant_for_admin_action),
) -> OnboardStatusResponse:
    """Check the onboarding status and artifact readiness for the authenticated tenant."""
    config = load_config()
    tenants = config.get("tenants", {})
    has_config = tenant_id in tenants

    storage = get_storage_backend(config)
    has_data = False
    raw_candidate = f"data/raw/{tenant_id}_raw.csv"
    if storage.exists(raw_candidate) or resolve_path(raw_candidate).exists():
        has_data = True
    elif has_config:
        try:
            t_cfg = get_tenant_config(config, tenant_id)
            ds_path = t_cfg.data_source.path
            if storage.exists(ds_path) or resolve_path(ds_path).exists():
                has_data = True
        except Exception:
            pass

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
        updated_at = status_data.get("updated_at")

        # Stalled check: if running/queued and updated_at > 15 minutes old
        is_stalled = False
        if train_status in ("queued", "running") and updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - dt).total_seconds() > 15 * 60:
                    is_stalled = True
            except (ValueError, TypeError):
                pass

        if is_stalled:
            logger.warning("[%s] Training job stalled (>15m without update)", tenant_id)
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="stalled",
                ready=False,
                has_data=has_data,
                has_config=has_config,
                has_model=has_model,
                model_path=model_path if has_model else None,
                stage=status_data.get("stage"),
                error="Training job stalled or timed out after 15 minutes.",
                message=f"Training job for tenant '{tenant_id}' stalled. Please retry.",
                models=status_data.get("models"),
                metrics=status_data.get("metrics"),
                winner_model=status_data.get("winner_model"),
                winner_key=status_data.get("winner_key"),
                dataset=status_data.get("dataset"),
                started_at=status_data.get("started_at"),
                updated_at=updated_at,
            )

        if train_status in ("queued", "running"):
            logger.info("[%s] Status check: %s (stage=%s)", tenant_id, train_status, status_data.get("stage"))
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status=train_status,
                ready=False,
                has_data=has_data,
                has_config=has_config,
                has_model=False,
                model_path=None,
                stage=status_data.get("stage"),
                error=None,
                message=status_data.get(
                    "message", f"Training is currently {train_status} for tenant '{tenant_id}'."
                ),
                models=status_data.get("models"),
                metrics=status_data.get("metrics"),
                winner_model=status_data.get("winner_model"),
                winner_key=status_data.get("winner_key"),
                dataset=status_data.get("dataset"),
                started_at=status_data.get("started_at"),
                updated_at=updated_at,
            )
        elif train_status == "failed":
            logger.info("[%s] Status check: failed (error=%s)", tenant_id, status_data.get("error"))
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="failed",
                ready=False,
                has_data=has_data,
                has_config=has_config,
                has_model=has_model,
                model_path=model_path if has_model else None,
                stage=status_data.get("stage"),
                error=status_data.get("error"),
                message=status_data.get(
                    "message", f"Training failed for tenant '{tenant_id}': {status_data.get('error')}"
                ),
                models=status_data.get("models"),
                metrics=status_data.get("metrics"),
                winner_model=status_data.get("winner_model"),
                winner_key=status_data.get("winner_key"),
                dataset=status_data.get("dataset"),
                started_at=status_data.get("started_at"),
                updated_at=updated_at,
            )
        elif train_status in ("complete", "completed"):
            saved_model_path = status_data.get("model_path") or model_path
            logger.info("[%s] Status check: completed (winner=%s)", tenant_id, status_data.get("winner_model"))
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="completed",
                ready=has_model,
                has_data=has_data,
                has_config=has_config,
                has_model=has_model,
                model_path=saved_model_path,
                stage=status_data.get("stage", "completed"),
                error=None,
                message=status_data.get(
                    "message",
                    f"Model successfully trained and saved for tenant '{tenant_id}'.",
                ),
                models=status_data.get("models"),
                metrics=status_data.get("metrics"),
                winner_model=status_data.get("winner_model"),
                winner_key=status_data.get("winner_key"),
                dataset=status_data.get("dataset"),
                started_at=status_data.get("started_at"),
                updated_at=updated_at,
            )
        elif train_status in ("ready_to_train", "ready-to-train"):
            return OnboardStatusResponse(
                tenant_id=tenant_id,
                status="ready_to_train",
                ready=False,
                has_data=has_data,
                has_config=has_config,
                has_model=has_model,
                model_path=model_path if has_model else None,
                error=None,
                message=status_data.get(
                    "message",
                    f"Tenant '{tenant_id}' has reached required data thresholds and is ready to train.",
                ),
                models=status_data.get("models"),
                metrics=status_data.get("metrics"),
                winner_model=status_data.get("winner_model"),
                winner_key=status_data.get("winner_key"),
                dataset=status_data.get("dataset"),
                started_at=status_data.get("started_at"),
                updated_at=updated_at,
            )

    # 2. Fall back to inferred onboarding state when no status file exists
    if has_model and has_config:
        status_str = "active"
        msg = f"Tenant '{tenant_id}' is active and ready to serve recommendations."
        ready_flag = True
    elif has_config and has_data:
        status_str = "ready_to_train"
        msg = f"Tenant '{tenant_id}' configuration is confirmed. Call /v1/onboard/train to build model."
        ready_flag = False
    elif has_data:
        status_str = "needs_configuration"
        msg = f"Tenant '{tenant_id}' dataset is uploaded. Call /v1/onboard/validate to inspect schema."
        ready_flag = False
    else:
        status_str = "not_started"
        msg = f"Tenant '{tenant_id}' has not uploaded data. Call /v1/onboard/upload to begin."
        ready_flag = False

    logger.info("[%s] Status check: inferred=%s (ready=%s)", tenant_id, status_str, ready_flag)
    return OnboardStatusResponse(
        tenant_id=tenant_id,
        status=status_str,
        ready=ready_flag,
        has_data=has_data,
        has_config=has_config,
        has_model=has_model,
        model_path=model_path if has_model else None,
        error=None,
        message=msg,
    )


from datetime import datetime, timezone
from src.utils.config import get_tenant_auth_records
from src.utils.key_manager import issue_tenant_keys


class RegisterKeyRequest(BaseModel):
    tenant_id: str
    api_key: str | None = None
    key_type: str = "private"


class IssueKeysPayload(BaseModel):
    tenant_id: str
    private_key: str | None = None
    public_key: str | None = None


# Unauthenticated onboarding router for public discovery and registration
open_router = APIRouter(
    prefix="/onboard",
    tags=["onboard"],
)


@open_router.get(
    "/keys",
    summary="List configured tenant authentication keys",
    description="Returns list of configured tenant IDs, their API keys, and key types.",
)
def list_tenant_keys() -> list[dict[str, Any]]:
    config = load_config()
    records = get_tenant_auth_records(config)
    load_tenant_auth(config)

    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for k, rec in records.items():
        items.append({
            "tenant_id": rec["tenant_id"],
            "api_key": k,
            "key_type": rec.get("key_type", "private"),
            "created_at": rec.get("created_at"),
        })
        seen_keys.add(k)

    return sorted(items, key=lambda x: (x["tenant_id"], x["api_key"]))


@open_router.post(
    "/register-key",
    summary="Register a new tenant API key",
    description="Registers an API key for the authenticated tenant.",
)
def register_tenant_key(
    payload: RegisterKeyRequest,
    auth_tenant: str = Depends(get_tenant_for_admin_action),
) -> dict[str, Any]:
    # tenant_id is derived strictly from authenticated credentials
    if payload.tenant_id and payload.tenant_id.strip() != auth_tenant and auth_tenant != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden: You can only register keys for your own tenant ('{auth_tenant}').",
        )

    target_tenant = payload.tenant_id.strip() if (auth_tenant == "admin" and payload.tenant_id.strip()) else auth_tenant

    if not payload.api_key or not payload.api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="api_key must be provided. Fabricating default demo keys is not permitted.",
        )

    api_key = payload.api_key.strip()
    key_type = "public" if (payload.key_type == "public" or api_key.startswith("pk-")) else "private"
    now_iso = datetime.now(timezone.utc).isoformat()

    record = {
        "tenant_id": target_tenant,
        "key_type": key_type,
        "created_at": now_iso,
    }

    local_path = resolve_path("config/tenants_auth.local.yaml")
    with atomic_yaml_write_lock(local_path):
        data = {}
        if local_path.exists():
            with open(local_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        if "tenants_auth" not in data or not isinstance(data["tenants_auth"], dict):
            data["tenants_auth"] = {}

        data["tenants_auth"][api_key] = record
        atomic_dump_yaml(local_path, data, sort_keys=False, acquire_lock=False)

    # Immediately register in in-memory auth cache
    load_tenant_auth()
    return {
        "status": "ok",
        "tenant_id": target_tenant,
        "api_key": api_key,
        "key_type": key_type,
        "created_at": now_iso,
    }


@open_router.post(
    "/issue-keys",
    summary="Issue both private and public API keys for a tenant",
    description="Generates and returns both a private organization key and a public client key for the tenant.",
)
def issue_keys_endpoint(payload: IssueKeysPayload) -> dict[str, Any]:
    tenant_id = payload.tenant_id.strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id cannot be blank")

    try:
        result = issue_tenant_keys(
            tenant_id=tenant_id,
            private_key=payload.private_key,
            public_key=payload.public_key,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result



