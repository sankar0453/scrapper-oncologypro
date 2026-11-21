"""Collects presentation URLs + catalog metadata for a conference, for one
or more formats, in a single pass over the presentation list (one paginated
query covering every requested format's link field, rather than one query
per format).
"""
from __future__ import annotations

import logging
from typing import Iterator, List

from ..api_client import KontentClient
from ..config import FORMAT_FIELD_MAP

logger = logging.getLogger("esmo_scraper.collectors.urls")


def collect(client: KontentClient, ticket_code: str, congress_slug: str, formats: List[str], limit: int = 0) -> Iterator[dict]:
    fields_needed = sorted({FORMAT_FIELD_MAP[f]["field"] for f in formats})
    elements = ",".join(["title", "citation", "code", "start", "security__accessibility_level"] + fields_needed)

    params = {
        "system.type": "presentation",
        "elements.security__ticket_code[contains]": ticket_code,
        "elements": elements,
    }

    count = 0
    for item in client.paginate_items(params, limit=limit):
        sysd = item["system"]
        el = item["elements"]
        base = {
            "codename": sysd["codename"],
            "congress_slug": congress_slug,
            "title": el.get("title", {}).get("value"),
            "citation": el.get("citation", {}).get("value"),
            "abstract_code": el.get("code", {}).get("value"),
            "url": f"https://oncologypro.esmo.org/congress-resources/{congress_slug}?presentation={sysd['codename']}",
            "last_modified_api": sysd.get("last_modified"),
        }
        accessibility = [t["codename"] for t in el.get("security__accessibility_level", {}).get("value", [])]

        for fmt in formats:
            field_name = FORMAT_FIELD_MAP[fmt]["field"]
            linked = el.get(field_name, {}).get("value", [])
            if not linked:
                continue
            row = dict(base)
            row["codename"] = f"{sysd['codename']}::{fmt}"  # unique per (presentation, format)
            row["presentation_codename"] = sysd["codename"]
            row["format"] = fmt
            row["linked_item_codename"] = linked[0]
            row["presentation_accessibility"] = accessibility
            yield row
            count += 1
    logger.info("url collection complete", extra={"stage": "collect_urls", "rows": count, "formats": formats})
