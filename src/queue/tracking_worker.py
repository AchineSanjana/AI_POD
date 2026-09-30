"""Background worker for ingesting SQS tracking events into tenant interactions storage.

Polls the SQS tracking events queue in batches, transforms raw tracking events into
canonical InteractionSchema rows (with event weights and anonymous session handling),
appends them to the tenant's interactions dataset in S3/storage, and deletes successfully
processed messages from the queue while leaving failed ones for SQS retry/DLQ.

IDENTITY MERGING & ANONYMOUS SESSION ARCHITECTURE (Step 19.3):
--------------------------------------------------------------
1. Explicit Transition Detection:
   When an incoming event contains both a valid session_id and a recognized customer_id
   (e.g., when a visitor logs in, registers, or completes an authenticated purchase),
   the worker detects this transition and updates the tenant's identity mappings.

2. Re-attribution of Stored Interactions:
   Any interactions previously recorded under the anonymous session_id in the tenant's
   interactions dataset (data/processed/{tenant_id}/interactions.csv) are immediately
   re-attributed to the newly identified customer_id.

3. Deterministic Signal Requirement (No Guessing):
   Identity merging is performed ONLY upon receiving a clean, explicit signal containing
   both session_id and customer_id. Heuristic guessing (e.g., IP address matching,
   device fingerprinting, or temporal proximity) is intentionally avoided because it
   risks false-positive merges across shared networks (households, offices, public Wi-Fi),
   which would corrupt personalized customer profiles.

4. Session-Only Rows & Recommender Impact:
   - Personalized Recommendations: The recommendation engine filters customers against
     the tenant customer catalog (customers.csv). Anonymous session_ids do not exist in
     the customer catalog and therefore do not receive personalized recommendations until
     identified.
   - Popularity & Trending Calculations: All interaction rows, including anonymous session
     rows, contribute directly to aggregate product popularity, ranking weights, and top-seller
     calculations.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
import json
import logging
import os
import threading
from typing import Any

import pandas as pd

from src.core.schema import InteractionSchema
from src.queue.tracking_queue import (
    get_sqs_client,
    get_sqs_config,
    resolve_queue_url,
)
from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend

logger = logging.getLogger(__name__)

# Default weights applied to tracking events when converted to interaction rows
DEFAULT_EVENT_WEIGHTS: dict[str, float] = {
    "view": 1.0,
    "add_to_cart": 2.0,
    "purchase": 5.0,
}


def get_configured_event_weights(config: dict[str, Any] | None = None) -> dict[str, float]:
    """Retrieve event weights from configuration with fallback to DEFAULT_EVENT_WEIGHTS."""
    if config:
        tracking_cfg = config.get("tracking", {})
        custom_weights = tracking_cfg.get("weights")
        if isinstance(custom_weights, dict):
            weights = DEFAULT_EVENT_WEIGHTS.copy()
            for k, v in custom_weights.items():
                try:
                    weights[str(k).lower()] = float(v)
                except (ValueError, TypeError):
                    pass
            return weights
    return DEFAULT_EVENT_WEIGHTS.copy()


def detect_identity_transition(event_data: dict[str, Any]) -> tuple[str, str] | None:
    """Detect if an event carries an explicit session_id -> customer_id transition link.

    A valid transition occurs when BOTH session_id and customer_id are non-empty strings,
    customer_id is not null/empty, and session_id != customer_id.

    Returns:
        tuple of (session_id, customer_id) if clean transition detected, else None.
    """
    if not isinstance(event_data, dict):
        return None

    raw_session = event_data.get("session_id")
    raw_customer = event_data.get("customer_id")
    if not raw_session or not raw_customer:
        return None

    session_id = str(raw_session).strip()
    customer_id = str(raw_customer).strip()

    if (
        session_id
        and customer_id
        and customer_id.lower() not in ("null", "none", "nan")
        and session_id.lower() not in ("null", "none", "nan")
        and session_id != customer_id
    ):
        return (session_id, customer_id)

    return None


def load_identity_mappings(tenant_id: str, storage: StorageBackend) -> dict[str, str]:
    """Load known session_id -> customer_id identity mappings for a tenant from storage."""
    path = f"data/processed/{tenant_id}/identity_mappings.json"
    if not storage.exists(path):
        return {}
    try:
        content = storage.read_file(path)
        data = json.loads(content.decode("utf-8"))
        if isinstance(data, dict):
            mappings = data.get("mappings", data)
            if isinstance(mappings, dict):
                return {
                    str(k): str(v)
                    for k, v in mappings.items()
                    if not k.startswith("_") and str(v).lower() not in ("null", "none", "nan")
                }
    except Exception as exc:
        logger.warning("Failed to load identity mappings for tenant '%s': %s", tenant_id, exc)
    return {}


def save_identity_mappings(
    tenant_id: str,
    mappings: dict[str, str],
    storage: StorageBackend,
) -> None:
    """Persist session_id -> customer_id identity mappings for a tenant to storage."""
    if not mappings:
        return
    path = f"data/processed/{tenant_id}/identity_mappings.json"
    payload = {
        "tenant_id": tenant_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mappings": mappings,
    }
    try:
        storage.write_file(path, json.dumps(payload, indent=2).encode("utf-8"))
        logger.debug("Persisted %d identity mapping(s) for tenant '%s'", len(mappings), tenant_id)
    except Exception as exc:
        logger.error("Failed to save identity mappings for tenant '%s': %s", tenant_id, exc)


def transform_event_to_interaction(
    event_data: dict[str, Any],
    event_weights: dict[str, float] | None = None,
    identity_mappings: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Convert an incoming tracking event into an InteractionSchema row.

    Rules:
    - customer_id: Uses customer_id if provided. For anonymous events (session_id only),
      checks known identity_mappings to see if the session was linked to a customer_id;
      if not, uses session_id directly as the customer_id identifier.
    - product_id: Must be non-empty string.
    - event_type: Normalized to lowercase string (e.g. view, add_to_cart, purchase).
    - weight: Resolved from event_weights; scaled by quantity when quantity > 0.
    - timestamp: Preserves event timestamp or sets current UTC time.

    Args:
        event_data: Dictionary containing event payload.
        event_weights: Optional mapping of event_type to base weight.
        identity_mappings: Optional mapping of session_id -> customer_id for the tenant.

    Returns:
        Dict representing interaction row or None if payload is invalid.
    """
    if not isinstance(event_data, dict):
        logger.warning("Event data is not a dict: %s", type(event_data))
        return None

    # 1. Resolve customer_id (handles anonymous sessions and known session aliases)
    raw_customer_id = event_data.get("customer_id")
    if (
        raw_customer_id is not None
        and str(raw_customer_id).strip()
        and str(raw_customer_id).strip().lower() not in ("null", "none", "nan")
    ):
        effective_customer_id = str(raw_customer_id).strip()
    else:
        raw_session_id = event_data.get("session_id")
        if (
            raw_session_id is not None
            and str(raw_session_id).strip()
            and str(raw_session_id).strip().lower() not in ("null", "none", "nan")
        ):
            session_str = str(raw_session_id).strip()
            # If session_id is known in identity mappings, resolve to customer_id
            if identity_mappings and session_str in identity_mappings:
                effective_customer_id = identity_mappings[session_str]
            else:
                effective_customer_id = session_str
        else:
            logger.warning("Event rejected: missing both customer_id and session_id: %s", event_data)
            return None

    # 2. Resolve product_id
    raw_product_id = event_data.get("product_id")
    if (
        not raw_product_id
        or not str(raw_product_id).strip()
        or str(raw_product_id).strip().lower() in ("null", "none", "nan")
    ):
        logger.warning("Event rejected: missing or invalid product_id: %s", event_data)
        return None
    product_id = str(raw_product_id).strip()

    # 3. Resolve event_type and weight
    raw_event_type = event_data.get("event_type", "view")
    event_type = str(raw_event_type).strip().lower()

    weights = event_weights or DEFAULT_EVENT_WEIGHTS
    base_weight = float(weights.get(event_type, 1.0))

    quantity = event_data.get("quantity")
    if quantity is not None and isinstance(quantity, (int, float)) and quantity > 0:
        weight = float(base_weight * quantity)
    else:
        weight = float(base_weight)

    # 4. Resolve timestamp
    raw_ts = event_data.get("timestamp")
    if raw_ts and str(raw_ts).strip():
        timestamp = str(raw_ts).strip()
    else:
        timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "customer_id": effective_customer_id,
        "product_id": product_id,
        "event_type": event_type,
        "weight": weight,
        "timestamp": timestamp,
    }


