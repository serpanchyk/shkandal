"""Remote image URL availability checks."""

from __future__ import annotations

from ipaddress import ip_address
from time import monotonic
from typing import Protocol
from urllib.parse import urlparse

import httpx

MAX_CACHE_ENTRIES = 10_000


class ImageUrlChecker(Protocol):
    """Select the first reachable URL from ordered image candidates."""

    async def first_available(self, urls: list[str]) -> str | None: ...


class HttpxImageUrlChecker:
    """Check remote images without downloading their response bodies."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_candidates: int,
        cache_ttl_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._max_candidates = max_candidates
        self._cache_ttl_seconds = cache_ttl_seconds
        self._availability: dict[str, tuple[float, bool]] = {}
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def first_available(self, urls: list[str]) -> str | None:
        attempts = 0
        for url in urls:
            if not _is_remote_http_url(url):
                continue
            if attempts >= self._max_candidates:
                break
            attempts += 1
            cached = self._availability.get(url)
            if cached is not None and cached[0] > monotonic():
                if cached[1]:
                    return url
                continue
            try:
                async with self._client.stream("GET", url) as response:
                    available = 200 <= response.status_code < 300
                    self._remember(url, available)
                    if available:
                        return url
            except httpx.HTTPError:
                self._remember(url, False)
                continue
        return None

    def _remember(self, url: str, available: bool) -> None:
        if len(self._availability) >= MAX_CACHE_ENTRIES and url not in self._availability:
            self._availability.pop(next(iter(self._availability)))
        self._availability[url] = (monotonic() + self._cache_ttl_seconds, available)

    async def close(self) -> None:
        await self._client.aclose()


def _is_remote_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname == "localhost" or parsed.hostname.endswith(".localhost"):
        return False
    try:
        address = ip_address(parsed.hostname)
    except ValueError:
        return True
    return address.is_global
