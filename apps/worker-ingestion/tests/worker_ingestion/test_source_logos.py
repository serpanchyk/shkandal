from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image
from worker_ingestion.source_logos import (
    SourceLogoRow,
    discover_icon_urls,
    normalize_raster_icon,
    select_largest_raster_icon,
    sync_source_logos,
)
from worker_ingestion.transport import FetchResult


class FakeFetcher:
    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self.responses = responses
        self.requested_urls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.requested_urls.append(url)
        return self.responses.get(url, _response(url, status_code=404))


class FakeSourceLogoRepository:
    def __init__(self, sources: tuple[SourceLogoRow, ...], *, fail_updates: bool = False) -> None:
        self.sources = sources
        self.fail_updates = fail_updates
        self.updates: list[tuple[UUID, str]] = []

    async def list_sources(self, source_slug: str | None = None) -> tuple[SourceLogoRow, ...]:
        if source_slug is None:
            return self.sources
        return tuple(source for source in self.sources if source.slug == source_slug)

    async def update_logo_path(self, source_id: UUID, logo_path: str) -> None:
        if self.fail_updates:
            raise RuntimeError("database unavailable")
        self.updates.append((source_id, logo_path))


def test_discover_icon_urls_resolves_links_skips_svg_and_adds_fallback() -> None:
    html = """
    <html><head>
      <link rel="icon" href="/small.png">
      <link rel="shortcut icon" href="https://cdn.example.ua/favicon.ico">
      <link rel="apple-touch-icon" href="touch.png">
      <link rel="icon" href="/vector.svg">
    </head></html>
    """

    assert discover_icon_urls(html, "https://example.ua/news") == (
        "https://example.ua/small.png",
        "https://cdn.example.ua/favicon.ico",
        "https://example.ua/touch.png",
        "https://example.ua/favicon.ico",
    )


@pytest.mark.parametrize("image_format", ["PNG", "JPEG", "WEBP", "ICO"])
def test_normalize_raster_icon_converts_supported_formats_to_png(image_format: str) -> None:
    icon = normalize_raster_icon(_image_bytes(48, 48, image_format), "https://example.ua/icon")

    assert icon.width == 48
    assert icon.height == 48
    assert icon.png.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_select_largest_raster_icon_ignores_invalid_and_svg_candidates() -> None:
    fetcher = FakeFetcher(
        {
            "https://example.ua/small.png": _response(
                "https://example.ua/small.png",
                content=_image_bytes(16, 16),
                content_type="image/png",
            ),
            "https://example.ua/vector": _response(
                "https://example.ua/vector",
                content=b"<svg/>",
                content_type="image/svg+xml",
            ),
            "https://example.ua/large.ico": _response(
                "https://example.ua/large.ico",
                content=_image_bytes(64, 64, "ICO"),
                content_type="image/x-icon",
            ),
        }
    )

    icon = await select_largest_raster_icon(
        (
            "https://example.ua/small.png",
            "https://example.ua/vector",
            "https://example.ua/large.ico",
        ),
        fetcher,
    )

    assert icon is not None
    assert icon.url == "https://example.ua/large.ico"
    assert (icon.width, icon.height) == (64, 64)


@pytest.mark.asyncio
async def test_sync_source_logos_dry_run_does_not_mutate(tmp_path: Path) -> None:
    source = _source("example")
    repository = FakeSourceLogoRepository((source,))
    fetcher = _website_fetcher(source.base_url, icon=_image_bytes(32, 32))

    results = await sync_source_logos(repository, fetcher, output_dir=tmp_path, apply=False)

    assert results[0].status == "would_update"
    assert results[0].logo_path == "/sources/example.png"
    assert repository.updates == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_sync_source_logos_apply_overwrites_asset_and_updates_row(tmp_path: Path) -> None:
    source = _source("example")
    repository = FakeSourceLogoRepository((source,))
    target = tmp_path / "example.png"
    target.write_bytes(b"old")
    fetcher = _website_fetcher(source.base_url, icon=_image_bytes(64, 64))

    results = await sync_source_logos(repository, fetcher, output_dir=tmp_path, apply=True)

    assert results[0].status == "updated"
    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert target.stat().st_mode & 0o777 == 0o644
    assert repository.updates == [(source.id, "/sources/example.png")]


@pytest.mark.asyncio
async def test_sync_source_logos_continues_after_failure(tmp_path: Path) -> None:
    failed = _source("failed", logo_path="/sources/old.png")
    succeeded = _source("succeeded")
    repository = FakeSourceLogoRepository((failed, succeeded))
    fetcher = _website_fetcher(succeeded.base_url, icon=_image_bytes(32, 32))

    results = await sync_source_logos(repository, fetcher, output_dir=tmp_path, apply=True)

    assert [result.status for result in results] == ["failed", "updated"]
    assert results[0].logo_path == "/sources/old.png"
    assert not (tmp_path / "failed.png").exists()
    assert (tmp_path / "succeeded.png").exists()


@pytest.mark.asyncio
async def test_sync_source_logos_restores_asset_when_database_update_fails(tmp_path: Path) -> None:
    source = _source("example", logo_path="/sources/example.png")
    repository = FakeSourceLogoRepository((source,), fail_updates=True)
    target = tmp_path / "example.png"
    target.write_bytes(b"previous")
    fetcher = _website_fetcher(source.base_url, icon=_image_bytes(64, 64))

    results = await sync_source_logos(repository, fetcher, output_dir=tmp_path, apply=True)

    assert results[0].status == "failed"
    assert results[0].logo_path == "/sources/example.png"
    assert target.read_bytes() == b"previous"


def _source(slug: str, logo_path: str | None = None) -> SourceLogoRow:
    return SourceLogoRow(
        id=uuid4(),
        slug=slug,
        base_url=f"https://{slug}.example.ua",
        logo_path=logo_path,
    )


def _website_fetcher(base_url: str, *, icon: bytes) -> FakeFetcher:
    icon_url = f"{base_url}/icon.png"
    return FakeFetcher(
        {
            base_url: _response(
                base_url,
                content=b'<html><head><link rel="icon" href="/icon.png"></head></html>',
                content_type="text/html",
            ),
            icon_url: _response(icon_url, content=icon, content_type="image/png"),
        }
    )


def _response(
    url: str,
    *,
    status_code: int = 200,
    content: bytes = b"",
    content_type: str = "text/plain",
) -> FetchResult:
    return FetchResult(
        url=url,
        status_code=status_code,
        content=content,
        text=content.decode(errors="replace"),
        headers={"content-type": content_type},
        fetched_at=datetime.now(UTC),
    )


def _image_bytes(width: int, height: int, image_format: str = "PNG") -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (width, height), color=(120, 30, 200))
    image.save(output, format=image_format)
    return output.getvalue()
