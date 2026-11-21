"""Dynamic conference discovery.

Conferences aren't hardcoded. ESMO runs dozens of them a year (ESMO Congress,
ESMO GI, ESMO Breast, ELCC, ESMO Asia, TAT, preceptorships, ...), each
identified on the backend by a `security__ticket_code` taxonomy term. This
module samples the `presentation` content type to build the list of terms
that actually have content, so `list_conferences()` always reflects what's
really on the site rather than a list someone has to remember to update.

There's no cheaper endpoint for this: the Kontent.ai Delivery API exposes
taxonomy *definitions* (the full tree of possible terms) but this proxy
doesn't expose that route (`/taxonomies/{group}` 404s here), and the
definitions wouldn't tell us which terms actually have presentations tagged
against them anyway. So this does cost a full scan of the `presentation`
content type (tens of thousands of items, in pages of 500) -- the one
genuinely expensive call in this tool. A short-lived local cache (default 1
hour) means that cost is paid once per cache window rather than on every
invocation, which matters a lot for `list-conferences`/`formats`/`run`
all being run back-to-back against the same congress, as they normally are.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

from .api_client import KontentClient

logger = logging.getLogger("esmo_scraper.discovery")

DEFAULT_CACHE_PATH = os.path.expanduser("~/.cache/esmo_scraper/conferences.json")
DEFAULT_CACHE_TTL_SECONDS = 3600


def _load_cache(cache_path: str, ttl_seconds: int) -> Optional[Dict[str, str]]:
    try:
        with open(cache_path) as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    age = time.time() - payload.get("fetched_at", 0)
    if age > ttl_seconds:
        return None
    logger.info("conference list served from cache", extra={"stage": "discovery_cache_hit", "age_seconds": int(age)})
    return payload.get("conferences")


def _save_cache(cache_path: str, conferences: Dict[str, str]):
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump({"fetched_at": time.time(), "conferences": conferences}, f)


def list_conferences(
    client: KontentClient,
    sample_limit: int = 50000,
    cache_path: str = DEFAULT_CACHE_PATH,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
) -> Dict[str, str]:
    """Returns {ticket_codename: display_name} for every congress/event that
    has at least one presentation. sample_limit caps how many presentation
    records are scanned to build this list -- raise it if a very recently
    added congress with few items doesn't show up yet. Cached locally for
    cache_ttl_seconds (default 1h); pass force_refresh=True (CLI:
    --refresh-conferences) to bypass the cache, e.g. right after a brand
    new congress goes live."""
    if not force_refresh:
        cached = _load_cache(cache_path, cache_ttl_seconds)
        if cached is not None:
            return cached

    seen: Dict[str, str] = {}
    for item in client.paginate_items(
        {"system.type": "presentation", "elements": "security__ticket_code"},
        limit=sample_limit,
    ):
        for t in item["elements"].get("security__ticket_code", {}).get("value", []):
            seen[t["codename"]] = t["name"]
    logger.info("conference discovery complete (full scan)", extra={"stage": "discovery", "conference_count": len(seen)})
    _save_cache(cache_path, seen)
    return seen


def resolve_conference(client: KontentClient, search_text: str, **list_conferences_kwargs) -> Optional[tuple[str, str]]:
    """Case-insensitive substring match against known conference names.
    Returns (ticket_codename, display_name), or None if zero/ambiguous."""
    matches = {k: v for k, v in list_conferences(client, **list_conferences_kwargs).items() if search_text.lower() in v.lower()}
    if len(matches) == 1:
        return next(iter(matches.items()))
    if len(matches) == 0:
        logger.error("no conference matched", extra={"stage": "resolve", "search": search_text})
        return None
    logger.error(
        "ambiguous conference search, multiple matches",
        extra={"stage": "resolve", "search": search_text, "matches": matches},
    )
    return None


def available_formats(client: KontentClient, ticket_code: str) -> Dict[str, int]:
    """For a resolved conference, returns {format_name: count} for each
    format field (abstract/eposter/slides/webcast) that has at least one
    linked item, so callers can show what's actually selectable."""
    from .config import FORMAT_FIELD_MAP

    counts = {}
    checked_fields = set()
    for fmt, spec in FORMAT_FIELD_MAP.items():
        field_name = spec["field"]
        if field_name in checked_fields:
            continue
        checked_fields.add(field_name)
        d = client._get("/items", {
            "system.type": "presentation",
            f"elements.security__ticket_code[contains]": ticket_code,
            f"elements.{field_name}[nempty]": "",
            "elements": "title",
            "limit": 1,
            "includeTotalCount": "",
        })
        counts[field_name] = d.get("pagination", {}).get("total_count", 0)
    return counts
