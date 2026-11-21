"""Optional proxy support for outbound requests.

Nothing requires a proxy by default -- the scraper talks to ESMO's own public
API, at a polite rate, the same way the website does. Proxy support exists
for cases like: running from an environment with restricted egress, wanting
geographic diversity for latency, or routing through a corporate egress
proxy. It is NOT here to evade rate limits or terms of use -- keep the same
request pacing regardless of how many proxies you have configured.
"""
from __future__ import annotations

import itertools
import logging
from typing import Iterator, Optional

from .config import ProxyConfig

logger = logging.getLogger("esmo_scraper.proxy")


class ProxyPool:
    """Round-robins through configured proxies. With zero or one proxy
    configured, behaves like "no rotation" (always the same proxy, or none)."""

    def __init__(self, proxy_config: ProxyConfig):
        proxies = []
        if proxy_config.proxy_url:
            proxies.append(proxy_config.proxy_url)
        if proxy_config.proxy_list_file:
            with open(proxy_config.proxy_list_file) as f:
                proxies.extend(line.strip() for line in f if line.strip() and not line.startswith("#"))
        self._proxies = proxies
        self._cycle: Optional[Iterator[str]] = itertools.cycle(proxies) if proxies else None
        self._dead: set[str] = set()
        if proxies:
            logger.info("proxy pool initialised", extra={"stage": "proxy_init", "proxy_count": len(proxies)})

    @property
    def enabled(self) -> bool:
        return bool(self._proxies)

    def next(self) -> Optional[dict]:
        """Returns a requests-style {'http': ..., 'https': ...} dict, or None."""
        if not self._cycle:
            return None
        for _ in range(len(self._proxies)):
            p = next(self._cycle)
            if p not in self._dead:
                return {"http": p, "https": p}
        # everything marked dead; reset and try again rather than fail hard
        logger.warning("all proxies marked dead, resetting pool", extra={"stage": "proxy_reset"})
        self._dead.clear()
        return {"http": self._proxies[0], "https": self._proxies[0]}

    def mark_dead(self, proxy_dict: Optional[dict]):
        if proxy_dict:
            self._dead.add(proxy_dict.get("https") or proxy_dict.get("http"))
            logger.warning(
                "proxy marked dead",
                extra={"stage": "proxy_dead", "proxy": proxy_dict.get("https"), "dead_count": len(self._dead)},
            )