def append_tenant_interactions(
    tenant_id: str,
    new_rows: list[dict[str, Any]],
    storage: StorageBackend,
    identity_mappings: dict[str, str] | None = None,
) -> None:
    """Append interaction rows to tenant's interactions data and re-attribute anonymous sessions.

    Maintains canonical schema:
    data/processed/{tenant_id}/interactions.csv

    Identity Merging:
    If identity_mappings are provided (session_id -> customer_id), any existing rows
    stored under those session_ids are re-attributed to the corresponding real customer_id.

    Validates combined output against InteractionSchema so the existing training
    pipeline can consume it directly without modification.

    Args:
        tenant_id: Identifier of the tenant.
        new_rows: List of interaction row dicts.
        storage: Target StorageBackend (LocalStorage or S3Storage).
        identity_mappings: Optional session_id -> customer_id mappings for re-attribution.
    """
    path = f"data/processed/{tenant_id}/interactions.csv"
    existing_df = pd.DataFrame()

    if storage.exists(path):
        try:
            content = storage.read_file(path)
            if content and content.strip():
                existing_df = pd.read_csv(io.BytesIO(content))
        except Exception as exc:
            logger.warning(
                "Could not parse existing interactions for tenant '%s', overwriting: %s",
                tenant_id,
                exc,
            )

    # 1. Apply identity re-attribution to existing interactions
    if identity_mappings and not existing_df.empty and "customer_id" in existing_df.columns:
        for session_id, real_cust_id in identity_mappings.items():
            mask = existing_df["customer_id"].astype(str) == str(session_id)
            match_count = int(mask.sum())
            if match_count > 0:
                existing_df.loc[mask, "customer_id"] = str(real_cust_id)
                logger.info(
                    "Re-attributed %d interaction(s) for tenant '%s' from session '%s' to customer '%s'",
                    match_count,
                    tenant_id,
                    session_id,
                    real_cust_id,
                )

    # 2. Prepare new rows DataFrame and apply re-attribution if needed
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        if identity_mappings and "customer_id" in new_df.columns:
            for session_id, real_cust_id in identity_mappings.items():
                mask = new_df["customer_id"].astype(str) == str(session_id)
                if mask.any():
                    new_df.loc[mask, "customer_id"] = str(real_cust_id)
        if not existing_df.empty:
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        else:
            combined_df = new_df
    else:
        combined_df = existing_df

    if combined_df.empty:
        return

    # Standardize column order with primary keys first
    all_cols = list(combined_df.columns)
    ordered_cols = ["customer_id", "product_id"] + [
        c for c in all_cols if c not in ("customer_id", "product_id")
    ]
    combined_df = combined_df[ordered_cols]

    # Ensure weight is numeric and defaults to 1.0 if missing
    if "weight" in combined_df.columns:
        combined_df["weight"] = (
            pd.to_numeric(combined_df["weight"], errors="coerce")
            .fillna(InteractionSchema.default_weight)
            .astype(float)
        )

    # Validate against InteractionSchema
    schema = InteractionSchema()
    schema.validate(combined_df)
    schema.validate_values(combined_df)

    # Persist back to storage
    out_csv = combined_df.to_csv(index=False).encode("utf-8")
    storage.write_file(path, out_csv)
    logger.info(
        "Successfully wrote interactions to '%s' (new: %d, total: %d rows)",
        path,
        len(new_rows),
        len(combined_df),
    )


