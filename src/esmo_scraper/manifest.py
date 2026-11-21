"""Master metadata file: the single source of truth for "what do we know
about this conference" that survives across runs.

Two different metadata artifacts exist in this system, on purpose:

  1. Per-run snapshot (data/{slug}/{run_id}/metadata/run_metadata.jsonl) --
     exactly what this one run saw and did. Immutable once the run ends.
     This is what you'd hand an auditor: "what happened in run X".

  2. Master metadata (data/{slug}/master_metadata.jsonl) -- one row per
     presentation codename, cumulative across every run against this
     conference. Re-running the same conference updates this file in place
     rather than duplicating rows, and tracks a content_hash + the API's own
     last_modified timestamp so a re-run can tell new / unchanged / updated
     apart and skip re-downloading/re-rendering anything that hasn't
     changed. This is what you query to answer "what do we have, right now,
     for this conference".

JSONL (one JSON object per line) rather than CSV/Parquet: trivially
appendable, diffable, greppable, and loads fine into pandas/DuckDB/Athena
later without a schema migration every time a field gets added.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from .storage.base import StorageBackend

logger = logging.getLogger("esmo_scraper.manifest")


def content_hash(record: dict) -> str:
    """Hash of the fields that matter for change detection -- deliberately
    excludes run bookkeeping fields (first_seen_run_id etc.) so those don't
    make every record look "changed" on every run."""
    stable = {k: v for k, v in record.items() if k not in (
        "first_seen_run_id", "last_seen_run_id", "last_changed_run_id",
        "status", "content_hash",
    )}
    blob = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class MasterMetadata:
    def __init__(self, storage: StorageBackend, relative_path: str):
        self.storage = storage
        self.relative_path = relative_path
        self.records: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not self.storage.exists(self.relative_path):
            return {}
        text = self.storage.read_text(self.relative_path)
        records = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            records[row["codename"]] = row
        logger.info("master metadata loaded", extra={"stage": "manifest_load", "existing_records": len(records)})
        return records

    def upsert(self, record: dict, run_id: str) -> str:
        """record must include 'codename'. Returns the status assigned:
        'new', 'unchanged', or 'updated'."""
        codename = record["codename"]
        new_hash = content_hash(record)
        existing = self.records.get(codename)

        if existing is None:
            status = "new"
            record["first_seen_run_id"] = run_id
            record["last_seen_run_id"] = run_id
            record["last_changed_run_id"] = run_id
        else:
            record["first_seen_run_id"] = existing.get("first_seen_run_id", run_id)
            record["last_seen_run_id"] = run_id
            if existing.get("content_hash") == new_hash:
                status = "unchanged"
                record["last_changed_run_id"] = existing.get("last_changed_run_id", run_id)
                # keep any backend file locations from the previous run
                for carry_field in ("local_pdf_path", "storage_uri"):
                    if carry_field in existing and carry_field not in record:
                        record[carry_field] = existing[carry_field]
            else:
                status = "updated"
                record["last_changed_run_id"] = run_id

        record["content_hash"] = new_hash
        record["status"] = status
        self.records[codename] = record
        return status

    def save(self):
        lines = [json.dumps(r, sort_keys=True, default=str) for r in self.records.values()]
        self.storage.write_text(self.relative_path, "\n".join(lines) + ("\n" if lines else ""))
        logger.info("master metadata saved", extra={"stage": "manifest_save", "total_records": len(lines)})

    def summary(self) -> dict:
        counts: Dict[str, int] = {}
        for r in self.records.values():
            counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        return counts
