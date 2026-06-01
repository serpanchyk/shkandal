"""HTTP transport contracts for ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

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
