"""Persistence contracts and PostgreSQL implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from shkandal_database.models import Article, Source
from sqlalchemy.dialects.postgresql import insert
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


class ArticleRepository(Protocol):
    async def ensure_source(self, source: SourceInput) -> UUID:
        """Create or return a source id."""

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
