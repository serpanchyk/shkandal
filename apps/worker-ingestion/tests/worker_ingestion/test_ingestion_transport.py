from datetime import UTC, datetime

import httpx
import pytest
from worker_ingestion.config import IngestionConfig
from worker_ingestion.transport import FetchResult, HttpxFetcher


def test_fetch_result_ok_reflects_status_and_error() -> None:
    success = FetchResult(
        url="https://example.ua",
        status_code=200,
        content=b"ok",
        text="ok",
        headers={},
        fetched_at=datetime.now(UTC),
    )
    failure = FetchResult(
        url="https://example.ua",
        status_code=500,
        content=b"",
        text="",
        headers={},
        fetched_at=success.fetched_at,
        error="server_error",
    )

    assert success.ok
    assert not failure.ok


@pytest.mark.asyncio
async def test_httpx_fetcher_returns_response_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "test-agent"
        return httpx.Response(
            200,
            content=b"<html>ok</html>",
            headers={"content-type": "text/html"},
            request=request,
        )

    fetcher = HttpxFetcher(
        IngestionConfig(request_user_agent="test-agent"),
        transport=httpx.MockTransport(handler),
    )

    result = await fetcher.fetch("https://example.ua/news")

    assert result.ok
    assert result.url == "https://example.ua/news"
    assert result.status_code == 200
    assert result.text == "<html>ok</html>"
    assert result.headers["content-type"] == "text/html"


@pytest.mark.asyncio
async def test_httpx_fetcher_captures_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    fetcher = HttpxFetcher(IngestionConfig(), transport=httpx.MockTransport(handler))

    result = await fetcher.fetch("https://example.ua/news")

    assert not result.ok
    assert result.status_code == 0
    assert result.error is not None
