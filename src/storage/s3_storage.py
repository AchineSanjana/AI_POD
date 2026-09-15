"""AWS S3 implementation of the StorageBackend using boto3."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.storage.base_storage import StorageBackend


class S3Storage(StorageBackend):
    """Storage backend that interacts with AWS S3 via boto3.

    Paths are mapped to S3 object keys within a specified bucket and an
    optional root prefix/folder.

    Args:
        bucket_name: Name of the S3 bucket.
        prefix: Optional root prefix (folder) within the bucket.
        s3_client: Optional pre-configured boto3 S3 client (e.g. for testing with moto).
        aws_access_key_id: Optional AWS access key ID.
        aws_secret_access_key: Optional AWS secret access key.
        aws_session_token: Optional AWS session token.
        region_name: Optional AWS region name.
        endpoint_url: Optional custom endpoint URL (e.g. for MinIO or LocalStack).
    """

    def __init__(
        self,
        bucket_name: str,
        prefix: str = "",
        s3_client: Any = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
        region_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        # Strip any leading 's3://' or slashes from bucket name
        cleaned_bucket = bucket_name.strip()
        if cleaned_bucket.startswith("s3://"):
            cleaned_bucket = cleaned_bucket[5:]
        self.bucket_name = cleaned_bucket.split("/")[0]

        # Normalize prefix
        self.prefix = prefix.strip().strip("/").replace("\\", "/")

        if s3_client is not None:
            self.s3_client = s3_client
        else:
            client_kwargs: dict[str, Any] = {}
            if aws_access_key_id:
                client_kwargs["aws_access_key_id"] = aws_access_key_id
            if aws_secret_access_key:
                client_kwargs["aws_secret_access_key"] = aws_secret_access_key
            if aws_session_token:
                client_kwargs["aws_session_token"] = aws_session_token
            if region_name:
                client_kwargs["region_name"] = region_name
            if endpoint_url:
                client_kwargs["endpoint_url"] = endpoint_url
            self.s3_client = boto3.client("s3", **client_kwargs)

    def _resolve_key(self, path: str) -> str:
        """Map a logical path or s3 URI to an S3 object key including self.prefix."""
        clean = path.strip()
        # Handle full s3:// URLs
        if clean.startswith("s3://"):
            clean = clean[5:]
            if clean.startswith(f"{self.bucket_name}/"):
                clean = clean[len(self.bucket_name) + 1:]
            elif "/" in clean:
                # Strip another bucket name prefix if present
                clean = clean.split("/", 1)[1]
        else:
            try:
                from pathlib import Path
                from src.utils.config import PROJECT_ROOT

                p = Path(clean)
                if p.is_absolute() and p.is_relative_to(PROJECT_ROOT):
                    clean = p.relative_to(PROJECT_ROOT).as_posix()
            except (ValueError, AttributeError):
                pass

        clean = clean.replace("\\", "/").lstrip("/")

        if self.prefix:
            if clean == self.prefix or clean.startswith(f"{self.prefix}/"):
                return clean
            return f"{self.prefix}/{clean}" if clean else self.prefix
        return clean

    def _key_to_logical_path(self, key: str) -> str:
        """Strip root prefix to convert an S3 key back to a logical path."""
        if self.prefix and (key.startswith(f"{self.prefix}/") or key == self.prefix):
            return key[len(self.prefix) + 1:]
        return key

    def read_file(self, path: str) -> bytes:
        """Read and return byte content of an S3 object."""
        key = self._resolve_key(path)
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404", "NoSuchBucket"):
                raise FileNotFoundError(
                    f"File not found in S3: s3://{self.bucket_name}/{key}"
                ) from e
            raise

    def write_file(self, path: str, content: bytes) -> None:
        """Write byte content to an S3 object."""
        key = self._resolve_key(path)
        self.s3_client.put_object(Bucket=self.bucket_name, Key=key, Body=content)

    def exists(self, path: str) -> bool:
        """Check whether an S3 object exists."""
        key = self._resolve_key(path)
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                return False
            raise

    def list_files(self, prefix: str) -> list[str]:
        """List all logical file paths under the given prefix in S3."""
        clean_prefix = prefix.strip().replace("\\", "/").lstrip("/")
        if clean_prefix:
            full_prefix = self._resolve_key(clean_prefix)
        else:
            full_prefix = f"{self.prefix}/" if self.prefix else ""

        results: list[str] = []
        paginator = self.s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key", "")
                # Skip directory marker keys
                if key.endswith("/"):
                    continue
                results.append(self._key_to_logical_path(key))

        return sorted(results)
