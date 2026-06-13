"""Discover website icons and synchronize frontend-owned Source logo assets."""

from __future__ import annotations

import io
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlparse
from uuid import UUID

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from shkandal_database.models import Source
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from worker_ingestion.transport import Fetcher

MAX_ICON_BYTES = 5 * 1024 * 1024
MAX_ICON_PIXELS = 2048 * 2048
LOGO_PATH_PREFIX = "/sources/"
_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ICON_REL_VALUES = frozenset({"icon", "shortcut", "apple-touch-icon"})


@dataclass(frozen=True)
class SourceLogoRow:
    """Database fields needed to synchronize one Source logo."""

    id: UUID
    slug: str
    base_url: str
    logo_path: str | None


@dataclass(frozen=True)
class NormalizedIcon:
    """A decoded website icon normalized to PNG."""

    url: str
    png: bytes
    width: int
    height: int


@dataclass(frozen=True)
class SourceLogoResult:
    """Outcome of synchronizing one Source logo."""

    source_slug: str
    status: str
    logo_path: str | None = None
    icon_url: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


class SourceLogoRepository(Protocol):
    """Persistence operations needed by the Source logo synchronizer."""

    async def list_sources(self, source_slug: str | None = None) -> tuple[SourceLogoRow, ...]:
        """Return all Sources, optionally limited to one slug."""

    async def update_logo_path(self, source_id: UUID, logo_path: str) -> None:
        """Persist one frontend-owned logo path."""


class SqlAlchemySourceLogoRepository:
    """PostgreSQL Source logo persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def list_sources(self, source_slug: str | None = None) -> tuple[SourceLogoRow, ...]:
        statement = select(Source.id, Source.slug, Source.base_url, Source.logo_path).order_by(
            Source.slug
        )
        if source_slug is not None:
            statement = statement.where(Source.slug == source_slug)

        async with self.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            SourceLogoRow(
                id=row.id,
                slug=row.slug,
                base_url=row.base_url,
                logo_path=row.logo_path,
            )
            for row in rows
        )

    async def update_logo_path(self, source_id: UUID, logo_path: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Source).where(Source.id == source_id).values(logo_path=logo_path)
            )
            await session.commit()


async def sync_source_logos(
    repository: SourceLogoRepository,
    fetcher: Fetcher,
    *,
    output_dir: Path,
    apply: bool,
    source_slug: str | None = None,
) -> tuple[SourceLogoResult, ...]:
    """Discover and optionally persist normalized website icons for Sources."""

    sources = await repository.list_sources(source_slug)
    results: list[SourceLogoResult] = []
    for source in sources:
        results.append(
            await _sync_source_logo(
                source,
                repository,
                fetcher,
                output_dir=output_dir,
                apply=apply,
            )
        )
    return tuple(results)


async def _sync_source_logo(
    source: SourceLogoRow,
    repository: SourceLogoRepository,
    fetcher: Fetcher,
    *,
    output_dir: Path,
    apply: bool,
) -> SourceLogoResult:
    try:
        if not _SAFE_SLUG.fullmatch(source.slug):
            raise ValueError("Source slug is not safe for use as an asset filename.")

        page = await fetcher.fetch(source.base_url)
        if not page.ok:
            raise ValueError(_fetch_error("source page", page.status_code, page.error))

        candidates = discover_icon_urls(page.text, page.url)
        icon = await select_largest_raster_icon(candidates, fetcher)
        if icon is None:
            raise ValueError("No usable raster icon was discovered.")

        logo_path = f"{LOGO_PATH_PREFIX}{source.slug}.png"
        if apply:
            target = output_dir / f"{source.slug}.png"
            previous = target.read_bytes() if target.exists() else None
            _write_atomic(target, icon.png)
            try:
                await repository.update_logo_path(source.id, logo_path)
            except Exception:
                _restore_file(target, previous)
                raise

        return SourceLogoResult(
            source_slug=source.slug,
            status="updated" if apply else "would_update",
            logo_path=logo_path,
            icon_url=icon.url,
            width=icon.width,
            height=icon.height,
        )
    except Exception as exc:
        return SourceLogoResult(
            source_slug=source.slug,
            status="failed",
            logo_path=source.logo_path,
            error=str(exc),
        )


def discover_icon_urls(html: str, page_url: str) -> tuple[str, ...]:
    """Return ordered website icon URLs plus the conventional favicon fallback."""

    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for link in soup.find_all("link"):
        href = link.get("href")
        rel_value = link.get("rel")
        if not isinstance(href, str) or rel_value is None:
            continue
        rel_values = (rel_value,) if isinstance(rel_value, str) else rel_value
        rel = {str(value).lower() for value in rel_values}
        if not (rel & _ICON_REL_VALUES):
            continue
        url = urljoin(page_url, href)
        if not _looks_like_svg(url):
            urls.append(url)

    urls.append(urljoin(page_url, "/favicon.ico"))
    return tuple(dict.fromkeys(urls))


async def select_largest_raster_icon(
    candidates: tuple[str, ...],
    fetcher: Fetcher,
) -> NormalizedIcon | None:
    """Fetch candidates and return the largest decodable raster icon."""

    best: NormalizedIcon | None = None
    for url in candidates:
        result = await fetcher.fetch(url)
        content_type = result.headers.get("content-type", "").lower()
        if (
            not result.ok
            or not result.content
            or len(result.content) > MAX_ICON_BYTES
            or "svg" in content_type
        ):
            continue
        try:
            icon = normalize_raster_icon(result.content, result.url)
        except (OSError, UnidentifiedImageError, ValueError):
            continue
        if best is None or icon.width * icon.height > best.width * best.height:
            best = icon
    return best


def normalize_raster_icon(content: bytes, url: str) -> NormalizedIcon:
    """Decode raster image bytes and return a normalized RGBA PNG."""

    with Image.open(io.BytesIO(content)) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("Icon has invalid dimensions.")
        if width * height > MAX_ICON_PIXELS:
            raise ValueError("Icon dimensions exceed the supported pixel limit.")
        image.load()
        normalized = image.convert("RGBA")
        output = io.BytesIO()
        normalized.save(output, format="PNG", optimize=True)
    return NormalizedIcon(url=url, png=output.getvalue(), width=width, height=height)


def _looks_like_svg(url: str) -> bool:
    return urlparse(url).path.lower().endswith(".svg")


def _fetch_error(label: str, status_code: int, error: str | None) -> str:
    detail = error or f"HTTP {status_code}"
    return f"Could not fetch {label}: {detail}"


def _write_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(content)
        temporary_path.chmod(0o644)
        temporary_path.replace(target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _restore_file(target: Path, previous: bytes | None) -> None:
    if previous is None:
        target.unlink(missing_ok=True)
        return
    _write_atomic(target, previous)
