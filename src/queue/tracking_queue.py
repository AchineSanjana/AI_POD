"""Amazon SQS integration for ingesting real-time tracking events.

Provides utilities for:
- Resolving queue URL and AWS region from environment variables and configuration.
- Creating a standard SQS queue for incoming tracking events.
- Pushing events to SQS with graceful failure handling (never raising errors to caller).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from src.utils.config import load_config

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_NAME = "ai-pod-tracking-events"
DEFAULT_REGION = "us-east-1"


def get_sqs_config(config: dict[str, Any] | None = None) -> tuple[str, str | None, str]:
    """Resolve AWS region, SQS queue URL, and queue name from environment and config.

    Precedence:
    1. Environment variables:
       - Region: AWS_REGION, AWS_DEFAULT_REGION
       - Queue URL: TRACKING_QUEUE_URL, SQS_QUEUE_URL, EVENTS_QUEUE_URL
       - Queue Name: TRACKING_QUEUE_NAME, SQS_QUEUE_NAME
    2. Configuration dictionary:
       - config['tracking']['region'] / config['storage']['region'] / config['aws']['region']
       - config['tracking']['queue_url']
       - config['tracking']['queue_name']
    3. Defaults:
       - Region: 'us-east-1'
       - Queue Name: 'ai-pod-tracking-events'
       - Queue URL: None (resolved dynamically via get_queue_url if needed)

    Returns:
        tuple of (region, queue_url, queue_name)
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    storage_cfg = config.get("storage", {})
    tracking_cfg = config.get("tracking", {})
    aws_cfg = config.get("aws", {})

    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or tracking_cfg.get("region")
        or aws_cfg.get("region")
        or storage_cfg.get("region")
        or DEFAULT_REGION
    )

    queue_url = (
        os.environ.get("TRACKING_QUEUE_URL")
        or os.environ.get("SQS_QUEUE_URL")
        or os.environ.get("EVENTS_QUEUE_URL")
        or tracking_cfg.get("queue_url")
    )

    queue_name = (
        os.environ.get("TRACKING_QUEUE_NAME")
        or os.environ.get("SQS_QUEUE_NAME")
        or tracking_cfg.get("queue_name")
        or DEFAULT_QUEUE_NAME
    )

    return region.strip(), queue_url.strip() if queue_url else None, queue_name.strip()


def get_sqs_client(
    region_name: str | None = None,
    endpoint_url: str | None = None,
) -> Any:
    """Instantiate and return a boto3 SQS client."""
    import boto3

    region, _, _ = get_sqs_config()
    final_region = region_name or region

    client_kwargs: dict[str, Any] = {"region_name": final_region}
    ep = (
        endpoint_url
        or os.environ.get("AWS_ENDPOINT_URL")
        or os.environ.get("SQS_ENDPOINT_URL")
    )
    if ep:
        client_kwargs["endpoint_url"] = ep

    return boto3.client("sqs", **client_kwargs)


def create_tracking_queue(
    queue_name: str | None = None,
    region_name: str | None = None,
    sqs_client: Any | None = None,
    attributes: dict[str, str] | None = None,
) -> str:
    """Create a standard SQS queue for incoming tracking events.

    Args:
        queue_name: Queue name (defaults to configured queue name).
        region_name: AWS region name.
        sqs_client: Optional pre-configured boto3 SQS client.
        attributes: Optional SQS queue attributes (e.g. MessageRetentionPeriod).

    Returns:
        The URL of the created or existing SQS queue.
    """
    region, _, default_name = get_sqs_config()
    name = queue_name or default_name
    reg = region_name or region
    client = sqs_client or get_sqs_client(region_name=reg)

    create_kwargs: dict[str, Any] = {"QueueName": name}
    if attributes:
        create_kwargs["Attributes"] = attributes

    logger.info("Creating SQS tracking queue '%s' in region '%s'...", name, reg)
    resp = client.create_queue(**create_kwargs)
    queue_url = resp["QueueUrl"]
    logger.info("SQS tracking queue created successfully: %s", queue_url)
    return queue_url


def resolve_queue_url(
    sqs_client: Any | None = None,
    region_name: str | None = None,
) -> str | None:
    """Resolve the SQS queue URL from configuration or by querying SQS with the queue name."""
    region, configured_url, queue_name = get_sqs_config()
    if configured_url:
        return configured_url

    client = sqs_client or get_sqs_client(region_name=region_name or region)
    try:
        resp = client.get_queue_url(QueueName=queue_name)
        return resp.get("QueueUrl")
    except Exception as exc:
        logger.debug(
            "Could not query SQS queue URL for '%s' in region '%s': %s",
            queue_name,
            region_name or region,
            exc,
        )
        return None


def push_tracking_event_to_sqs(
    event_record: dict[str, Any],
    queue_url: str | None = None,
    sqs_client: Any | None = None,
) -> bool:
    """Push a validated tracking event record onto the SQS queue.

    Catches and logs all errors without raising, guaranteeing that any SQS
    downstream send failure never causes the endpoint to fail or surface an
    error to the caller.

    Args:
        event_record: Event payload dict including tenant_id and event details.
        queue_url: Optional explicit queue URL to override configuration.
        sqs_client: Optional boto3 SQS client instance.

    Returns:
        True if the event was pushed to SQS successfully; False if send failed.
    """
    tenant_id = event_record.get("tenant_id", "unknown")
    event_type = event_record.get("event_type", "unknown")

    try:
        region, configured_url, _ = get_sqs_config()
        client = sqs_client or get_sqs_client(region_name=region)
        target_url = queue_url or configured_url or resolve_queue_url(sqs_client=client)

        if not target_url:
            logger.error(
                "Failed to send tracking event: no SQS queue URL configured or found "
                "for tenant '%s'. Set TRACKING_QUEUE_URL or ensure queue exists.",
                tenant_id,
            )
            return False

        message_body = json.dumps(event_record)
        client.send_message(
            QueueUrl=target_url,
            MessageBody=message_body,
            MessageAttributes={
                "tenant_id": {
                    "DataType": "String",
                    "StringValue": str(tenant_id),
                },
                "event_type": {
                    "DataType": "String",
                    "StringValue": str(event_type),
                },
            },
        )
        logger.debug(
            "Successfully sent tracking event to SQS for tenant '%s' (type: '%s')",
            tenant_id,
            event_type,
        )
        return True
    except Exception as exc:
        # Graceful failure handling: Log the error, do not raise
        logger.error(
            "Failed to send tracking event to SQS for tenant '%s': %s",
            tenant_id,
            exc,
            exc_info=True,
        )
        return False
