"""HTTP transport contracts for ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from curl_cffi.requests import AsyncSession as CurlAsyncSession

from worker_ingestion.config import IngestionConfig


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    text: str
    headers: dict[str, str]
    fetched_at: datetime
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300 and self.error is None


class Fetcher(Protocol):
    async def fetch(self, url: str) -> FetchResult:
        """Fetch one URL."""


class HttpxFetcher:
    """Async HTTP fetcher for source pages and sitemaps."""

    def __init__(
        self,
        config: IngestionConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    async def fetch(self, url: str) -> FetchResult:
        if _requires_browser_impersonation(url):
            return await self._fetch_with_browser_impersonation(url)

        async with httpx.AsyncClient(
            headers={"user-agent": self.config.request_user_agent},
            timeout=self.config.request_timeout_seconds,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                return FetchResult(
                    url=url,
                    status_code=0,
                    content=b"",
                    text="",
                    headers={},
                    fetched_at=datetime.now(UTC),
                    error=str(exc),
                )

        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content=response.content,
            text=response.text,
            headers={key.lower(): value for key, value in response.headers.items()},
            fetched_at=datetime.now(UTC),
        )

    async def _fetch_with_browser_impersonation(self, url: str) -> FetchResult:
        headers = {
            "accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
            "accept-language": "uk-UA,uk;q=0.9,en-US;q=0.7,en;q=0.6",
            "referer": "https://www.pravda.com.ua/",
        }
        try:
            async with CurlAsyncSession(
                impersonate="chrome124",
                timeout=self.config.request_timeout_seconds,
                headers=headers,
            ) as client:
                response = await client.get(url, allow_redirects=True)
        except Exception as exc:
            return FetchResult(
                url=url,
                status_code=0,
                content=b"",
                text="",
                headers={},
                fetched_at=datetime.now(UTC),
                error=str(exc),
            )

        return FetchResult(
            url=str(response.url),
            status_code=response.status_code,
            content=response.content,
            text=response.text,
            headers={key.lower(): value for key, value in response.headers.items()},
            fetched_at=datetime.now(UTC),
        )


def _requires_browser_impersonation(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc in {"www.pravda.com.ua", "pravda.com.ua"}
