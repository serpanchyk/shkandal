"""Persistence contracts and PostgreSQL implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from shkandal_database.models import Article, Source
from sqlalchemy import cast, select, tuple_, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func


@dataclass(frozen=True)
class SourceInput:
    slug: str
    name: str
    source_type: str
    base_url: str
    language: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ArticleInput:
    source_id: UUID
    url: str
    identity_url: str
    title: str | None
    lead: str | None
    published_at: datetime | None
    fetched_at: datetime | None
    source_language: str | None
    raw_html: str | None
    extracted_text: str | None
    remote_image_url: str | None
    remote_image_metadata: dict[str, Any]
    source_metadata: dict[str, Any]


@dataclass(frozen=True)
class PublishedAtRepairRow:
    article_id: UUID
    created_at: datetime
    source_slug: str
    url: str
    raw_html: str


class ArticleRepository(Protocol):
    async def ensure_source(self, source: SourceInput) -> UUID:
        """Create or return a source id."""

    async def existing_identity_urls(self, identity_urls: set[str]) -> set[str]:
        """Return article identity URLs already stored."""

    async def upsert_article(self, article: ArticleInput) -> None:
        """Insert or update one article by identity URL."""


class SqlAlchemyArticleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def ensure_source(self, source: SourceInput) -> UUID:
        async with self.session_factory() as session:
            statement = (
                insert(Source)
                .values(
                    slug=source.slug,
                    name=source.name,
                    source_type=source.source_type,
                    base_url=source.base_url,
                    language=source.language,
                    metadata_=source.metadata,
                )
                .on_conflict_do_update(
                    index_elements=[Source.slug],
                    set_={
                        "name": source.name,
                        "source_type": source.source_type,
                        "base_url": source.base_url,
                        "language": source.language,
                        "metadata": source.metadata,
                    },
                )
                .returning(Source.id)
            )
            source_id = (await session.execute(statement)).scalar_one()
            await session.commit()
            return source_id

    async def existing_identity_urls(self, identity_urls: set[str]) -> set[str]:
        if not identity_urls:
            return set()

        existing_identity_urls: set[str] = set()
        async with self.session_factory() as session:
            for chunk in _chunks(tuple(identity_urls), size=10_000):
                statement = select(Article.identity_url).where(Article.identity_url.in_(chunk))
                result = await session.execute(statement)
                existing_identity_urls.update(result.scalars())
        return existing_identity_urls

    async def fetch_articles_missing_published_at_batch(
        self,
        *,
        source_slug: str | None = None,
        limit: int | None = None,
        after_created_at: datetime | None = None,
        after_article_id: UUID | None = None,
    ) -> list[PublishedAtRepairRow]:
        async with self.session_factory() as session:
            statement = (
                select(Article.id, Article.created_at, Source.slug, Article.url, Article.raw_html)
                .join(Source, Source.id == Article.source_id)
                .where(
                    Article.published_at.is_(None),
                    Article.raw_html.is_not(None),
                    Article.raw_html != "",
                )
                .order_by(Article.created_at, Article.id)
            )
            if source_slug:
                statement = statement.where(Source.slug == source_slug)
            if after_created_at is not None and after_article_id is not None:
                statement = statement.where(
                    tuple_(Article.created_at, Article.id) > (after_created_at, after_article_id)
                )
            if limit is not None:
                statement = statement.limit(limit)

            rows = (await session.execute(statement)).all()
            return [
                PublishedAtRepairRow(
                    article_id=row.id,
                    created_at=row.created_at,
                    source_slug=row.slug,
                    url=row.url,
                    raw_html=row.raw_html,
                )
                for row in rows
            ]

    async def update_article_published_at(self, article_id: UUID, published_at: datetime) -> None:
        async with self.session_factory() as session:
            statement = (
                update(Article)
                .where(Article.id == article_id, Article.published_at.is_(None))
                .values(
                    published_at=published_at,
                    source_metadata=Article.source_metadata.op("||")(
                        cast({"published_at_repaired": True}, JSONB)
                    ),
                )
            )
            await session.execute(statement)
            await session.commit()

    async def upsert_article(self, article: ArticleInput) -> None:
        async with self.session_factory() as session:
            statement = insert(Article).values(
                source_id=article.source_id,
                url=article.url,
                identity_url=article.identity_url,
                title=article.title,
                lead=article.lead,
                published_at=article.published_at,
                fetched_at=article.fetched_at,
                source_language=article.source_language,
                raw_html=article.raw_html,
                extracted_text=article.extracted_text,
                remote_image_url=article.remote_image_url,
                remote_image_metadata=article.remote_image_metadata,
                source_metadata=article.source_metadata,
            )
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                constraint="uq_articles_identity_url",
                set_={
                    "title": func.coalesce(func.nullif(excluded.title, ""), Article.title),
                    "lead": func.coalesce(func.nullif(excluded.lead, ""), Article.lead),
                    "published_at": func.coalesce(excluded.published_at, Article.published_at),
                    "fetched_at": func.coalesce(excluded.fetched_at, Article.fetched_at),
                    "source_language": func.coalesce(
                        func.nullif(excluded.source_language, ""),
                        Article.source_language,
                    ),
                    "raw_html": func.coalesce(
                        func.nullif(excluded.raw_html, ""),
                        Article.raw_html,
                    ),
                    "extracted_text": func.coalesce(
                        func.nullif(excluded.extracted_text, ""),
                        Article.extracted_text,
                    ),
                    "remote_image_url": func.coalesce(
                        func.nullif(excluded.remote_image_url, ""),
                        Article.remote_image_url,
                    ),
                    "remote_image_metadata": Article.remote_image_metadata.op("||")(
                        excluded.remote_image_metadata
                    ),
                    "source_metadata": Article.source_metadata.op("||")(excluded.source_metadata),
                },
            )
            await session.execute(statement)
            await session.commit()


def _chunks(values: tuple[str, ...], *, size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(values[index : index + size] for index in range(0, len(values), size))
