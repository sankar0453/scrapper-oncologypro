"""Structured, per-run logging.

Every run gets a run_id (UTC timestamp + short random suffix) that's attached
to every log line, so logs from concurrent or repeated runs against the same
conference never get mixed up when grepped later. Two sinks are configured:

  - a human-readable rotating file (run.log) + console, for watching a run live
  - a JSON-lines file (run.jsonl) with structured fields, for feeding into
    anything observability-shaped later (CloudWatch Logs, Datadog, grep -
    jq, a Loki/Elastic stack, whatever) without needing a log parser.
"""
from __future__ import annotations

import json
import logging
import os
import random
import string
import sys
import time
from logging.handlers import RotatingFileHandler


def new_run_id() -> str:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{ts}-{suffix}"


class _JsonFormatter(logging.Formatter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "run_id": self.run_id,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Any extra= fields passed to the log call ride along verbatim, e.g.
        # logger.info("fetched item", extra={"codename": ..., "stage": "collect"})
        for k, v in record.__dict__.items():
            if k in payload or k in (
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelno", "lineno", "module", "msecs", "msg", "name",
                "pathname", "process", "processName", "relativeCreated", "stack_info",
                "thread", "threadName", "levelname", "taskName",
            ):
                continue
            payload[k] = v
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(run_id: str, log_dir: str, level: str = "INFO", json_logs: bool = True) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("esmo_scraper")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(f"%(asctime)s [{run_id}] %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(console)

    text_file = RotatingFileHandler(os.path.join(log_dir, "run.log"), maxBytes=10_000_000, backupCount=3)
    text_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logger.addHandler(text_file)

    if json_logs:
        json_file = logging.FileHandler(os.path.join(log_dir, "run.jsonl"))
        json_file.setFormatter(_JsonFormatter(run_id))
        logger.addHandler(json_file)

    return logger
