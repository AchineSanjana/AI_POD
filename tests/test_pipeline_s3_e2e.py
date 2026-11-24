"""End-to-end test comparing telco pipeline outputs between local and S3 backends."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from scripts import run_pipeline
from src.api.recommendations import clear_model_cache, get_recommendations
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage
from src.utils import config as config_module
from src.utils.persistence import load_model


@pytest.fixture
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    old_env = os.environ.copy()
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    yield
    os.environ.clear()
    os.environ.update(old_env)


@mock_aws
def test_pipeline_s3_identical_to_local(monkeypatch, aws_credentials):
    """Run full pipeline with S3 backend and verify outputs match local backend."""
    local_storage = LocalStorage()

    # 1. Ensure local pipeline has run for telco_default as reference
    if not local_storage.exists("models/telco_default/final_model.joblib"):
        monkeypatch.setattr(
            sys, "argv", ["run_pipeline.py", "--tenant_id", "telco_default"]
        )
        run_pipeline.main()
    customers_local = pd.read_csv(
        io.BytesIO(local_storage.read_file("data/processed/telco_default/customers.csv"))
    )
    products_local = pd.read_csv(
        io.BytesIO(local_storage.read_file("data/processed/telco_default/products.csv"))
    )
    interactions_local = pd.read_csv(
        io.BytesIO(local_storage.read_file("data/processed/telco_default/interactions.csv"))
    )
    model_local = load_model(
        "models/telco_default/final_model.joblib", storage=local_storage
    )

    # 2. Setup mocked S3 bucket
    bucket_name = "telco-pipeline-e2e-bucket"
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket=bucket_name)

    # Seed raw dataset into S3 to test end-to-end cloud reading
    raw_path = Path("data/raw/telco_customer_churn.csv")
    if raw_path.exists():
        s3_client.put_object(
            Bucket=bucket_name,
            Key="data/raw/telco_customer_churn.csv",
            Body=raw_path.read_bytes(),
        )

    # 3. Configure storage.backend: "s3"
    orig_load_config = config_module.load_config

    def mock_s3_config():
        cfg = orig_load_config()
        cfg["storage"] = {
            "backend": "s3",
            "s3_bucket": bucket_name,
            "s3_prefix": "",
        }
        return cfg

    monkeypatch.setattr(config_module, "load_config", mock_s3_config)
    monkeypatch.setattr("scripts.run_pipeline.load_config", mock_s3_config)
    monkeypatch.setattr("src.api.recommendations.load_config", mock_s3_config)
    monkeypatch.setattr("src.api.ui.load_config", mock_s3_config)

    # 4. Run pipeline targeting S3 backend
    clear_model_cache()
    monkeypatch.setattr(
        sys, "argv", ["run_pipeline.py", "--tenant_id", "telco_default"]
    )
    run_pipeline.main()

    # 5. Verify files exist in S3
    s3_storage = S3Storage(bucket_name=bucket_name, s3_client=s3_client)
    assert s3_storage.exists("data/processed/telco_default/customers.csv")
    assert s3_storage.exists("data/processed/telco_default/products.csv")
    assert s3_storage.exists("data/processed/telco_default/interactions.csv")
    assert s3_storage.exists("models/telco_default/final_model.joblib")

    # 6. Read S3 outputs and compare against local tables
    customers_s3 = pd.read_csv(
        io.BytesIO(s3_storage.read_file("data/processed/telco_default/customers.csv"))
    )
    products_s3 = pd.read_csv(
        io.BytesIO(s3_storage.read_file("data/processed/telco_default/products.csv"))
    )
    interactions_s3 = pd.read_csv(
        io.BytesIO(s3_storage.read_file("data/processed/telco_default/interactions.csv"))
    )

    pd.testing.assert_frame_equal(customers_s3, customers_local)
    pd.testing.assert_frame_equal(products_s3, products_local)
    pd.testing.assert_frame_equal(interactions_s3, interactions_local)

    # 7. Compare trained model predictions
    model_s3 = load_model(
        "models/telco_default/final_model.joblib", storage=s3_storage
    )
    assert type(model_s3) is type(model_local)

    test_customer_id = customers_s3["customer_id"].iloc[0]
    local_recs = model_local.recommend(test_customer_id, top_k=5)
    s3_recs = model_s3.recommend(test_customer_id, top_k=5)
    assert s3_recs == local_recs

    # 8. Test API recommendations endpoint with S3 backend
    clear_model_cache()
    api_response = get_recommendations(
        customer_id=test_customer_id,
        top_n=5,
        tenant_id="telco_default",
    )
    assert api_response["tenant_id"] == "telco_default"
    assert len(api_response["recommendations"]) == 5
    api_rec_ids = [r["product_id"] for r in api_response["recommendations"]]
    assert api_rec_ids == s3_recs
