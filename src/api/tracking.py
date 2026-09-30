"""Client-side tracking API endpoint for real-time interaction and conversion events.

Authenticated strictly by public API keys ('pk-...'). Pushes validated events onto
an in-memory ingestion queue (stubbed for Step 19) and returns 202 Accepted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import get_public_key_tenant
from src.api.rate_limiter import check_rate_limit
from src.api.schemas import TrackEventAcceptedResponse
from src.queue.tracking_queue import push_tracking_event_to_sqs

router = APIRouter(
    prefix="/track",
    tags=["tracking"],
    dependencies=[Depends(check_rate_limit(scope="tracking"))],
)

# ---------------------------------------------------------------------------
# Step 19 Queue Stub: In-memory event buffer
# ---------------------------------------------------------------------------
EVENT_QUEUE: list[dict[str, Any]] = []


def push_event(event: dict[str, Any]) -> None:
    """Push an event record onto the ingestion queue."""
    EVENT_QUEUE.append(event)


def get_queued_events(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Retrieve queued events, optionally filtered by tenant_id."""
    if tenant_id is None:
        return list(EVENT_QUEUE)
    return [e for e in EVENT_QUEUE if e.get("tenant_id") == tenant_id]


def clear_queue() -> None:
    """Clear all events in the queue stub (useful for test isolation)."""
    EVENT_QUEUE.clear()


# ---------------------------------------------------------------------------
# POST /v1/track Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=202,
    response_model=TrackEventAcceptedResponse,
    summary="Track client interaction event",
    description="Record a client interaction event. Authenticated strictly by public API keys.",
)
async def track_event(
    request: Request,
    tenant_id: str = Depends(get_public_key_tenant),
) -> dict[str, str]:
    """Ingest a single client interaction event.

    - Authenticated by a public key only.
    - Validates payload shape, rejecting malformed events with 400.
    - Resolves tenant from public key (never from body).
    - Pushes event onto queue (Step 19 stub).
    - Returns minimal 202 Accepted response.
    """
    # 1. Parse JSON body
    try:
        raw_body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed JSON in request body")

    if not isinstance(raw_body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    # 2. Validate payload shape
    event_type = raw_body.get("event_type")
    if event_type not in {"view", "add_to_cart", "purchase"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid 'event_type': must be one of 'view', 'add_to_cart', 'purchase'",
        )

    session_id = raw_body.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise HTTPException(
            status_code=400,
            detail="Missing or invalid 'session_id': non-empty string required",
        )

    product_id = raw_body.get("product_id")
    if not isinstance(product_id, str) or not product_id.strip():
        raise HTTPException(
            status_code=400,
            detail="Missing or invalid 'product_id': non-empty string required",
        )

    customer_id = raw_body.get("customer_id")
    if customer_id is not None and not isinstance(customer_id, str):
        raise HTTPException(
            status_code=400,
            detail="Invalid 'customer_id': must be string or null",
        )
    if isinstance(customer_id, str):
        customer_id = customer_id.strip() or None

    quantity = raw_body.get("quantity")
    if quantity is not None:
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
            raise HTTPException(
                status_code=400,
                detail="Invalid 'quantity': must be a number",
            )
        if quantity < 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid 'quantity': cannot be negative",
            )

    ts = raw_body.get("timestamp")
    if ts is not None and not isinstance(ts, str):
        raise HTTPException(
            status_code=400,
            detail="Invalid 'timestamp': must be an ISO 8601 string",
        )
    if not ts or not str(ts).strip():
        timestamp = datetime.now(timezone.utc).isoformat()
    else:
        timestamp = str(ts).strip()

    # 3. Build event record: tenant_id strictly resolved from public key
    event_record = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "customer_id": customer_id,
        "session_id": session_id.strip(),
        "product_id": product_id.strip(),
        "quantity": quantity,
        "timestamp": timestamp,
    }

    # 4. Push validated event record onto Amazon SQS queue (and in-memory buffer)
    push_event(event_record)
    push_tracking_event_to_sqs(event_record)

    # 5. Return fast minimal 202 Accepted response
    return {"status": "accepted"}
