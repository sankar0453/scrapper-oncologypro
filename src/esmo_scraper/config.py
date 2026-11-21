"""Central configuration objects for the ESMO OncologyPRO scraper.

Everything that varies between runs (which conference, which formats, where
output goes, proxy/storage settings) lives here as plain dataclasses so it
can be built once from CLI args (or a YAML/env file later) and passed down
instead of read from globals.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Formats the site exposes per presentation, and the Kontent.ai modular_content
# field that links to the actual content item for that format. "accessible"
# notes what we've confirmed about each format's accessibility_level:
#   - "abstract" items are tagged Public -> safe to bulk-fetch content.
#   - "eposter"/"slides" linked items are tagged Tickets/Members -> gated.
# The scraper always collects the *URL + metadata* for every selected format
# (that's just catalog data). It only fetches/renders full *content* for
# formats confirmed Public, unless --allow-gated is passed explicitly, in
# which case it still only uses the public API (no login) and will simply
# get back whatever (if anything) that API exposes for a gated item.
FORMAT_FIELD_MAP = {
    "abstract": {"field": "abstract", "item_type": "abstract", "default_public": True},
    "eposter": {"field": "eposter", "item_type": "eposter", "default_public": False},
    "poster": {"field": "eposter", "item_type": "eposter", "default_public": False},  # alias
    "slides": {"field": "slides", "item_type": "slides", "default_public": False},
    "webcast": {"field": "webcast", "item_type": "webcast", "default_public": False},
}


@dataclass
class ProxyConfig:
    # A single proxy URL ("http://user:pass@host:port"), and/or a path to a
    # newline-delimited file of proxy URLs to round-robin across. Either can
    # come from env vars so credentials never need to sit in a CLI history.
    proxy_url: Optional[str] = None
    proxy_list_file: Optional[str] = None

    @classmethod
    def from_env_and_args(cls, proxy_url: Optional[str], proxy_list_file: Optional[str]) -> "ProxyConfig":
        return cls(
            proxy_url=proxy_url or os.environ.get("ESMO_SCRAPER_PROXY"),
            proxy_list_file=proxy_list_file or os.environ.get("ESMO_SCRAPER_PROXY_LIST"),
        )


@dataclass
class StorageConfig:
    backend: str = "local"  # "local" or "s3"
    local_root: str = "data"
    s3_bucket: Optional[str] = None
    s3_prefix: str = "esmo"
    s3_region: Optional[str] = None
    # Credentials are intentionally NOT a field here: boto3 picks them up from
    # the environment / ~/.aws/credentials / an instance role. We never want
    # an AWS key living in a config object that might get logged or committed.

    def __post_init__(self):
        if self.backend == "s3" and not self.s3_bucket:
            raise ValueError("StorageConfig(backend='s3') requires s3_bucket")


@dataclass
class RunConfig:
    congress_search: str                 # e.g. "ESMO Congress 2026"
    congress_slug: str                   # e.g. "esmo-congress-2026" (URL path segment)
    formats: list = field(default_factory=lambda: ["abstract"])
    limit: int = 0                       # 0 = no limit
    render_pdfs: bool = False
    allow_gated: bool = False            # see FORMAT_FIELD_MAP docstring
    storage: StorageConfig = field(default_factory=StorageConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    log_level: str = "INFO"
    log_json: bool = True
    batch_size: int = 500
    request_delay_seconds: float = 0.25
    max_retries: int = 5