def process_tracking_batch(
    queue_url: str | None = None,
    sqs_client: Any | None = None,
    storage: StorageBackend | None = None,
    max_messages: int = 10,
    wait_time_seconds: int = 1,
    event_weights: dict[str, float] | None = None,
) -> int:
    """Poll a batch of tracking events from SQS, process and append to storage, and delete handled messages.

    Handles:
    - Long-polling SQS in batches.
    - Detecting identity transitions (session_id -> customer_id).
    - Re-attributing stored interactions under the session_id to the real customer_id.
    - Deleting successfully processed messages, leaving failed messages for retry/DLQ.

    Args:
        queue_url: Optional explicit SQS queue URL.
        sqs_client: Optional boto3 SQS client.
        storage: Optional StorageBackend instance.
        max_messages: Maximum messages to retrieve in batch (max 10 for SQS).
        wait_time_seconds: SQS long-polling wait time in seconds (0-20).
        event_weights: Optional custom event weight mapping.

    Returns:
        Number of successfully processed and deleted messages.
    """
    region, configured_url, _ = get_sqs_config()
    client = sqs_client or get_sqs_client(region_name=region)
    target_url = queue_url or configured_url or resolve_queue_url(sqs_client=client)

    if not target_url:
        logger.warning("No SQS queue URL found. Skipping batch polling.")
        return 0

    storage_backend = storage or get_storage_backend()
    weights = event_weights or DEFAULT_EVENT_WEIGHTS

    # 1. Poll SQS for a batch of messages
    batch_size = min(max(1, max_messages), 10)
    try:
        response = client.receive_message(
            QueueUrl=target_url,
            MaxNumberOfMessages=batch_size,
            WaitTimeSeconds=max(0, wait_time_seconds),
            MessageAttributeNames=["All"],
        )
    except Exception as exc:
        logger.error("Failed to receive messages from SQS queue '%s': %s", target_url, exc)
        return 0

    messages = response.get("Messages", [])
    if not messages:
        return 0

    logger.debug("Received %d message(s) from SQS queue", len(messages))

    # 2. Parse messages, extract tenant_id, and detect identity transitions
    # Map: tenant_id -> list of (raw_event_data, receipt_handle)
    tenant_raw_events: dict[str, list[tuple[dict[str, Any], str]]] = {}
    # Map: tenant_id -> dict of {session_id: customer_id} newly detected in this batch
    tenant_new_transitions: dict[str, dict[str, str]] = {}

    for msg in messages:
        receipt_handle = msg.get("ReceiptHandle")
        if not receipt_handle:
            continue

        raw_body = msg.get("Body", "")
        try:
            event_data = json.loads(raw_body)
        except Exception as exc:
            logger.error(
                "Failed to parse SQS message JSON (leaving for DLQ/retry): %s", exc
            )
            continue

        # Extract tenant_id from body or message attributes
        tenant_id = event_data.get("tenant_id")
        if not tenant_id:
            attr_tenant = (
                msg.get("MessageAttributes", {})
                .get("tenant_id", {})
                .get("StringValue")
            )
            tenant_id = attr_tenant

        if not tenant_id or not str(tenant_id).strip():
            logger.error(
                "SQS event missing tenant_id (leaving for DLQ/retry): %s", event_data
            )
            continue

        clean_tenant_id = str(tenant_id).strip()
        tenant_raw_events.setdefault(clean_tenant_id, []).append((event_data, receipt_handle))

        # Check for explicit identity transition in this event
        transition = detect_identity_transition(event_data)
        if transition:
            sess_id, cust_id = transition
            tenant_new_transitions.setdefault(clean_tenant_id, {})[sess_id] = cust_id
            logger.info(
                "Detected identity transition for tenant '%s': session '%s' -> customer '%s'",
                clean_tenant_id,
                sess_id,
                cust_id,
            )

    # 3. For each tenant, load identity mappings, transform events, re-attribute and append
    successful_handles: list[str] = []

    for t_id, raw_items in tenant_raw_events.items():
        # Load known identity mappings for this tenant
        identity_mappings = load_identity_mappings(tenant_id=t_id, storage=storage_backend)

        # Merge newly discovered transitions
        new_transitions = tenant_new_transitions.get(t_id, {})
        if new_transitions:
            identity_mappings.update(new_transitions)
            save_identity_mappings(t_id, identity_mappings, storage=storage_backend)

        transformed_rows: list[dict[str, Any]] = []
        item_handles: list[str] = []

        for event_data, r_handle in raw_items:
            transformed = transform_event_to_interaction(
                event_data,
                event_weights=weights,
                identity_mappings=identity_mappings,
            )
            if transformed is None:
                logger.error(
                    "Failed to transform SQS event for tenant '%s' (leaving for DLQ/retry): %s",
                    t_id,
                    event_data,
                )
                continue

            transformed_rows.append(transformed)
            item_handles.append(r_handle)

        if not transformed_rows and not new_transitions:
            continue

        try:
            append_tenant_interactions(
                tenant_id=t_id,
                new_rows=transformed_rows,
                storage=storage_backend,
                identity_mappings=identity_mappings,
            )
            successful_handles.extend(item_handles)
        except Exception as exc:
            logger.exception(
                "Failed to write interactions for tenant '%s' (%d items); leaving for SQS retry: %s",
                t_id,
                len(transformed_rows),
                exc,
            )

    # 4. Delete successfully processed messages from SQS
    if successful_handles:
        _delete_messages_from_sqs(client, target_url, successful_handles)

    return len(successful_handles)


