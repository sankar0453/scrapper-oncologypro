"""Storage backend interface.

Everything that writes output (URL lists, master metadata, PDFs, logs-of-
record) goes through this interface so the rest of the codebase never knows
or cares whether it's writing to local disk or S3. Swapping backends is a
one-line config change (--storage s3 --s3-bucket ...).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class StorageBackend(ABC):
    @abstractmethod
    def write_bytes(self, relative_path: str, data: bytes) -> str:
        """Writes data, returns a backend-specific location string (local
        path or s3:// URI) for logging/manifest purposes."""

    @abstractmethod
    def write_text(self, relative_path: str, text: str) -> str:
        ...

    @abstractmethod
    def read_text(self, relative_path: str) -> str:
        ...

    @abstractmethod
    def exists(self, relative_path: str) -> bool:
        ...

    @abstractmethod
    def list(self, prefix: str) -> Iterable[str]:
        ...
