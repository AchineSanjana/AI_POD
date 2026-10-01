"""Tenant training readiness checker (Step 21.2 scheduled job).

Monitors untrained tenants, inspecting their available customer and interaction data
(processed files, tracking events, and raw datasets). Once both thresholds
(MIN_CUSTOMERS_TO_TRAIN and MIN_INTERACTIONS_TO_TRAIN) are satisfied, the checker marks
the tenant as 'ready_to_train' in storage so that automated or manual training can proceed.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from src.api.onboarding import _load_training_status, _save_training_status
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.utils.config import (
    MIN_CUSTOMERS_TO_TRAIN,
    MIN_INTERACTIONS_TO_TRAIN,
    PROJECT_ROOT,
    get_tenant_auth_records,
    get_tenant_config,
    get_training_thresholds,
    load_config,
    resolve_path,
)

logger = logging.getLogger(__name__)


def is_tenant_untrained(tenant_id: str, storage: StorageBackend | None = None) -> bool:
    """Return True if the tenant has never been trained (no model exists and status != complete)."""
    if storage is None:
        storage = get_storage_backend()

    model_path = f"models/{tenant_id}/final_model.joblib"
    if storage.exists(model_path):
        return False
    if tenant_id == "telco_default" and storage.exists("models/final_model.joblib"):
        return False

    status_data = _load_training_status(tenant_id, storage=storage)
    if status_data and status_data.get("status") == "complete":
        return False

    return True


def discover_all_tenants(
    config: dict | None = None, storage: StorageBackend | None = None
) -> list[str]:
    """Discover all known tenant IDs across configuration, auth records, and storage."""
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    if storage is None:
        storage = get_storage_backend(config)

    tenants: set[str] = set()

    # 1. From config.yaml
    cfg_tenants = config.get("tenants", {})
    if isinstance(cfg_tenants, dict):
        tenants.update(cfg_tenants.keys())

    # 2. From auth records
    try:
        auth_records = get_tenant_auth_records(config)
        for rec in auth_records.values():
            t_id = rec.get("tenant_id")
            if t_id:
                tenants.add(str(t_id))
    except Exception:
        pass

    # 3. From status/ directory
    try:
        status_files = storage.list_files("status")
        for sf in status_files:
            if sf.endswith(".json") and not sf.endswith(".gitkeep"):
                stem = Path(sf).stem
                if stem:
                    tenants.add(stem)
    except Exception:
        pass

    # 4. From data/processed/ directories
    try:
        proc_files = storage.list_files("data/processed")
        for pf in proc_files:
            parts = pf.replace("\\", "/").split("/")
            if len(parts) >= 3 and parts[0] == "data" and parts[1] == "processed":
                candidate = parts[2]
                if candidate and not candidate.endswith(".csv"):
                    tenants.add(candidate)
    except Exception:
        pass

    # Filter out empty strings
    return sorted([t for t in tenants if t.strip()])


def get_tenant_customer_and_interaction_counts(
    tenant_id: str,
    config: dict | None = None,
    storage: StorageBackend | None = None,
) -> tuple[int, int]:
    """Calculate the total unique customers and total interactions recorded for a tenant."""
    if storage is None:
        storage = get_storage_backend(config)
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    customer_ids: set[str] = set()
    n_interactions = 0

    # 1. Inspect processed interactions.csv
    interactions_path = f"data/processed/{tenant_id}/interactions.csv"
    if storage.exists(interactions_path):
        try:
            content = storage.read_file(interactions_path)
            idf = pd.read_csv(io.BytesIO(content))
            n_interactions += len(idf)
            for c_col in ("customer_id", "CustomerID", "user_id"):
                if c_col in idf.columns:
                    customer_ids.update(idf[c_col].dropna().astype(str).unique())
                    break
        except Exception as exc:
            logger.warning("Error reading %s: %s", interactions_path, exc)

    # 2. Inspect processed customers.csv
    customers_path = f"data/processed/{tenant_id}/customers.csv"
    if storage.exists(customers_path):
        try:
            content = storage.read_file(customers_path)
            cdf = pd.read_csv(io.BytesIO(content))
            for c_col in ("customer_id", "customerID", "CustomerID", "user_id"):
                if c_col in cdf.columns:
                    customer_ids.update(cdf[c_col].dropna().astype(str).unique())
                    break
            else:
                if len(cdf.columns) > 0:
                    customer_ids.update(cdf.iloc[:, 0].dropna().astype(str).unique())
        except Exception as exc:
            logger.warning("Error reading %s: %s", customers_path, exc)

    # 3. Inspect in-memory tracking queue stub
    try:
        from src.api.tracking import get_queued_events

        queued = get_queued_events(tenant_id)
        n_interactions += len(queued)
        for ev in queued:
            cid = ev.get("customer_id")
            if cid:
                customer_ids.add(str(cid).strip())
    except Exception:
        pass

    # 4. If no processed interactions found, check raw data / tenant config
    if n_interactions == 0 and tenant_id in config.get("tenants", {}):
        try:
            from src.data.adapters.generic_config_adapter import GenericConfigAdapter

            t_cfg = get_tenant_config(config, tenant_id)
            adapter = GenericConfigAdapter(t_cfg, storage=storage)
            cust_df, _, int_df = adapter.run()
            n_interactions += len(int_df)
            if "customer_id" in cust_df.columns:
                customer_ids.update(cust_df["customer_id"].dropna().astype(str).unique())
        except Exception:
            pass

    return len(customer_ids), n_interactions


def mark_tenant_ready_to_train(
    tenant_id: str,
    customers_count: int,
    interactions_count: int,
    min_customers: int,
    min_interactions: int,
    storage: StorageBackend | None = None,
) -> dict[str, Any]:
    """Persist status/{tenant_id}.json marking tenant as ready_to_train."""
    if storage is None:
        storage = get_storage_backend()

    msg = (
        f"Tenant '{tenant_id}' met training thresholds "
        f"({customers_count} >= {min_customers} customers, {interactions_count} >= {min_interactions} interactions) "
        "and is ready to train."
    )
    status_dict = _save_training_status(
        tenant_id=tenant_id,
        status_val="ready_to_train",
        message=msg,
        storage=storage,
    )
    # Add threshold telemetry to status file
    status_dict["customers_count"] = customers_count
    status_dict["interactions_count"] = interactions_count
    status_dict["min_customers_threshold"] = min_customers
    status_dict["min_interactions_threshold"] = min_interactions

    payload = json.dumps(status_dict, indent=2).encode("utf-8")
    storage.write_file(f"status/{tenant_id}.json", payload)

    logger.info(
        "Marked untrained tenant '%s' as ready_to_train (%d customers, %d interactions)",
        tenant_id,
        customers_count,
        interactions_count,
    )
    return status_dict


def check_untrained_tenants_readiness(
    config: dict | None = None,
    storage: StorageBackend | None = None,
    min_customers: int | None = None,
    min_interactions: int | None = None,
) -> dict[str, Any]:
    """Check all untrained tenants against customer & interaction thresholds (Step 21.2).

    If both thresholds are satisfied, marks the tenant as 'ready_to_train'.

    Returns:
        dict summarizing checked tenants, marked ready tenants, and detail per tenant.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}
    if storage is None:
        storage = get_storage_backend(config)

    all_tenants = discover_all_tenants(config=config, storage=storage)
    logger.info("Running training readiness check across %d discovered tenants...", len(all_tenants))

    results: dict[str, Any] = {
        "checked": [],
        "marked_ready": [],
        "already_ready": [],
        "below_threshold": [],
        "details": {},
    }

    for tenant_id in all_tenants:
        if not is_tenant_untrained(tenant_id, storage=storage):
            continue

        results["checked"].append(tenant_id)

        # Thresholds (explicit argument overrides or config / defaults)
        cfg_min_c, cfg_min_i = get_training_thresholds(config, tenant_id=tenant_id)
        thresh_c = min_customers if min_customers is not None else cfg_min_c
        thresh_i = min_interactions if min_interactions is not None else cfg_min_i

        c_count, i_count = get_tenant_customer_and_interaction_counts(
            tenant_id, config=config, storage=storage
        )

        meets_customers = c_count >= thresh_c
        meets_interactions = i_count >= thresh_i
        is_ready = meets_customers and meets_interactions

        # Check existing status
        current_status_data = _load_training_status(tenant_id, storage=storage)
        curr_status = current_status_data.get("status") if current_status_data else None

        detail = {
            "tenant_id": tenant_id,
            "customers": c_count,
            "min_customers": thresh_c,
            "interactions": i_count,
            "min_interactions": thresh_i,
            "meets_customers": meets_customers,
            "meets_interactions": meets_interactions,
            "is_ready": is_ready,
            "current_status": curr_status,
        }

        if is_ready:
            if curr_status in ("ready_to_train", "ready-to-train"):
                results["already_ready"].append(tenant_id)
                detail["action"] = "already_marked"
            else:
                mark_tenant_ready_to_train(
                    tenant_id=tenant_id,
                    customers_count=c_count,
                    interactions_count=i_count,
                    min_customers=thresh_c,
                    min_interactions=thresh_i,
                    storage=storage,
                )
                results["marked_ready"].append(tenant_id)
                detail["action"] = "marked_ready_to_train"
        else:
            results["below_threshold"].append(tenant_id)
            detail["action"] = "below_threshold"

        results["details"][tenant_id] = detail

    logger.info(
        "Readiness check complete: %d checked, %d newly marked ready, %d below threshold",
        len(results["checked"]),
        len(results["marked_ready"]),
        len(results["below_threshold"]),
    )
    return results
