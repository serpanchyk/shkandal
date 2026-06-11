"""PostgreSQL queries for public reader pages."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import Protocol
from uuid import UUID

from shkandal_database.models import (
    Article,
    ArticleEntity,
    ArticleEntityCase,
    ArticleEvent,
    ArticleEventCase,
    Case,
    CaseArticle,
    CaseEntity,
    CaseEvent,
    CaseRelation,
    CaseViewCounter,
    Entity,
    Event,
    Source,
)
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from shkandal_backend.schemas import (
    ArticlePreview,
    CaseFeedItem,
    CaseFeedPage,
    CasePage,
    CaseSort,
    EntityPage,
    EntityPreview,
    EventPreview,
    RelatedCasePreview,
    SitemapEntry,
    SourcePreview,
)

PAGE_SIZE = 20
DISCLAIMER_UK = (
    "Сторінка автоматично зібрана з відкритих джерел. Події та згадані особи й "
    "організації мають посилання на матеріали, на основі яких їх додано."
)


class PublicRepository(Protocol):
    async def case_feed(self, *, sort: CaseSort, query: str | None, page: int) -> CaseFeedPage: ...

    async def case_page(self, slug: str) -> CasePage | None: ...

    async def entity_page(self, slug: str) -> EntityPage | None: ...

    async def increment_case_view(self, slug: str) -> int | None: ...

    async def sitemap_entries(self) -> list[SitemapEntry]: ...


class SqlAlchemyPublicRepository:
    """Compose reader-facing views from current PostgreSQL rows."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def case_feed(self, *, sort: CaseSort, query: str | None, page: int) -> CaseFeedPage:
        async with self._session_factory() as session:
            views = (
                select(
                    CaseViewCounter.case_id.label("case_id"),
                    func.coalesce(func.sum(CaseViewCounter.view_count), 0).label("view_count"),
                )
                .group_by(CaseViewCounter.case_id)
                .subquery()
            )
            trending = (
                select(
                    CaseArticle.case_id.label("case_id"),
                    func.count(CaseArticle.id).label("trending_count"),
                )
                .join(Article, Article.id == CaseArticle.article_id)
                .where(Article.published_at >= datetime.now(UTC) - timedelta(days=7))
                .group_by(CaseArticle.case_id)
                .subquery()
            )
            latest_image = (
                select(Article.remote_image_url)
                .join(CaseArticle, CaseArticle.article_id == Article.id)
                .where(
                    CaseArticle.case_id == Case.id,
                    Article.remote_image_url.is_not(None),
                )
                .order_by(Article.published_at.desc().nulls_last(), Article.created_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            view_count = func.coalesce(views.c.view_count, 0)
            trending_count = func.coalesce(trending.c.trending_count, 0)
            statement = (
                select(Case, view_count.label("view_count"), latest_image.label("image_url"))
                .outerjoin(views, views.c.case_id == Case.id)
                .outerjoin(trending, trending.c.case_id == Case.id)
                .where(_public_case_predicate())
            )
            if query:
                similarity = func.similarity(Case.title_uk, query)
                statement = statement.where(similarity > 0.15).order_by(
                    similarity.desc(), Case.last_updated_at.desc().nulls_last(), Case.id
                )
            elif sort == "latest":
                statement = statement.order_by(Case.last_updated_at.desc().nulls_last(), Case.id)
            elif sort == "newest":
                statement = statement.order_by(
                    Case.created_at.desc(), Case.last_updated_at.desc().nulls_last(), Case.id
                )
            elif sort == "popular":
                statement = statement.order_by(
                    view_count.desc(), Case.last_updated_at.desc().nulls_last(), Case.id
                )
            elif sort == "biggest":
                statement = statement.order_by(
                    Case.article_count.desc(), Case.last_updated_at.desc().nulls_last(), Case.id
                )
            else:
                statement = statement.order_by(
                    trending_count.desc(), Case.last_updated_at.desc().nulls_last(), Case.id
                )

            total = await session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            rows = (
                await session.execute(statement.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))
            ).all()
            return CaseFeedPage(
                items=[
                    CaseFeedItem(
                        slug=case_row.slug,
                        title_uk=case_row.title_uk,
                        summary_uk=case_row.summary_uk or "",
                        latest_article_at=case_row.last_updated_at,
                        article_count=case_row.article_count,
                        view_count=int(row_view_count),
                        image_url=image_url,
                    )
                    for case_row, row_view_count, image_url in rows
                ],
                sort=sort,
                query=query,
                page=page,
                page_size=PAGE_SIZE,
                total_items=total or 0,
                total_pages=ceil((total or 0) / PAGE_SIZE),
            )

    async def case_page(self, slug: str) -> CasePage | None:
        async with self._session_factory() as session:
            case_row = await session.scalar(select(Case).where(Case.slug == slug))
            if case_row is None or not await _is_public_case(session, case_row):
                return None
            articles = await _case_articles(session, case_row.id)
            sources = await _case_sources(session, case_row.id)
            entities = await _case_entities(session, case_row.id)
            events = await _case_events(session, case_row.id)
            related_cases = await _related_cases(session, case_row.id)
            view_count = await _case_view_count(session, case_row.id)
            return CasePage(
                slug=case_row.slug,
                title_uk=case_row.title_uk,
                summary_uk=case_row.summary_uk or "",
                latest_article_at=case_row.last_updated_at,
                article_count=case_row.article_count,
                event_count=case_row.event_count,
                view_count=view_count,
                sources=sources,
                entities=entities,
                events=events,
                articles=articles,
                related_cases=related_cases,
                disclaimer_uk=DISCLAIMER_UK,
            )

    async def entity_page(self, slug: str) -> EntityPage | None:
        async with self._session_factory() as session:
            entity = await session.scalar(select(Entity).where(Entity.slug == slug))
            if entity is None or not entity.description_uk:
                return None
            case_rows = (
                await session.scalars(
                    select(Case)
                    .join(CaseEntity, CaseEntity.case_id == Case.id)
                    .where(CaseEntity.entity_id == entity.id, _public_case_predicate())
                    .order_by(Case.last_updated_at.desc().nulls_last())
                )
            ).all()
            article_rows = (
                await session.execute(
                    select(Article, Source)
                    .join(Source, Source.id == Article.source_id)
                    .join(ArticleEntity, ArticleEntity.article_id == Article.id)
                    .join(
                        ArticleEntityCase,
                        ArticleEntityCase.article_entity_id == ArticleEntity.id,
                    )
                    .join(Case, Case.id == ArticleEntityCase.case_id)
                    .where(ArticleEntity.entity_id == entity.id, _public_case_predicate())
                    .distinct()
                    .order_by(Article.published_at.desc().nulls_last(), Article.created_at.desc())
                )
            ).all()
            if not case_rows or not article_rows:
                return None
            return EntityPage(
                slug=entity.slug,
                canonical_name_uk=entity.canonical_name_uk,
                entity_type=entity.entity_type,
                aliases=entity.aliases,
                description_uk=entity.description_uk,
                cases=[_related_case(case_row) for case_row in case_rows],
                articles=[_article_preview(article, source) for article, source in article_rows],
            )

    async def increment_case_view(self, slug: str) -> int | None:
        async with self._session_factory() as session:
            case_id = await session.scalar(
                select(Case.id).where(Case.slug == slug, _public_case_predicate())
            )
            if case_id is None:
                return None
            await session.execute(
                insert(CaseViewCounter)
                .values(case_id=case_id, counter_date=date.today(), view_count=1)
                .on_conflict_do_update(
                    index_elements=[CaseViewCounter.case_id, CaseViewCounter.counter_date],
                    set_={"view_count": CaseViewCounter.view_count + 1},
                )
            )
            await session.commit()
            return await _case_view_count(session, case_id)

    async def sitemap_entries(self) -> list[SitemapEntry]:
        async with self._session_factory() as session:
            cases = (
                await session.execute(
                    select(Case.slug, Case.updated_at).where(_public_case_predicate())
                )
            ).all()
            entities = (
                await session.execute(
                    select(Entity.slug, Entity.updated_at)
                    .join(CaseEntity, CaseEntity.entity_id == Entity.id)
                    .join(Case, Case.id == CaseEntity.case_id)
                    .where(Entity.description_uk.is_not(None), _public_case_predicate())
                    .distinct()
                )
            ).all()
            return [
                *[
                    SitemapEntry(path=f"/cases/{slug}", updated_at=updated_at)
                    for slug, updated_at in cases
                ],
                *[
                    SitemapEntry(path=f"/entities/{slug}", updated_at=updated_at)
                    for slug, updated_at in entities
                ],
            ]


def _public_case_predicate() -> ColumnElement[bool]:
    return and_(
        Case.status == "active",
        Case.summary_uk.is_not(None),
        func.length(func.trim(Case.summary_uk)) > 0,
        select(CaseArticle.id).where(CaseArticle.case_id == Case.id).exists(),
    )


async def _is_public_case(session: AsyncSession, case_row: Case) -> bool:
    return bool(
        await session.scalar(select(_public_case_predicate()).where(Case.id == case_row.id))
    )


def _source_preview(source: Source, article_count: int | None = None) -> SourcePreview:
    return SourcePreview(
        slug=source.slug,
        name=source.name,
        source_type=source.source_type,
        homepage_url=source.base_url,
        logo_path=source.logo_path,
        article_count=article_count,
    )


def _article_preview(article: Article, source: Source) -> ArticlePreview:
    return ArticlePreview(
        title=article.title or article.url,
        url=article.url,
        published_at=article.published_at,
        image_url=article.remote_image_url,
        source=_source_preview(source),
    )


async def _case_articles(session: AsyncSession, case_id: UUID) -> list[ArticlePreview]:
    rows = (
        await session.execute(
            select(Article, Source)
            .join(Source, Source.id == Article.source_id)
            .join(CaseArticle, CaseArticle.article_id == Article.id)
            .where(CaseArticle.case_id == case_id)
            .order_by(Article.published_at.desc().nulls_last(), Article.created_at.desc())
        )
    ).all()
    return [_article_preview(article, source) for article, source in rows]


async def _case_sources(session: AsyncSession, case_id: UUID) -> list[SourcePreview]:
    rows = (
        await session.execute(
            select(Source, func.count(CaseArticle.id))
            .join(Article, Article.source_id == Source.id)
            .join(CaseArticle, CaseArticle.article_id == Article.id)
            .where(CaseArticle.case_id == case_id)
            .group_by(Source.id)
            .order_by(func.count(CaseArticle.id).desc(), Source.name)
        )
    ).all()
    return [_source_preview(source, int(count)) for source, count in rows]


async def _case_entities(session: AsyncSession, case_id: UUID) -> list[EntityPreview]:
    rows = (
        await session.execute(
            select(Entity, CaseEntity.mention_count)
            .join(CaseEntity, CaseEntity.entity_id == Entity.id)
            .where(CaseEntity.case_id == case_id)
            .order_by(CaseEntity.mention_count.desc(), Entity.canonical_name_uk)
        )
    ).all()
    return [
        EntityPreview(
            slug=entity.slug,
            canonical_name_uk=entity.canonical_name_uk,
            entity_type=entity.entity_type,
            description_uk=entity.description_uk,
            mention_count=mention_count,
        )
        for entity, mention_count in rows
    ]


async def _case_events(session: AsyncSession, case_id: UUID) -> list[EventPreview]:
    rows = (
        (
            await session.execute(
                select(Event)
                .join(CaseEvent, CaseEvent.event_id == Event.id)
                .where(CaseEvent.case_id == case_id)
                .order_by(
                    case((Event.event_year.is_(None), 1), else_=0),
                    Event.event_year,
                    Event.event_month,
                    Event.event_day,
                    Event.created_at,
                )
            )
        )
        .scalars()
        .all()
    )
    result: list[EventPreview] = []
    for event in rows:
        article_rows = (
            await session.execute(
                select(Article, Source)
                .join(Source, Source.id == Article.source_id)
                .join(ArticleEvent, ArticleEvent.article_id == Article.id)
                .join(ArticleEventCase, ArticleEventCase.article_event_id == ArticleEvent.id)
                .where(ArticleEvent.event_id == event.id, ArticleEventCase.case_id == case_id)
                .order_by(Article.published_at.desc().nulls_last())
            )
        ).all()
        result.append(
            EventPreview(
                slug=event.slug,
                title_uk=event.title_uk,
                description_uk=event.description_uk,
                event_year=event.event_year,
                event_month=event.event_month,
                event_day=event.event_day,
                event_date_precision=event.event_date_precision,
                location_uk=event.location_uk,
                supporting_articles=[
                    _article_preview(article, source) for article, source in article_rows
                ],
            )
        )
    return result


async def _related_cases(session: AsyncSession, case_id: UUID) -> list[RelatedCasePreview]:
    other = aliased(Case)
    related_id = case(
        (CaseRelation.case_a_id == case_id, CaseRelation.case_b_id),
        else_=CaseRelation.case_a_id,
    )
    rows = (
        await session.scalars(
            select(other)
            .join(CaseRelation, other.id == related_id)
            .where(
                or_(CaseRelation.case_a_id == case_id, CaseRelation.case_b_id == case_id),
                CaseRelation.relation_type == "related",
                other.status == "active",
                other.summary_uk.is_not(None),
            )
            .order_by(other.last_updated_at.desc().nulls_last())
        )
    ).all()
    return [_related_case(row) for row in rows]


def _related_case(case_row: Case) -> RelatedCasePreview:
    return RelatedCasePreview(
        slug=case_row.slug,
        title_uk=case_row.title_uk,
        summary_uk=case_row.summary_uk or "",
    )


async def _case_view_count(session: AsyncSession, case_id: UUID) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(CaseViewCounter.view_count), 0)).where(
            CaseViewCounter.case_id == case_id
        )
    )
    return int(value or 0)
