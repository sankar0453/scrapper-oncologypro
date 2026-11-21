"""Client for the public Kontent.ai Delivery API that oncologypro.esmo.org's
own frontend uses (see the esmo-oncologypro-scraper skill for how this was
found). No authentication is required or used for this public content.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .proxy import ProxyPool

BASE_URL = "https://kontent.cdn.aws.esmo.org/rest"
USER_AGENT = "esmo-scraper/1.0 (personal/research use; see esmo-oncologypro-scraper skill)"

logger = logging.getLogger("esmo_scraper.api_client")


class KontentClient:
    def __init__(self, proxy_pool: Optional[ProxyPool] = None, max_retries: int = 5, request_delay_seconds: float = 0.25):
        self.proxy_pool = proxy_pool
        self.request_delay_seconds = request_delay_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        retry = Retry(
            total=max_retries,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        proxies = self.proxy_pool.next() if self.proxy_pool and self.proxy_pool.enabled else None
        start = time.monotonic()
        try:
            resp = self.session.get(f"{BASE_URL}{path}", params=params, proxies=proxies, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            if proxies:
                self.proxy_pool.mark_dead(proxies)
            logger.error("request failed", extra={"stage": "http_error", "path": path, "error": str(e)})
            raise
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.debug(
            "request ok",
            extra={"stage": "http_ok", "path": path, "duration_ms": duration_ms, "status": resp.status_code},
        )
        if self.request_delay_seconds:
            time.sleep(self.request_delay_seconds)
        return resp.json()

    def get_item(self, codename: str) -> Dict[str, Any]:
        return self._get(f"/items/{codename}", {})

    def paginate_items(self, params: Dict[str, Any], batch_size: int = 500, limit: int = 0) -> Iterator[Dict[str, Any]]:
        """Yields raw item dicts, transparently paginating with skip/limit."""
        skip = 0
        yielded = 0
        while True:
            p = dict(params, limit=batch_size, skip=skip, includeTotalCount="")
            d = self._get("/items", p)
            items = d["items"]
            if not items:
                return
            for it in items:
                yield it
                yielded += 1
                if limit and yielded >= limit:
                    return
            skip += batch_size
            total = d.get("pagination", {}).get("total_count")
            logger.info(
                "page fetched",
                extra={"stage": "paginate", "fetched": yielded, "total": total},
            )
            if total is not None and skip >= total:
                return
