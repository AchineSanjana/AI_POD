"""Tests for Shopify OAuth Connect Store flow, secure token storage, and catalog sync.

Verifies:
- Shop domain normalization and validation.
- OAuth authorization URL and CSRF state generation.
- OAuth callback code exchange and secure per-tenant token storage (Step 15.2 pattern).
- Pulling products from Shopify Admin API and populating products table in S3 in the same shape as Step 20.1.
- Priority: Shopify platform connection takes priority over catalog_feed_url.
- Public key restrictions (OAuth endpoints forbidden for public keys, allowed for private keys).
"""

from __future__ import annotations

import io
import json
import os
from unittest.mock import MagicMock, patch
import urllib.request
import boto3
from fastapi.testclient import TestClient
import pandas as pd
import pytest
from moto import mock_aws

from src.api.app import app
from src.catalog.feed_sync import sync_tenant_catalog
from src.core.schema import ProductSchema
from src.integrations.shopify.client import (
    build_authorization_url,
    normalize_shop_domain,
    parse_shopify_products,
    verify_shopify_hmac,
)
from src.integrations.shopify.storage import (
    delete_shopify_connection,
    get_shopify_connection,
    list_shopify_connections,
    save_shopify_connection,
)
from src.storage.s3_storage import S3Storage


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def aws_env(monkeypatch):
    """Set standard AWS environment variables for moto tests."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")


def test_normalize_shop_domain():
    """Verify shop domain normalization to *.myshopify.com."""
    assert normalize_shop_domain("my-store") == "my-store.myshopify.com"
    assert normalize_shop_domain("my-store.myshopify.com") == "my-store.myshopify.com"
    assert normalize_shop_domain("https://my-store.myshopify.com/") == "my-store.myshopify.com"
    assert normalize_shop_domain("HTTP://DEMO-SHOP.MYSHOPIFY.COM") == "demo-shop.myshopify.com"

    with pytest.raises(ValueError):
        normalize_shop_domain("")

    with pytest.raises(ValueError):
        normalize_shop_domain("bad domain with spaces")


def test_verify_shopify_hmac():
    """Verify HMAC signature calculation against Shopify query parameters."""
    secret = "hush"
    # Generated using standard HMAC-SHA256 of code=0907a61c0c8d55e99db179b68161bc00&shop=some-shop.myshopify.com&state=0.6784241404105439&timestamp=1337178173
    # key: hush
    import hashlib
    import hmac

    params = {
        "code": "0907a61c0c8d55e99db179b68161bc00",
        "shop": "some-shop.myshopify.com",
        "state": "0.6784241404105439",
        "timestamp": "1337178173",
    }
    sorted_pairs = sorted([(k, str(v)) for k, v in params.items()])
    msg = "&".join(f"{k}={v}" for k, v in sorted_pairs)
    sig = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hmac"] = sig

    assert verify_shopify_hmac(params, secret) is True
    # Tampered params
    params["code"] = "tampered"
    assert verify_shopify_hmac(params, secret) is False


def test_parse_shopify_products():
    """Verify raw Shopify Admin API product payload converts into canonical schema rows."""
    raw_shopify_data = [
        {
            "id": 8011223344,
            "title": "Aerodynamic Wireless Earbuds",
            "product_type": "Audio > In-Ear",
            "variants": [
                {
                    "id": 991122,
                    "title": "Default Title",
                    "price": "149.99",
                    "sku": "EARBUD-01",
                }
            ],
        },
        {
            "id": 8011223355,
            "title": "Waterproof Carrying Case",
            "product_type": "Accessories",
            "variants": [
                {
                    "id": 991133,
                    "price": "29.50",
                }
            ],
        },
    ]

    rows = parse_shopify_products(raw_shopify_data)
    assert len(rows) == 2

    assert rows[0]["product_id"] == "8011223344"
    assert rows[0]["product_name"] == "Aerodynamic Wireless Earbuds"
    assert rows[0]["price"] == 149.99
    assert rows[0]["category"] == "Audio > In-Ear"

    assert rows[1]["product_id"] == "8011223355"
    assert rows[1]["product_name"] == "Waterproof Carrying Case"
    assert rows[1]["price"] == 29.50
    assert rows[1]["category"] == "Accessories"


@mock_aws
def test_shopify_storage_secure_ssm(aws_env, monkeypatch):
    """Verify storing, retrieving, listing, and deleting Shopify credentials via SSM Parameter Store."""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    tenant_id = "test_merchant"
    record = save_shopify_connection(
        tenant_id=tenant_id,
        shop="merchant-store.myshopify.com",
        access_token="shpat_test_token_12345",
        scopes="read_products",
    )
    assert record["tenant_id"] == tenant_id
    assert record["shop"] == "merchant-store.myshopify.com"

    # Retrieve
    loaded = get_shopify_connection(tenant_id)
    assert loaded is not None
    assert loaded["access_token"] == "shpat_test_token_12345"

    # List
    all_conns = list_shopify_connections()
    assert tenant_id in all_conns

    # Delete
    deleted = delete_shopify_connection(tenant_id)
    assert deleted is True
    assert get_shopify_connection(tenant_id) is None


def test_shopify_oauth_authorize_endpoint(client: TestClient):
    """Verify GET /v1/integrations/shopify/authorize generates authorization URL and state."""
    # 1. Must reject public key with 403
    pub_resp = client.get(
        "/v1/integrations/shopify/authorize",
        params={"shop": "demo-app.myshopify.com"},
        headers={"X-API-Key": "pk-telco-xxxx"},
    )
    assert pub_resp.status_code == 403

    # 2. Must succeed with private key
    priv_resp = client.get(
        "/v1/integrations/shopify/authorize",
        params={"shop": "demo-app.myshopify.com"},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert priv_resp.status_code == 200
    data = priv_resp.json()
    assert data["status"] == "pending_authorization"
    assert data["tenant_id"] == "telco_default"
    assert data["shop"] == "demo-app.myshopify.com"
    assert "authorization_url" in data
    assert "state" in data
    assert "oauth/authorize" in data["authorization_url"]


@mock_aws
def test_shopify_oauth_callback_flow_and_catalog_pull(client: TestClient, monkeypatch, aws_env):
    """Test full OAuth callback: exchange code, store access token, and populate S3 products table."""
    region = "us-east-1"
    bucket_name = "test-shopify-callback-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_REGION", region)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    tenant_id = "telco_default"

    # 1. Start authorize flow to obtain valid state
    auth_resp = client.get(
        "/v1/integrations/shopify/authorize",
        params={"shop": "quick-start.myshopify.com"},
        headers={"X-API-Key": "sk-telco-xxxx"},
    )
    assert auth_resp.status_code == 200
    state = auth_resp.json()["state"]

    # 2. Mock Shopify token exchange and product fetch
    mock_token_response = {"access_token": "shpat_live_secret_token_abc", "scope": "read_products"}
    mock_products_response = [
        {
            "id": 9001,
            "title": "Shopify Premium Plan Service",
            "product_type": "Subscription",
            "variants": [{"id": 1, "price": "79.00"}],
        },
        {
            "id": 9002,
            "title": "Hardware Terminal",
            "product_type": "Hardware",
            "variants": [{"id": 2, "price": "299.00"}],
        },
    ]

    with patch("src.integrations.shopify.api.exchange_code_for_token", return_value=mock_token_response), \
         patch("src.integrations.shopify.client.fetch_shopify_products", return_value=mock_products_response):

        # 3. Simulate Shopify redirecting to callback
        callback_resp = client.get(
            "/v1/integrations/shopify/callback",
            params={
                "shop": "quick-start.myshopify.com",
                "code": "auth_code_from_shopify_123",
                "state": state,
            },
        )
        assert callback_resp.status_code == 200
        cb_data = callback_resp.json()
        assert cb_data["status"] == "connected"
        assert cb_data["tenant_id"] == tenant_id
        assert cb_data["shop"] == "quick-start.myshopify.com"

        # 4. Verify token was securely stored per tenant
        saved_conn = get_shopify_connection(tenant_id)
        assert saved_conn is not None
        assert saved_conn["access_token"] == "shpat_live_secret_token_abc"
        assert saved_conn["shop"] == "quick-start.myshopify.com"

        # 5. Confirm S3 products table was populated in the same shape as feed-based path
        prod_path = f"data/processed/{tenant_id}/products.csv"
        assert storage.exists(prod_path)

        csv_bytes = storage.read_file(prod_path)
        products_df = pd.read_csv(io.BytesIO(csv_bytes))

        assert len(products_df) == 2
        assert "product_id" in products_df.columns
        assert "product_name" in products_df.columns
        assert "price" in products_df.columns
        assert "category" in products_df.columns

        lookup = products_df.set_index("product_id")
        assert lookup.loc[9001]["product_name"] == "Shopify Premium Plan Service"
        assert lookup.loc[9001]["price"] == 79.00
        assert lookup.loc[9001]["category"] == "Subscription"

        assert lookup.loc[9002]["product_name"] == "Hardware Terminal"
        assert lookup.loc[9002]["price"] == 299.00

        # Validate against ProductSchema
        schema = ProductSchema()
        schema.validate(products_df)


@mock_aws
def test_platform_connection_priority_over_feed_url(monkeypatch, aws_env, tmp_path):
    """When a tenant has both a feed URL and a Shopify connection, Shopify connection takes priority."""
    region = "us-east-1"
    bucket_name = "test-priority-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_REGION", region)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    tenant_id = "priority_tenant"

    # 1. Create a fake feed with Product FEED_1
    feed_file = tmp_path / "feed.json"
    feed_file.write_text(
        json.dumps([{"product_id": "FEED_PROD_1", "product_name": "Feed Item", "price": 10.0}]),
        encoding="utf-8",
    )

    # 2. Configure tenant in config with catalog_feed_url
    cfg = {
        "tenants": {
            tenant_id: {
                "catalog_feed_url": f"file://{feed_file.resolve()}",
            }
        },
        "storage": {"backend": "s3", "s3_bucket": bucket_name, "region": region},
    }

    # 3. Store an active Shopify connection for this tenant
    save_shopify_connection(
        tenant_id=tenant_id,
        shop="priority-store.myshopify.com",
        access_token="shpat_priority_token",
        config=cfg,
    )

    # 4. Mock Shopify API products returning SHOPIFY_PROD_1
    mock_shopify_products = [
        {
            "id": "SHOPIFY_PROD_1",
            "title": "Shopify Priority Item",
            "product_type": "Top Priority",
            "variants": [{"price": "55.00"}],
        }
    ]

    with patch("src.integrations.shopify.client.fetch_shopify_products", return_value=mock_shopify_products):
        # 5. Run sync_tenant_catalog
        res = sync_tenant_catalog(tenant_id=tenant_id, storage=storage, config=cfg)

        # Confirm priority source is shopify
        assert res["status"] == "success"
        assert res["source"] == "shopify"
        assert res["shop"] == "priority-store.myshopify.com"

        # Check S3 file contents: must contain SHOPIFY_PROD_1, not FEED_PROD_1
        csv_bytes = storage.read_file(f"data/processed/{tenant_id}/products.csv")
        df = pd.read_csv(io.BytesIO(csv_bytes))
        assert len(df) == 1
        assert df.loc[0, "product_id"] == "SHOPIFY_PROD_1"
        assert df.loc[0, "product_name"] == "Shopify Priority Item"
        assert df.loc[0, "price"] == 55.00
