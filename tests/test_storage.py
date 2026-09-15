"""Unit tests for the StorageBackend abstraction, LocalStorage, and S3Storage."""

from __future__ import annotations

import os
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from src.storage import get_storage_backend
from src.storage.base_storage import StorageBackend
from src.storage.local_storage import LocalStorage
from src.storage.s3_storage import S3Storage


@pytest.fixture(autouse=True)
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    old_env = os.environ.copy()
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    os.environ.clear()
    os.environ.update(old_env)


# ===========================================================================
# LocalStorage Tests
# ===========================================================================


class TestLocalStorage:
    def test_write_and_read_file(self, tmp_path: Path):
        storage = LocalStorage(base_dir=tmp_path)
        test_path = "data/processed/telco_default/interactions.csv"
        content = b"customer_id,product_id\nc1,p1\n"

        storage.write_file(test_path, content)
        assert storage.exists(test_path) is True
        assert storage.read_file(test_path) == content

    def test_read_non_existent_file_raises(self, tmp_path: Path):
        storage = LocalStorage(base_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.read_file("models/non_existent.joblib")

    def test_exists_non_existent_or_dir(self, tmp_path: Path):
        storage = LocalStorage(base_dir=tmp_path)
        assert storage.exists("does/not/exist.txt") is False

        # Directory should not be treated as a file existence
        (tmp_path / "somedir").mkdir()
        assert storage.exists("somedir") is False

    def test_list_files(self, tmp_path: Path):
        storage = LocalStorage(base_dir=tmp_path)
        storage.write_file("data/processed/tenant_a/interactions.csv", b"a")
        storage.write_file("data/processed/tenant_a/customers.csv", b"a")
        storage.write_file("data/processed/tenant_b/interactions.csv", b"b")
        storage.write_file("models/tenant_a/model.joblib", b"m")

        # List all under data/processed
        data_files = storage.list_files("data/processed")
        assert data_files == [
            "data/processed/tenant_a/customers.csv",
            "data/processed/tenant_a/interactions.csv",
            "data/processed/tenant_b/interactions.csv",
        ]

        # List specific tenant prefix
        tenant_a_files = storage.list_files("data/processed/tenant_a")
        assert tenant_a_files == [
            "data/processed/tenant_a/customers.csv",
            "data/processed/tenant_a/interactions.csv",
        ]

        # List non-existent prefix
        assert storage.list_files("non_existent_prefix") == []


# ===========================================================================
# S3Storage Tests
# ===========================================================================


class TestS3Storage:
    @mock_aws
    def test_write_and_read_file(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(bucket_name="test-bucket", s3_client=client)
        test_path = "data/processed/telco_default/interactions.csv"
        content = b"customer_id,product_id\nc1,p1\n"

        storage.write_file(test_path, content)
        assert storage.exists(test_path) is True
        assert storage.read_file(test_path) == content

    @mock_aws
    def test_read_non_existent_file_raises(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(bucket_name="test-bucket", s3_client=client)
        with pytest.raises(FileNotFoundError):
            storage.read_file("models/non_existent.joblib")

    @mock_aws
    def test_exists_returns_false_for_missing(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(bucket_name="test-bucket", s3_client=client)
        assert storage.exists("models/missing.joblib") is False

    @mock_aws
    def test_s3_uri_compatibility(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(bucket_name="test-bucket", s3_client=client)
        s3_uri = "s3://test-bucket/models/tenant_id/final_model.joblib"
        content = b"model-binary-data"

        storage.write_file(s3_uri, content)
        assert storage.exists(s3_uri) is True
        # Also accessible via relative key
        assert storage.exists("models/tenant_id/final_model.joblib") is True
        assert storage.read_file(s3_uri) == content
        assert storage.read_file("models/tenant_id/final_model.joblib") == content

    @mock_aws
    def test_prefix_mapping(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(
            bucket_name="test-bucket",
            prefix="environments/production",
            s3_client=client,
        )
        path = "data/processed/tenant_x/interactions.csv"
        content = b"data"

        storage.write_file(path, content)
        assert storage.exists(path) is True
        assert storage.read_file(path) == content

        # Verify underlying key in bucket has prefix
        direct_obj = client.get_object(
            Bucket="test-bucket",
            Key="environments/production/data/processed/tenant_x/interactions.csv",
        )
        assert direct_obj["Body"].read() == content

        # Verify list_files strips root prefix to return logical paths
        files = storage.list_files("data/processed")
        assert files == ["data/processed/tenant_x/interactions.csv"]

    @mock_aws
    def test_list_files(self):
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")

        storage = S3Storage(bucket_name="test-bucket", s3_client=client)
        storage.write_file("data/processed/t1/customers.csv", b"1")
        storage.write_file("data/processed/t1/interactions.csv", b"2")
        storage.write_file("data/processed/t2/interactions.csv", b"3")
        storage.write_file("models/t1/model.joblib", b"4")

        assert storage.list_files("data/processed") == [
            "data/processed/t1/customers.csv",
            "data/processed/t1/interactions.csv",
            "data/processed/t2/interactions.csv",
        ]
        assert storage.list_files("data/processed/t1") == [
            "data/processed/t1/customers.csv",
            "data/processed/t1/interactions.csv",
        ]
        assert storage.list_files("non_existent") == []


# ===========================================================================
# Factory Function Tests
# ===========================================================================


class TestStorageFactory:
    def test_get_storage_backend_local_default(self):
        backend = get_storage_backend({"storage": {"backend": "local"}})
        assert isinstance(backend, LocalStorage)

    def test_get_storage_backend_s3(self):
        backend = get_storage_backend({
            "storage": {
                "backend": "s3",
                "s3_bucket": "my-test-bucket",
                "s3_prefix": "app",
            }
        })
        assert isinstance(backend, S3Storage)
        assert backend.bucket_name == "my-test-bucket"
        assert backend.prefix == "app"

    def test_get_storage_backend_s3_missing_bucket(self):
        with pytest.raises(ValueError, match="storage.s3_bucket"):
            get_storage_backend({"storage": {"backend": "s3"}})

    def test_get_storage_backend_unknown(self):
        with pytest.raises(ValueError, match="Unsupported storage backend 'gcs'"):
            get_storage_backend({"storage": {"backend": "gcs"}})

    def test_get_storage_backend_default_config(self):
        # When called without arguments, reads config.yaml which defaults to local
        backend = get_storage_backend()
        assert isinstance(backend, LocalStorage)


# ===========================================================================
# Backend Parity (Contract) Tests
# ===========================================================================


class TestBackendParity:
    """Ensure LocalStorage and S3Storage exhibit identical contract behavior."""

    @pytest.fixture
    def backends(self, tmp_path: Path):
        with mock_aws():
            s3_client = boto3.client("s3", region_name="us-east-1")
            s3_client.create_bucket(Bucket="parity-bucket")
            local = LocalStorage(base_dir=tmp_path)
            s3 = S3Storage(bucket_name="parity-bucket", s3_client=s3_client)
            yield [("local", local), ("s3", s3)]

    def test_contract_parity(self, backends: list[tuple[str, StorageBackend]]):
        for name, storage in backends:
            # 1. Non-existent file raises FileNotFoundError
            with pytest.raises(FileNotFoundError):
                storage.read_file("test/file.txt")

            # 2. Exists returns False
            assert storage.exists("test/file.txt") is False

            # 3. Write and verify exists & read
            storage.write_file("data/processed/tenant_1/file1.csv", b"content1")
            storage.write_file("data/processed/tenant_1/file2.csv", b"content2")
            storage.write_file("data/processed/tenant_2/file3.csv", b"content3")

            assert storage.exists("data/processed/tenant_1/file1.csv") is True
            assert storage.read_file("data/processed/tenant_1/file1.csv") == b"content1"

            # 4. List files with prefix
            assert storage.list_files("data/processed/tenant_1") == [
                "data/processed/tenant_1/file1.csv",
                "data/processed/tenant_1/file2.csv",
            ]
            assert storage.list_files("data/processed") == [
                "data/processed/tenant_1/file1.csv",
                "data/processed/tenant_1/file2.csv",
                "data/processed/tenant_2/file3.csv",
            ]
            assert storage.list_files("unknown") == []
