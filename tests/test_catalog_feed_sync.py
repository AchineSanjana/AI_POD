"""Tests for catalog feed fetching, Google Shopping XML/JSON parsing, and S3 upsert syncing.

Verifies:
- Parsing Google Shopping RSS 2.0 and Atom XML feeds with 'g:' namespaces.
- Parsing JSON product feeds (list or object formats).
- Price extraction and currency symbol cleaning.
- Upsert behavior in S3:
  - New products from the feed are added.
  - Existing products mentioned in the feed are updated.
  - Existing products not mentioned in the feed are preserved untouched.
  - No duplicate product_ids are created.
- Shared BackgroundScheduler registration and execution.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import boto3
import pandas as pd
import pytest
from moto import mock_aws

from src.catalog.feed_parser import _clean_price, parse_catalog_feed
from src.catalog.feed_sync import (
    sync_all_tenant_catalogs,
    sync_tenant_catalog,
    upsert_tenant_products,
)
from src.core.schema import ProductSchema
from src.scheduler.scheduler import BackgroundScheduler, ScheduledJob
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


def test_clean_price():
    """Verify price string parsing and currency normalization."""
    assert _clean_price("19.99 USD") == 19.99
    assert _clean_price("$49.50") == 49.50
    assert _clean_price("£120.00") == 120.00
    assert _clean_price("1,299.95") == 1299.95
    assert _clean_price(85.5) == 85.5
    assert _clean_price(None) is None
    assert _clean_price("free") is None


def test_parse_google_shopping_rss_xml():
    """Verify parsing standard Google Shopping RSS 2.0 XML product feed."""
    xml_content = """<?xml version="1.0"?>
    <rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">
      <channel>
        <title>Demo Merchant Store</title>
        <item>
          <g:id>SKU_HEADPHONE_01</g:id>
          <g:title>Noise-Canceling Headphones</g:title>
          <g:price>199.99 USD</g:price>
          <g:product_type>Electronics &gt; Audio</g:product_type>
        </item>
        <item>
          <g:id>SKU_CASE_02</g:id>
          <g:title>Phone Protective Case</g:title>
          <g:price>24.50 USD</g:price>
          <g:google_product_category>Accessories &gt; Cases</g:google_product_category>
        </item>
      </channel>
    </rss>
    """
    products = parse_catalog_feed(xml_content, content_type="text/xml")
    assert len(products) == 2

    p1 = products[0]
    assert p1["product_id"] == "SKU_HEADPHONE_01"
    assert p1["product_name"] == "Noise-Canceling Headphones"
    assert p1["price"] == 199.99
    assert p1["category"] == "Electronics > Audio"

    p2 = products[1]
    assert p2["product_id"] == "SKU_CASE_02"
    assert p2["product_name"] == "Phone Protective Case"
    assert p2["price"] == 24.50
    assert p2["category"] == "Accessories > Cases"


def test_parse_atom_xml_feed():
    """Verify parsing Atom XML product feed."""
    atom_content = """<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:g="http://base.google.com/ns/1.0">
      <title>Atom Store</title>
      <entry>
        <g:id>SKU_ATOM_01</g:id>
        <g:title>Trail Running Shoes</g:title>
        <g:price>$110.00</g:price>
        <g:product_type>Footwear</g:product_type>
      </entry>
    </feed>
    """
    products = parse_catalog_feed(atom_content, content_type="application/atom+xml")
    assert len(products) == 1
    assert products[0]["product_id"] == "SKU_ATOM_01"
    assert products[0]["product_name"] == "Trail Running Shoes"
    assert products[0]["price"] == 110.00
    assert products[0]["category"] == "Footwear"


def test_parse_json_product_feed():
    """Verify parsing JSON product feeds in both list and dict formats."""
    # Format 1: dict with 'products' list
    json_obj = {
        "products": [
            {
                "id": "PROD_JSON_01",
                "title": "Smart Watch",
                "price": "249.99",
                "category": "Wearables",
            }
        ]
    }
    res1 = parse_catalog_feed(json.dumps(json_obj), content_type="application/json")
    assert len(res1) == 1
    assert res1[0]["product_id"] == "PROD_JSON_01"
    assert res1[0]["product_name"] == "Smart Watch"
    assert res1[0]["price"] == 249.99
    assert res1[0]["category"] == "Wearables"

    # Format 2: top-level list
    json_list = [
        {
            "product_id": "PROD_JSON_02",
            "product_name": "USB-C Cable",
            "price": 12.99,
            "category": "Cables",
        }
    ]
    res2 = parse_catalog_feed(json.dumps(json_list), content_type="application/json")
    assert len(res2) == 1
    assert res2[0]["product_id"] == "PROD_JSON_02"
    assert res2[0]["price"] == 12.99


@mock_aws
def test_upsert_tenant_products_behavior(aws_env, tmp_path):
    """Confirm correct upsert behavior: new products added, existing updated, nothing duplicated."""
    region = "us-east-1"
    bucket_name = "test-catalog-upsert-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    tenant_id = "test_ecom_tenant"
    products_path = f"data/processed/{tenant_id}/products.csv"

    # 1. Establish initial products table in S3
    initial_df = pd.DataFrame(
        [
            {
                "product_id": "PROD_EXISTING_1",
                "product_name": "Original Name 1",
                "price": 10.0,
                "category": "Old Category",
            },
            {
                "product_id": "PROD_UNTOUCHED_2",
                "product_name": "Untouched Product",
                "price": 50.0,
                "category": "Stable Category",
            },
        ]
    )
    storage.write_file(products_path, initial_df.to_csv(index=False).encode("utf-8"))

    # 2. Prepare feed rows:
    # - PROD_EXISTING_1 is updated with new title, price, and category
    # - PROD_NEW_3 is a brand new product
    # - PROD_UNTOUCHED_2 is absent from the feed (should be preserved in 'upsert' mode)
    feed_rows = [
        {
            "product_id": "PROD_EXISTING_1",
            "product_name": "Updated Name 1",
            "price": 19.99,
            "category": "Upgraded Category",
        },
        {
            "product_id": "PROD_NEW_3",
            "product_name": "Brand New Item",
            "price": 89.95,
            "category": "New Arrivals",
        },
    ]

    metrics = upsert_tenant_products(
        tenant_id=tenant_id,
        feed_rows=feed_rows,
        storage=storage,
        mode="upsert",
    )

    assert metrics["fetched"] == 2
    assert metrics["updated"] == 1
    assert metrics["added"] == 1
    assert metrics["total"] == 3

    # 3. Read back and verify final table contents
    raw_csv = storage.read_file(products_path)
    final_df = pd.read_csv(io.BytesIO(raw_csv))

    assert len(final_df) == 3
    # Check that nothing is duplicated
    assert len(final_df["product_id"].unique()) == 3

    lookup = final_df.set_index("product_id")

    # Verify PROD_EXISTING_1 was updated
    p1 = lookup.loc["PROD_EXISTING_1"]
    assert p1["product_name"] == "Updated Name 1"
    assert p1["price"] == 19.99
    assert p1["category"] == "Upgraded Category"

    # Verify PROD_UNTOUCHED_2 was preserved untouched
    p2 = lookup.loc["PROD_UNTOUCHED_2"]
    assert p2["product_name"] == "Untouched Product"
    assert p2["price"] == 50.0
    assert p2["category"] == "Stable Category"

    # Verify PROD_NEW_3 was added
    p3 = lookup.loc["PROD_NEW_3"]
    assert p3["product_name"] == "Brand New Item"
    assert p3["price"] == 89.95
    assert p3["category"] == "New Arrivals"

    # Verify compliance with ProductSchema
    schema = ProductSchema()
    schema.validate(final_df)


@mock_aws
def test_sync_tenant_catalog_end_to_end_from_xml_feed(aws_env, tmp_path, monkeypatch):
    """End-to-end sync using a fake XML feed file and S3 storage."""
    region = "us-east-1"
    bucket_name = "test-e2e-catalog-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_REGION", region)

    storage = S3Storage(bucket_name=bucket_name, region_name=region)
    tenant_id = "feed_tenant"

    # 1. Write initial product table
    init_df = pd.DataFrame(
        [{"product_id": "SKU_BASE", "product_name": "Base Product", "price": 5.0, "category": "Base"}]
    )
    storage.write_file(
        f"data/processed/{tenant_id}/products.csv",
        init_df.to_csv(index=False).encode("utf-8"),
    )

    # 2. Write a local fake Google Shopping XML feed file
    fake_feed = tmp_path / "google_shopping_feed.xml"
    fake_feed.write_text(
        """<?xml version="1.0"?>
        <rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">
          <channel>
            <item>
              <g:id>SKU_BASE</g:id>
              <g:title>Base Product Deluxe</g:title>
              <g:price>7.50 USD</g:price>
              <g:product_type>Base &gt; Deluxe</g:product_type>
            </item>
            <item>
              <g:id>SKU_PREMIUM</g:id>
              <g:title>Premium Bundle</g:title>
              <g:price>99.00 USD</g:price>
              <g:product_type>Bundles</g:product_type>
            </item>
          </channel>
        </rss>
        """,
        encoding="utf-8",
    )

    feed_url = f"file://{fake_feed.resolve()}"

    # 3. Execute sync_tenant_catalog
    res = sync_tenant_catalog(
        tenant_id=tenant_id,
        feed_url=feed_url,
        storage=storage,
        mode="upsert",
    )
    assert res["status"] == "success"
    assert res["fetched"] == 2
    assert res["updated"] == 1
    assert res["added"] == 1
    assert res["total"] == 2

    # 4. Verify S3 file
    products_csv = storage.read_file(f"data/processed/{tenant_id}/products.csv")
    df = pd.read_csv(io.BytesIO(products_csv))
    assert len(df) == 2
    lookup = df.set_index("product_id")
    assert lookup.loc["SKU_BASE"]["product_name"] == "Base Product Deluxe"
    assert lookup.loc["SKU_BASE"]["price"] == 7.50
    assert lookup.loc["SKU_PREMIUM"]["product_name"] == "Premium Bundle"


@mock_aws
def test_sync_all_tenant_catalogs_with_configured_url(aws_env, tmp_path):
    """Confirm sync_all_tenant_catalogs scans tenants and syncs those with catalog_feed_url."""
    region = "us-east-1"
    bucket_name = "test-all-catalogs-bucket"
    s3 = boto3.client("s3", region_name=region)
    s3.create_bucket(Bucket=bucket_name)
    storage = S3Storage(bucket_name=bucket_name, region_name=region)

    feed_file = tmp_path / "feed.json"
    feed_file.write_text(
        json.dumps(
            [
                {
                    "product_id": "SYNC_PROD_1",
                    "product_name": "Synced Item",
                    "price": 25.0,
                    "category": "General",
                }
            ]
        ),
        encoding="utf-8",
    )

    test_config = {
        "tenants": {
            "tenant_with_feed": {
                "catalog_feed_url": f"file://{feed_file.resolve()}",
            },
            "tenant_without_feed": {
                "catalog_feed_url": None,
            },
        }
    }

    results = sync_all_tenant_catalogs(config=test_config, storage=storage)
    assert len(results) == 1
    assert results[0]["tenant_id"] == "tenant_with_feed"
    assert results[0]["status"] == "success"
    assert results[0]["total"] == 1

    assert storage.exists("data/processed/tenant_with_feed/products.csv")


def test_background_scheduler_lifecycle():
    """Verify shared BackgroundScheduler registration, immediate execution, and thread lifecycle."""
    executed = []

    def mock_job(value: int):
        executed.append(value)

    scheduler = BackgroundScheduler(check_interval_seconds=0.1)
    job = scheduler.register_job(
        name="test_sync_job",
        fn=mock_job,
        interval_seconds=3600.0,
        kwargs={"value": 42},
        run_immediately=False,
    )
    assert job.name == "test_sync_job"
    assert not scheduler.is_alive()

    # Test run_job_now
    scheduler.run_job_now("test_sync_job")
    assert executed == [42]
    assert job.run_count == 1
    assert job.last_status == "success"

    # Test lifecycle
    scheduler.start()
    assert scheduler.is_alive()

    scheduler.stop(timeout=1.0)
    assert not scheduler.is_alive()
