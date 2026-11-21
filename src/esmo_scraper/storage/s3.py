"""S3-backed storage.

Credentials are never read here directly -- boto3's default credential chain
(env vars AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN, an AWS
profile via AWS_PROFILE, an EC2/ECS instance role, or SSO) handles that. This
module only needs a bucket name and an optional key prefix.
"""
from __future__ import annotations

import logging
from typing import Iterable

from .base import StorageBackend

logger = logging.getLogger("esmo_scraper.storage.s3")


class S3Storage(StorageBackend):
    def __init__(self, bucket: str, prefix: str = "", region: str | None = None):
        import boto3  # imported lazily so boto3 is only required if S3 is actually used

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._s3 = boto3.client("s3", region_name=region)

    def _key(self, relative_path: str) -> str:
        relative_path = relative_path.lstrip("/")
        return f"{self.prefix}/{relative_path}" if self.prefix else relative_path

    def write_bytes(self, relative_path: str, data: bytes) -> str:
        key = self._key(relative_path)
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        uri = f"s3://{self.bucket}/{key}"
        logger.debug("uploaded to s3", extra={"stage": "s3_put", "uri": uri, "bytes": len(data)})
        return uri

    def write_text(self, relative_path: str, text: str) -> str:
        return self.write_bytes(relative_path, text.encode("utf-8"))

    def read_text(self, relative_path: str) -> str:
        key = self._key(relative_path)
        obj = self._s3.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read().decode("utf-8")

    def exists(self, relative_path: str) -> bool:
        from botocore.exceptions import ClientError

        key = self._key(relative_path)
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def list(self, prefix: str) -> Iterable[str]:
        key_prefix = self._key(prefix)
        paginator = self._s3.get_paginator("list_objects_v2")
        out = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                out.append(key[len(self.prefix) + 1:] if self.prefix else key)
        return out
