from __future__ import annotations

from ..config import StorageConfig
from .base import StorageBackend
from .local import LocalStorage


def build_storage(cfg: StorageConfig) -> StorageBackend:
    if cfg.backend == "local":
        return LocalStorage(cfg.local_root)
    if cfg.backend == "s3":
        from .s3 import S3Storage  # lazy import: boto3 only needed for this path

        return S3Storage(bucket=cfg.s3_bucket, prefix=cfg.s3_prefix, region=cfg.s3_region)
    raise ValueError(f"Unknown storage backend: {cfg.backend!r}")