def _delete_messages_from_sqs(
    client: Any,
    queue_url: str,
    receipt_handles: list[str],
) -> None:
    """Delete a collection of messages from SQS using delete_message_batch (chunks of 10)."""
    chunk_size = 10
    for i in range(0, len(receipt_handles), chunk_size):
        chunk = receipt_handles[i : i + chunk_size]
        entries = [
            {"Id": f"msg_{idx}", "ReceiptHandle": handle}
            for idx, handle in enumerate(chunk)
        ]
        try:
            client.delete_message_batch(QueueUrl=queue_url, Entries=entries)
            logger.debug("Deleted batch of %d message(s) from SQS", len(entries))
        except Exception as exc:
            logger.error("Failed to delete message batch from SQS: %s", exc)
            for entry in entries:
                try:
                    client.delete_message(
                        QueueUrl=queue_url, ReceiptHandle=entry["ReceiptHandle"]
                    )
                except Exception as inner_exc:
                    logger.error(
                        "Failed to delete individual message from SQS: %s", inner_exc
                    )


class TrackingWorker:
    """Background worker daemon thread that continuously polls SQS for tracking events."""

    def __init__(
        self,
        queue_url: str | None = None,
        sqs_client: Any | None = None,
        storage: StorageBackend | None = None,
        poll_interval: float = 10.0,
        wait_time_seconds: int = 10,
        max_messages: int = 10,
        event_weights: dict[str, float] | None = None,
    ) -> None:
        self.queue_url = queue_url
        self.sqs_client = sqs_client
        self.storage = storage
        self.poll_interval = max(0.1, poll_interval)
        self.wait_time_seconds = wait_time_seconds
        self.max_messages = max_messages
        self.event_weights = event_weights

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def process_once(self) -> int:
        """Execute a single batch cycle synchronously."""
        return process_tracking_batch(
            queue_url=self.queue_url,
            sqs_client=self.sqs_client,
            storage=self.storage,
            max_messages=self.max_messages,
            wait_time_seconds=self.wait_time_seconds,
            event_weights=self.event_weights,
        )

    def _worker_loop(self) -> None:
        """Internal daemon loop polling SQS until stopped."""
        logger.info(
            "TrackingWorker started (poll_interval=%.1fs, wait_time=%ds)",
            self.poll_interval,
            self.wait_time_seconds,
        )
        while not self._stop_event.is_set():
            try:
                processed = self.process_once()
                if processed > 0:
                    logger.info("TrackingWorker processed and deleted %d message(s)", processed)
            except Exception as exc:
                logger.exception("Unexpected error in TrackingWorker loop: %s", exc)

            self._stop_event.wait(self.poll_interval)

        logger.info("TrackingWorker stopped gracefully.")

    def start(self) -> TrackingWorker:
        """Start the background worker in a daemon thread (Step 15.5 pattern)."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("TrackingWorker is already running.")
            return self

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            name="tracking-sqs-worker",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the background worker to stop and wait for completion."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        """Return True if background worker thread is running."""
        return self._thread is not None and self._thread.is_alive()


# Active singleton worker instance
_GLOBAL_TRACKING_WORKER: TrackingWorker | None = None


def get_tracking_worker() -> TrackingWorker | None:
    """Return the global active TrackingWorker instance if started."""
    global _GLOBAL_TRACKING_WORKER
    return _GLOBAL_TRACKING_WORKER


def start_background_tracking_worker(
    queue_url: str | None = None,
    sqs_client: Any | None = None,
    storage: StorageBackend | None = None,
    poll_interval: float = 10.0,
    wait_time_seconds: int = 10,
    max_messages: int = 10,
    event_weights: dict[str, float] | None = None,
) -> TrackingWorker:
    """Start and register the global background TrackingWorker thread."""
    global _GLOBAL_TRACKING_WORKER
    if _GLOBAL_TRACKING_WORKER is not None and _GLOBAL_TRACKING_WORKER.is_alive():
        return _GLOBAL_TRACKING_WORKER

    worker = TrackingWorker(
        queue_url=queue_url,
        sqs_client=sqs_client,
        storage=storage,
        poll_interval=poll_interval,
        wait_time_seconds=wait_time_seconds,
        max_messages=max_messages,
        event_weights=event_weights,
    )
    worker.start()
    _GLOBAL_TRACKING_WORKER = worker
    return worker


def stop_background_tracking_worker(timeout: float = 5.0) -> None:
    """Stop the global background TrackingWorker thread."""
    global _GLOBAL_TRACKING_WORKER
    if _GLOBAL_TRACKING_WORKER is not None:
        _GLOBAL_TRACKING_WORKER.stop(timeout=timeout)
        _GLOBAL_TRACKING_WORKER = None
