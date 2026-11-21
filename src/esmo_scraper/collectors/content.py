"""Fetches the full linked content item for each collected row (the actual
abstract text, or whatever a gated eposter/slides item exposes), batched by
format so we only ask the API for item types we actually need.

Accessibility is checked per item (`security__accessibility_level`) before
treating anything as fetchable content. Only items tagged "public" get their
body content used for rendering; anything else (Tickets/Members-only, which
is what we've found eposter/slides items to be) is recorded as gated in the
output, not downloaded -- this tool only ever calls the same unauthenticated
public API the site itself exposes, it never logs in or carries a session.

Important, empirically-confirmed API behavior: the Delivery API's *listing*
endpoint (`/items?system.type=...`) silently excludes non-public items --
querying `system.type=eposter` for a conference that has thousands of
eposters returns `total_count: 0`, even though those items definitely exist
and definitely carry the right ticket_code (confirmed by fetching one
directly by codename: `/items/{codename}` still returns it, just with only
the security fields populated, no title/content). So "the bulk listing came
back empty" is itself the signal that a format is access-gated for this
conference -- we treat it that way and stop there, rather than issuing one
GET per linked codename just to learn the same thing thousands of times.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from ..api_client import KontentClient
from ..config import FORMAT_FIELD_MAP

logger = logging.getLogger("esmo_scraper.collectors.content")


def fetch_bodies(client: KontentClient, ticket_code: str, item_type: str, limit: int = 0) -> Dict[str, dict]:
    """Bulk-fetches every item of the given Kontent content type tagged for
    this conference (much cheaper than one GET per linked codename, but costs
    the same regardless of how many rows the caller actually needs -- prefer
    fetch_bodies_by_codenames when the caller already knows which codenames
    it needs, e.g. because --limit bounded the row collection)."""
    params = {
        "system.type": item_type,
        "elements.security__ticket_code[contains]": ticket_code,
        "elements": "title,content,authors_block,authors_affiliations,citation,code,security__accessibility_level",
    }
    out: Dict[str, dict] = {}
    for item in client.paginate_items(params, limit=limit):
        out[item["system"]["codename"]] = item["elements"]
    logger.info("content fetch complete", extra={"stage": "collect_content", "item_type": item_type, "count": len(out)})
    return out


def fetch_bodies_by_codenames(client: KontentClient, item_type: str, codenames: List[str], chunk_size: int = 50) -> Dict[str, dict]:
    """Fetches only the given codenames of the given type, via
    system.codename[in]=..., chunked to keep URLs a sane length. Cost is
    proportional to len(codenames), not to the conference's total item
    count -- this is what a --limit'd run (or a targeted re-fetch of just
    the 'updated' rows from a prior run) should use instead of fetch_bodies."""
    out: Dict[str, dict] = {}
    unique = sorted(set(codenames))
    for i in range(0, len(unique), chunk_size):
        chunk = unique[i:i + chunk_size]
        params = {
            "system.type": item_type,
            "system.codename[in]": ",".join(chunk),
            "elements": "title,content,authors_block,authors_affiliations,citation,code,security__accessibility_level",
            "limit": chunk_size,
            "includeTotalCount": "",
        }
        d = client._get("/items", params)
        for item in d["items"]:
            out[item["system"]["codename"]] = item["elements"]
    logger.info(
        "targeted content fetch complete",
        extra={"stage": "collect_content_targeted", "item_type": item_type, "requested": len(unique), "found": len(out)},
    )
    return out


def is_public(elements: dict) -> bool:
    levels = [t["codename"] for t in elements.get("security__accessibility_level", {}).get("value", [])]
    return (not levels) or ("public" in levels)


def probe_type_gated(client: KontentClient, ticket_code: str, item_type: str) -> bool:
    """Cheap (limit=1) check: does the bulk listing for this item type +
    conference come back empty? If so the whole type is access-gated for
    this conference -- see module docstring."""
    d = client._get("/items", {
        "system.type": item_type,
        "elements.security__ticket_code[contains]": ticket_code,
        "elements": "title",
        "limit": 1,
        "includeTotalCount": "",
    })
    return d.get("pagination", {}).get("total_count", 0) == 0


def fetch_all_bodies(client: KontentClient, ticket_code: str, formats: List[str], needed_codenames_by_format: Dict[str, List[str]] = None):
    """Returns (bodies_by_format, gated_formats):
      - bodies_by_format: {format_name: {linked_codename: elements}}
      - gated_formats: set of format names whose listing was confirmed
        access-gated for this conference (see probe_type_gated) -- the
        caller should record every row for these as content_status='gated'
        without treating a missing dict entry as some other kind of error.

    When needed_codenames_by_format is given (the normal case: it's exactly
    the linked_item_codename values from the rows the caller already
    collected), a non-gated format is fetched with fetch_bodies_by_codenames
    -- cost proportional to the rows actually in play, not to every item of
    that type in the whole conference. Omit it to force a full bulk fetch
    per type instead (fetch_bodies) -- rarely what you want.
    """
    needed_codenames_by_format = needed_codenames_by_format or {}
    item_types = {FORMAT_FIELD_MAP[f]["item_type"] for f in formats}
    by_type: Dict[str, Dict[str, dict]] = {}
    gated_types = set()
    for t in item_types:
        if probe_type_gated(client, ticket_code, t):
            logger.info(
                "format listing is access-gated for this conference, skipping bulk fetch",
                extra={"stage": "collect_content_gated", "item_type": t},
            )
            by_type[t] = {}
            gated_types.add(t)
        else:
            fmts_for_type = [f for f in formats if FORMAT_FIELD_MAP[f]["item_type"] == t]
            codenames = [c for f in fmts_for_type for c in needed_codenames_by_format.get(f, [])]
            if codenames:
                by_type[t] = fetch_bodies_by_codenames(client, t, codenames)
            else:
                by_type[t] = fetch_bodies(client, ticket_code, t)
    bodies_by_format = {fmt: by_type[FORMAT_FIELD_MAP[fmt]["item_type"]] for fmt in formats}
    gated_formats = {fmt for fmt in formats if FORMAT_FIELD_MAP[fmt]["item_type"] in gated_types}
    return bodies_by_format, gated_formats
