from __future__ import annotations

import os
from typing import Iterable

from .base import StorageBackend


class LocalStorage(StorageBackend):
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _full(self, relative_path: str) -> str:
        full = os.path.join(self.root, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        return full

    def write_bytes(self, relative_path: str, data: bytes) -> str:
        full = self._full(relative_path)
        with open(full, "wb") as f:
            f.write(data)
        return full

    def write_text(self, relative_path: str, text: str) -> str:
        return self.write_bytes(relative_path, text.encode("utf-8"))

    def read_text(self, relative_path: str) -> str:
        full = os.path.join(self.root, relative_path)
        with open(full, encoding="utf-8") as f:
            return f.read()

    def exists(self, relative_path: str) -> bool:
        return os.path.exists(os.path.join(self.root, relative_path))

    def list(self, prefix: str) -> Iterable[str]:
        base = os.path.join(self.root, prefix)
        if not os.path.isdir(base):
            return []
        out = []
        for dirpath, _, filenames in os.walk(base):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, self.root))
        return out
