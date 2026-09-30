"""Tests for background tracking worker ingesting SQS events into S3 interactions.

Verifies:
- Event transformation into InteractionSchema rows with weights and anonymous session IDs.
- Appending interaction rows into tenant S3/storage datasets.
- Batched SQS polling, event processing, S3 persistence, and queue deletion.
- Failed / invalid messages remain in SQS for retry / dead-letter handling.
- Appended S3 interactions data conforms strictly to InteractionSchema and pipeline expectations.
"""

from __future__ import annotations

import io
import json
import os
import boto3
import pandas as pd
import pytest
from moto import mock_aws

from src.core.schema import InteractionSchema
from src.queue.tracking_queue import create_tracking_queue, get_sqs_client
from src.queue.tracking_worker import (
    TrackingWorker,
    append_tenant_interactions,
    detect_identity_transition,
    load_identity_mappings,
    process_tracking_batch,
    save_identity_mappings,
    transform_event_to_interaction,
)
from src.storage.s3_storage import S3Storage


@pytest.fixture
def aws_env(monkeypatch):
    """Set standard AWS environment variables for moto tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def test_transform_event_anonymous_session():
    """Anonymous events (customer_id is null/empty) must use session_id as customer_id."""
    event = {
        "event_type": "view",
        "customer_id": None,
        "session_id": "sess_anon_987",
        "product_id": "prod_phone_12",
        "quantity": 1,
        "timestamp": "2026-09-30T12:00:00Z",
    }
    row = transform_event_to_interaction(event)
    assert row is not None
    assert row["customer_id"] == "sess_anon_987"
    assert row["product_id"] == "prod_phone_12"
    assert row["event_type"] == "view"
    assert row["weight"] == 1.0
    assert row["timestamp"] == "2026-09-30T12:00:00Z"


def test_transform_event_authenticated_user():
    """Authenticated events must preserve customer_id."""
    event = {
        "event_type": "add_to_cart",
        "customer_id": "cust_alice_456",
        "session_id": "sess_browser_001",
        "product_id": "prod_tablet_01",
        "quantity": 1,
    }
    row = transform_event_to_interaction(event)
    assert row is not None
    assert row["customer_id"] == "cust_alice_456"
    assert row["product_id"] == "prod_tablet_01"
    assert row["event_type"] == "add_to_cart"
    assert row["weight"] == 2.0
    assert row["timestamp"] is not None


def test_transform_event_purchase_with_quantity():
    """Purchase events must have higher weight and scale with quantity."""
    event = {
        "event_type": "purchase",
        "customer_id": "cust_bob_789",
        "session_id": "sess_browser_002",
        "product_id": "prod_laptop_02",
        "quantity": 3,
    }
    row = transform_event_to_interaction(event)
    assert row is not None
    # Base purchase weight is 5.0 * 3 = 15.0
    assert row["weight"] == 15.0
    assert row["event_type"] == "purchase"


def test_transform_event_invalid_missing_ids():
    """Events missing both customer_id and session_id or missing product_id must be rejected."""
    # Missing customer_id and session_id
    bad_event_1 = {"event_type": "view", "product_id": "prod_1"}
    assert transform_event_to_interaction(bad_event_1) is None

    # Missing product_id
    bad_event_2 = {"event_type": "view", "session_id": "sess_1", "product_id": ""}
    assert transform_event_to_interaction(bad_event_2) is None


@mock_aws
def test_append_tenant_interactions_to_s3(aws_env):
    """Verify appending interaction rows creates or updates interactions.csv in S3."""
    s3_client = boto3.client("s3", region_name="us-east-1")
    bucket_name = "test-ai-pod-bucket"
    s3_client.create_bucket(Bucket=bucket_name)

    storage = S3Storage(bucket_name=bucket_name, region_name="us-east-1")
    tenant_id = "test_tenant"

    initial_rows = [
        {
            "customer_id": "cust_1",
            "product_id": "prod_a",
            "event_type": "view",
            "weight": 1.0,
            "timestamp": "2026-09-30T10:00:00Z",
        }
    ]
    append_tenant_interactions(tenant_id, initial_rows, storage)

    path = f"data/processed/{tenant_id}/interactions.csv"
    assert storage.exists(path)

    # Append second batch
    second_rows = [
        {
            "customer_id": "sess_anon_99",
            "product_id": "prod_b",
            "event_type": "purchase",
            "weight": 5.0,
            "timestamp": "2026-09-30T11:00:00Z",
        }
    ]
    append_tenant_interactions(tenant_id, second_rows, storage)

    # Read back and validate schema
    content = storage.read_file(path)
    df = pd.read_csv(io.BytesIO(content))
    assert len(df) == 2
    assert list(df["customer_id"]) == ["cust_1", "sess_anon_99"]
    assert list(df["product_id"]) == ["prod_a", "prod_b"]
    assert list(df["weight"]) == [1.0, 5.0]

    schema = InteractionSchema()
    schema.validate(df)
    schema.validate_values(df)


@mock_aws
def test_process_tracking_batch_end_to_end_s3(aws_env, monkeypatch):
    """End-to-end test confirming fake queued events appear correctly in tenant's S3 interactions.

    1. Enqueue 3 fake events (anonymous view, authenticated cart, purchase with quantity).
    2. Run process_tracking_batch.
    3. Confirm messages are deleted from SQS.
    4. Confirm S3 interactions.csv contains all rows with expected schema and weights.
    """
    region = "us-east-1"
    bucket_name = "test-tracking-s3-bucket"

    # 1. Setup mock S3
    s3_client = boto3.client("s3", region_name=region)
    s3_client.create_bucket(Bucket=bucket_name)

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_REGION", region)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)

    # 2. Setup mock SQS queue
    queue_url = create_tracking_queue(
        queue_name="ai-pod-tracking-events",
        region_name=region,
    )
    sqs_client = get_sqs_client(region_name=region)

    # 3. Enqueue fake tracking events for tenant 'telco_default'
    fake_events = [
        {
            "tenant_id": "telco_default",
            "event_type": "view",
            "customer_id": None,  # anonymous session
            "session_id": "sess_anon_visitor_01",
            "product_id": "prod_internet_fiber",
            "quantity": 1,
            "timestamp": "2026-09-30T14:00:00Z",
        },
        {
            "tenant_id": "telco_default",
            "event_type": "add_to_cart",
            "customer_id": "cust_authenticated_101",
            "session_id": "sess_user_02",
            "product_id": "prod_streaming_addon",
            "quantity": 1,
            "timestamp": "2026-09-30T14:05:00Z",
        },
        {
            "tenant_id": "telco_default",
            "event_type": "purchase",
            "customer_id": "cust_authenticated_102",
            "session_id": "sess_user_03",
            "product_id": "prod_phone_bundle",
            "quantity": 2,  # quantity 2 -> 5.0 * 2 = 10.0
            "timestamp": "2026-09-30T14:10:00Z",
        },
    ]

    for ev in fake_events:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(ev),
            MessageAttributes={
                "tenant_id": {"DataType": "String", "StringValue": ev["tenant_id"]},
                "event_type": {"DataType": "String", "StringValue": ev["event_type"]},
            },
        )

    # Verify messages are in SQS
    initial_check = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        VisibilityTimeout=0,  # Make immediately visible again
    )
    assert len(initial_check.get("Messages", [])) == 3

    # 4. Execute batch worker
    processed_count = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs_client,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    assert processed_count == 3

    # 5. Confirm messages were deleted from SQS
    remaining = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=0,
    )
    assert "Messages" not in remaining or len(remaining["Messages"]) == 0

    # 6. Confirm events appear correctly in tenant's S3 interactions.csv
    interactions_path = "data/processed/telco_default/interactions.csv"
    assert storage.exists(interactions_path)

    raw_csv = storage.read_file(interactions_path)
    interactions_df = pd.read_csv(io.BytesIO(raw_csv))

    assert len(interactions_df) == 3
    # Check column shape matches pipeline requirements
    assert "customer_id" in interactions_df.columns
    assert "product_id" in interactions_df.columns
    assert "event_type" in interactions_df.columns
    assert "weight" in interactions_df.columns
    assert "timestamp" in interactions_df.columns

    # Verify anonymous session customer_id handling
    assert interactions_df.loc[0, "customer_id"] == "sess_anon_visitor_01"
    assert interactions_df.loc[0, "product_id"] == "prod_internet_fiber"
    assert interactions_df.loc[0, "event_type"] == "view"
    assert interactions_df.loc[0, "weight"] == 1.0

    # Verify authenticated cart event
    assert interactions_df.loc[1, "customer_id"] == "cust_authenticated_101"
    assert interactions_df.loc[1, "product_id"] == "prod_streaming_addon"
    assert interactions_df.loc[1, "event_type"] == "add_to_cart"
    assert interactions_df.loc[1, "weight"] == 2.0

    # Verify purchase event with quantity weighting (5.0 * 2 = 10.0)
    assert interactions_df.loc[2, "customer_id"] == "cust_authenticated_102"
    assert interactions_df.loc[2, "product_id"] == "prod_phone_bundle"
    assert interactions_df.loc[2, "event_type"] == "purchase"
    assert interactions_df.loc[2, "weight"] == 10.0

    # 7. Verify InteractionSchema compliance
    schema = InteractionSchema()
    schema.validate(interactions_df)
    schema.validate_values(interactions_df)


@mock_aws
def test_process_tracking_batch_leaves_failed_message_on_queue(aws_env):
    """Corrupted messages must not be deleted from SQS (left for DLQ/retry)."""
    region = "us-east-1"
    bucket_name = "test-dlq-bucket"
    s3_client = boto3.client("s3", region_name=region)
    s3_client.create_bucket(Bucket=bucket_name)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    queue_url = create_tracking_queue(
        queue_name="dlq-test-queue",
        region_name=region,
        attributes={"VisibilityTimeout": "0"},
    )
    sqs_client = get_sqs_client(region_name=region)

    # 1. Send one valid message and one unparseable corrupted message
    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody="INVALID NOT JSON {{{",
    )
    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(
            {
                "tenant_id": "tenant_valid",
                "event_type": "view",
                "customer_id": "cust_valid",
                "session_id": "sess_valid",
                "product_id": "prod_valid",
            }
        ),
    )

    # 2. Run batch
    processed_count = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs_client,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    # Only the valid message was processed and deleted
    assert processed_count == 1

    # 3. Check remaining on queue: invalid message was not deleted and is still on the queue
    remaining = sqs_client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=0,
    )
    messages = remaining.get("Messages", [])
    assert len(messages) == 1
    assert messages[0]["Body"] == "INVALID NOT JSON {{{"


@mock_aws
def test_tracking_worker_thread_lifecycle(aws_env):
    """Test TrackingWorker daemon thread start and stop methods."""
    region = "us-east-1"
    queue_url = create_tracking_queue(queue_name="lifecycle-test-queue", region_name=region)
    sqs_client = get_sqs_client(region_name=region)

    worker = TrackingWorker(
        queue_url=queue_url,
        sqs_client=sqs_client,
        poll_interval=0.1,
        wait_time_seconds=0,
    )
    assert not worker.is_alive()

    worker.start()
    assert worker.is_alive()

    worker.stop(timeout=1.0)
    assert not worker.is_alive()


def test_detect_identity_transition():
    """Verify detect_identity_transition identifies explicit links and ignores unlinked events."""
    # Valid transition
    t1 = detect_identity_transition({"session_id": "sess_01", "customer_id": "cust_100"})
    assert t1 == ("sess_01", "cust_100")

    # Anonymous event: no customer_id
    t2 = detect_identity_transition({"session_id": "sess_01", "customer_id": None})
    assert t2 is None

    # Customer ID is null string
    t3 = detect_identity_transition({"session_id": "sess_01", "customer_id": "null"})
    assert t3 is None

    # Same identifier (not a transition)
    t4 = detect_identity_transition({"session_id": "cust_100", "customer_id": "cust_100"})
    assert t4 is None


@mock_aws
def test_identity_mapping_persistence(aws_env):
    """Verify saving and loading identity mappings in S3."""
    region = "us-east-1"
    bucket_name = "test-mapping-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)
    storage = S3Storage(bucket_name=bucket_name, region_name=region)

    tenant_id = "test_tenant"
    assert load_identity_mappings(tenant_id, storage) == {}

    mappings = {"sess_alpha": "cust_01", "sess_beta": "cust_02"}
    save_identity_mappings(tenant_id, mappings, storage)

    loaded = load_identity_mappings(tenant_id, storage)
    assert loaded == mappings


@mock_aws
def test_anonymous_views_then_authenticated_purchase_merges_earlier_events(aws_env, monkeypatch):
    """Simulate anonymous view events, then a purchase carrying a real customer_id.

    Confirm that:
    1. Earlier anonymous events get stored under session_id.
    2. Once the purchase event with real customer_id arrives, earlier events are re-attributed.
    3. The final dataset has all interactions merged under the real customer_id.
    """
    region = "us-east-1"
    bucket_name = "test-identity-merge-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_REGION", region)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    queue_url = create_tracking_queue(queue_name="merge-test-queue", region_name=region)
    sqs = get_sqs_client(region_name=region)
    tenant_id = "ecom_brand"

    # Step 1: Anonymous browsing - visitor views two products
    session_id = "sess_shopper_42"
    anon_events = [
        {
            "tenant_id": tenant_id,
            "event_type": "view",
            "customer_id": None,
            "session_id": session_id,
            "product_id": "prod_running_shoes",
            "timestamp": "2026-09-30T10:00:00Z",
        },
        {
            "tenant_id": tenant_id,
            "event_type": "view",
            "customer_id": None,
            "session_id": session_id,
            "product_id": "prod_sports_jacket",
            "timestamp": "2026-09-30T10:05:00Z",
        },
    ]

    for ev in anon_events:
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(ev))

    # Process first batch
    processed_1 = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    assert processed_1 == 2

    # Verify initial storage state: rows exist under session_id
    interactions_path = f"data/processed/{tenant_id}/interactions.csv"
    assert storage.exists(interactions_path)
    df_initial = pd.read_csv(io.BytesIO(storage.read_file(interactions_path)))
    assert len(df_initial) == 2
    assert (df_initial["customer_id"] == session_id).all()

    # Step 2: Visitor completes a purchase with an identified account
    real_customer_id = "cust_sarah_100"
    purchase_event = {
        "tenant_id": tenant_id,
        "event_type": "purchase",
        "customer_id": real_customer_id,
        "session_id": session_id,  # Clean signal linking session to customer!
        "product_id": "prod_running_shoes",
        "quantity": 1,
        "timestamp": "2026-09-30T10:15:00Z",
    }
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(purchase_event))

    # Process second batch
    processed_2 = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    assert processed_2 == 1

    # Step 3: Verify that earlier anonymous view events have been re-attributed
    df_merged = pd.read_csv(io.BytesIO(storage.read_file(interactions_path)))
    assert len(df_merged) == 3

    # All rows must now belong to the real customer_id
    assert (df_merged["customer_id"] == real_customer_id).all()
    # No rows remain under the raw session_id
    assert not (df_merged["customer_id"] == session_id).any()

    # Check products and event types
    assert set(df_merged["product_id"]) == {"prod_running_shoes", "prod_sports_jacket"}
    assert set(df_merged["event_type"]) == {"view", "purchase"}

    # Schema must validate cleanly
    schema = InteractionSchema()
    schema.validate(df_merged)
    schema.validate_values(df_merged)

    # Step 4: Subsequent event with only session_id is also mapped via saved identity mappings
    followup_anon_event = {
        "tenant_id": tenant_id,
        "event_type": "view",
        "customer_id": None,
        "session_id": session_id,
        "product_id": "prod_socks",
        "timestamp": "2026-09-30T10:30:00Z",
    }
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(followup_anon_event))

    processed_3 = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    assert processed_3 == 1

    df_final = pd.read_csv(io.BytesIO(storage.read_file(interactions_path)))
    assert len(df_final) == 4
    assert (df_final["customer_id"] == real_customer_id).all()


@mock_aws
def test_same_batch_identity_merge(aws_env, monkeypatch):
    """Anonymous view and authenticated purchase arriving in the same batch get merged."""
    region = "us-east-1"
    bucket_name = "test-same-batch-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    queue_url = create_tracking_queue(queue_name="same-batch-queue", region_name=region)
    sqs = get_sqs_client(region_name=region)
    tenant_id = "telco_default"

    session_id = "sess_new_visitor"
    real_customer_id = "cust_registered_user"

    events = [
        {
            "tenant_id": tenant_id,
            "event_type": "view",
            "customer_id": None,
            "session_id": session_id,
            "product_id": "prod_wifi_mesh",
        },
        {
            "tenant_id": tenant_id,
            "event_type": "purchase",
            "customer_id": real_customer_id,
            "session_id": session_id,
            "product_id": "prod_wifi_mesh",
        },
    ]

    for ev in events:
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(ev))

    processed = process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )
    assert processed == 2

    interactions_path = f"data/processed/{tenant_id}/interactions.csv"
    df = pd.read_csv(io.BytesIO(storage.read_file(interactions_path)))
    assert len(df) == 2
    # Both events must be attributed to real_customer_id
    assert list(df["customer_id"]) == [real_customer_id, real_customer_id]


@mock_aws
def test_unreliable_merge_fallback_remains_session_only(aws_env, monkeypatch):
    """Without an explicit link, anonymous events remain session-only and are not guessed."""
    region = "us-east-1"
    bucket_name = "test-unlinked-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    queue_url = create_tracking_queue(queue_name="unlinked-queue", region_name=region)
    sqs = get_sqs_client(region_name=region)
    tenant_id = "telco_default"

    unlinked_session = "sess_anonymous_never_logs_in"
    event = {
        "tenant_id": tenant_id,
        "event_type": "view",
        "customer_id": None,
        "session_id": unlinked_session,
        "product_id": "prod_broadband",
    }
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(event))

    process_tracking_batch(
        queue_url=queue_url,
        sqs_client=sqs,
        storage=storage,
        max_messages=10,
        wait_time_seconds=0,
    )

    interactions_path = f"data/processed/{tenant_id}/interactions.csv"
    df = pd.read_csv(io.BytesIO(storage.read_file(interactions_path)))
    assert len(df) == 1
    # Remains session-only row
    assert df.loc[0, "customer_id"] == unlinked_session
