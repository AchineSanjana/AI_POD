"""Tests for SQS queuing of tracking events with moto mock_aws.

Verifies:
- Standard SQS queue creation.
- SQS configuration and URL resolution from environment and config.
- POST /v1/track pushes validated events onto SQS with correct tenant_id attached.
- SQS MessageAttributes contain tenant_id and event_type.
- SQS send failures are handled gracefully without failing the request (still returns 202).
"""

from __future__ import annotations

import json
import logging
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from src.api.app import app
from src.queue.tracking_queue import (
    create_tracking_queue,
    get_sqs_client,
    get_sqs_config,
    push_tracking_event_to_sqs,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_sqs_config_resolution(monkeypatch):
    """Verify get_sqs_config reads region, queue URL, and queue name from env."""
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("TRACKING_QUEUE_URL", "https://sqs.eu-west-1.amazonaws.com/123/my-queue")
    monkeypatch.setenv("TRACKING_QUEUE_NAME", "my-queue")

    region, queue_url, queue_name = get_sqs_config()
    assert region == "eu-west-1"
    assert queue_url == "https://sqs.eu-west-1.amazonaws.com/123/my-queue"
    assert queue_name == "my-queue"


def test_create_tracking_queue_moto():
    """Verify create_tracking_queue provisions a standard SQS queue."""
    with mock_aws():
        queue_url = create_tracking_queue(
            queue_name="ai-pod-tracking-events",
            region_name="us-east-1",
        )
        assert queue_url is not None
        assert "ai-pod-tracking-events" in queue_url

        # Check queue exists via client
        sqs = get_sqs_client(region_name="us-east-1")
        resp = sqs.get_queue_url(QueueName="ai-pod-tracking-events")
        assert resp["QueueUrl"] == queue_url


def test_post_track_pushes_event_to_sqs_with_correct_tenant_id(client: TestClient, monkeypatch):
    """Confirm POST /v1/track pushes validated event onto SQS with correct tenant_id."""
    with mock_aws():
        region = "us-east-1"
        monkeypatch.setenv("AWS_REGION", region)
        monkeypatch.setenv("AWS_DEFAULT_REGION", region)

        # 1. Create SQS queue in mock AWS
        queue_url = create_tracking_queue(
            queue_name="ai-pod-tracking-events",
            region_name=region,
        )
        monkeypatch.setenv("TRACKING_QUEUE_URL", queue_url)

        # 2. Send POST /v1/track with public key
        payload = {
            "event_type": "view",
            "customer_id": "cust_sqs_456",
            "session_id": "sess_sqs_browser_1",
            "product_id": "prod_high_speed_fiber",
            "quantity": 1,
            "timestamp": "2026-09-30T15:30:00Z",
        }
        resp = client.post(
            "/v1/track",
            json=payload,
            headers={"X-API-Key": "pk-telco-xxxx"},
        )
        assert resp.status_code == 202
        assert resp.json() == {"status": "accepted"}

        # 3. Pull message from SQS queue
        sqs = get_sqs_client(region_name=region)
        messages_resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            MessageAttributeNames=["All"],
        )
        messages = messages_resp.get("Messages", [])
        assert len(messages) == 1

        msg = messages[0]
        event_data = json.loads(msg["Body"])

        # 4. Verify correct tenant_id and fields
        assert event_data["tenant_id"] == "telco_default"
        assert event_data["event_type"] == "view"
        assert event_data["customer_id"] == "cust_sqs_456"
        assert event_data["session_id"] == "sess_sqs_browser_1"
        assert event_data["product_id"] == "prod_high_speed_fiber"
        assert event_data["quantity"] == 1
        assert event_data["timestamp"] == "2026-09-30T15:30:00Z"

        # 5. Verify message attributes
        msg_attrs = msg.get("MessageAttributes", {})
        assert "tenant_id" in msg_attrs
        assert msg_attrs["tenant_id"]["StringValue"] == "telco_default"
        assert "event_type" in msg_attrs
        assert msg_attrs["event_type"]["StringValue"] == "view"


def test_track_tenant_isolation_on_sqs_message(client: TestClient, monkeypatch):
    """Confirm body spoofing attempt is ignored and SQS message strictly gets authenticated tenant_id."""
    with mock_aws():
        region = "us-east-1"
        monkeypatch.setenv("AWS_REGION", region)
        monkeypatch.setenv("AWS_DEFAULT_REGION", region)

        queue_url = create_tracking_queue(
            queue_name="ai-pod-tracking-events",
            region_name=region,
        )
        monkeypatch.setenv("TRACKING_QUEUE_URL", queue_url)

        # Attempt to pass spoofed tenant_id in body
        payload = {
            "event_type": "purchase",
            "customer_id": "cust_victim",
            "session_id": "sess_spoof",
            "product_id": "prod_1",
            "tenant_id": "fixture_ecommerce",  # attacker tries to attribute to another tenant
        }
        resp = client.post(
            "/v1/track",
            json=payload,
            headers={"X-API-Key": "pk-telco-xxxx"},  # key belongs to telco_default
        )
        assert resp.status_code == 202

        sqs = get_sqs_client(region_name=region)
        messages_resp = sqs.receive_message(QueueUrl=queue_url, MessageAttributeNames=["All"])
        messages = messages_resp.get("Messages", [])
        assert len(messages) == 1

        event_data = json.loads(messages[0]["Body"])
        assert event_data["tenant_id"] == "telco_default"
        assert messages[0]["MessageAttributes"]["tenant_id"]["StringValue"] == "telco_default"


def test_sqs_send_failure_handled_gracefully(client: TestClient, monkeypatch, caplog):
    """Confirm SQS failures are logged and 202 is still returned to caller."""
    # Point to a broken/non-existent queue URL
    monkeypatch.setenv("TRACKING_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/000000000000/non-existent-queue")

    payload = {
        "event_type": "view",
        "customer_id": "cust_fail",
        "session_id": "sess_fail",
        "product_id": "prod_fail",
    }

    with caplog.at_level(logging.ERROR):
        resp = client.post(
            "/v1/track",
            json=payload,
            headers={"X-API-Key": "pk-telco-xxxx"},
        )

    # Must still return 202 Accepted to browser
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted"}

    # Error must be logged
    assert any("Failed to send tracking event to SQS" in record.message for record in caplog.records)
