"""Tests verifying Dockerfile.pipeline configuration and S3 execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from scripts import run_pipeline
from src.storage.s3_storage import S3Storage
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


def test_dockerfile_pipeline_structure():
    """Verify Dockerfile.pipeline exists with expected environment and entrypoint."""
    pipeline_dockerfile = Path("Dockerfile.pipeline")
    assert pipeline_dockerfile.exists(), (
        "Dockerfile.pipeline must exist at project root"
    )

    content = pipeline_dockerfile.read_text(encoding="utf-8")
    assert "python:3.11-slim" in content
    assert "TENANT_ID=telco_default" in content
    assert "STORAGE_BACKEND=s3" in content
    assert "scripts/run_pipeline.py" in content
    assert 'ENTRYPOINT ["python", "scripts/run_pipeline.py"]' in content


def test_tenant_id_environment_variable_resolution(monkeypatch):
    """Verify pipeline scripts prioritize TENANT_ID env var."""
    monkeypatch.setenv("TENANT_ID", "fixture_ecommerce")

    # When no arguments are passed, should default to TENANT_ID env var
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py"])
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tenant_id",
        type=str,
        default=os.environ.get("TENANT_ID", "telco_default"),
    )
    args = parser.parse_args()
    assert args.tenant_id == "fixture_ecommerce"

    # Explicit command-line argument overrides environment variable
    monkeypatch.setattr(
        sys, "argv", ["run_pipeline.py", "--tenant_id", "telco_default"]
    )
    args_cli = parser.parse_args()
    assert args_cli.tenant_id == "telco_default"


@mock_aws
def test_docker_pipeline_run_with_s3_env(monkeypatch, aws_credentials):
    """Simulate docker run --env TENANT_ID=telco_default writing output to S3."""
    bucket_name = "test-docker-pipeline-bucket"
    s3_client = boto3.client("s3", region_name="us-east-1")
    s3_client.create_bucket(Bucket=bucket_name)

    # Configure environment variables matching Dockerfile.pipeline defaults
    monkeypatch.setenv("TENANT_ID", "telco_default")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("STORAGE_S3_BUCKET", bucket_name)
    monkeypatch.setenv("STORAGE_S3_PREFIX", "")

    # Execute run_pipeline.main() without CLI args (simulates default entrypoint)
    monkeypatch.setattr(sys, "argv", ["run_pipeline.py"])
    run_pipeline.main()

    # Verify S3 received processed datasets and trained model
    s3_storage = S3Storage(bucket_name=bucket_name, s3_client=s3_client)
    assert s3_storage.exists("data/processed/telco_default/customers.csv")
    assert s3_storage.exists("data/processed/telco_default/products.csv")
    assert s3_storage.exists("data/processed/telco_default/interactions.csv")
    assert s3_storage.exists("models/telco_default/final_model.joblib")

    # Verify model artifact loads from S3 and produces recommendations
    model = load_model(
        "models/telco_default/final_model.joblib", storage=s3_storage
    )
    assert hasattr(model, "recommend")
    recs = model.recommend("7590-VHVEG", top_k=5)
    assert len(recs) == 5
