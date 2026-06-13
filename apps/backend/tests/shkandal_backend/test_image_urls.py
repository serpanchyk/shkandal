import httpx
from shkandal_backend.image_urls import HttpxImageUrlChecker


async def test_image_url_checker_skips_dead_url_and_returns_next_available() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/error.jpg":
            raise httpx.ConnectError("unreachable", request=request)
        status_code = 404 if request.url.path == "/dead.jpg" else 200
        return httpx.Response(status_code, request=request)

    checker = HttpxImageUrlChecker(
        timeout_seconds=1,
        max_candidates=5,
        cache_ttl_seconds=60,
        transport=httpx.MockTransport(handler),
    )

    result = await checker.first_available(
        [
            "https://example.com/dead.jpg",
            "https://example.com/error.jpg",
            "https://example.com/live.jpg",
        ]
    )

    assert result == "https://example.com/live.jpg"
    assert requested_urls == [
        "https://example.com/dead.jpg",
        "https://example.com/error.jpg",
        "https://example.com/live.jpg",
    ]

    assert (
        await checker.first_available(
            ["https://example.com/dead.jpg", "https://example.com/error.jpg", result]
        )
        == result
    )
    assert requested_urls == [
        "https://example.com/dead.jpg",
        "https://example.com/error.jpg",
        "https://example.com/live.jpg",
    ]
    await checker.close()


async def test_image_url_checker_skips_invalid_urls_and_bounds_requests() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(404, request=request)

    checker = HttpxImageUrlChecker(
        timeout_seconds=1,
        max_candidates=2,
        cache_ttl_seconds=60,
        transport=httpx.MockTransport(handler),
    )

    result = await checker.first_available(
        [
            "file:///etc/passwd",
            "http://localhost/private.jpg",
            "http://127.0.0.1/private.jpg",
            "https://example.com/one.jpg",
            "https://example.com/two.jpg",
            "https://example.com/three.jpg",
        ]
    )
    await checker.close()

    assert result is None
    assert requested_urls == [
        "https://example.com/one.jpg",
        "https://example.com/two.jpg",
    ]
