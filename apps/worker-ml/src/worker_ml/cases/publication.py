"""Serialized publication of reader-facing Case state."""

from __future__ import annotations

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
    Event,
)
from shkandal_vector_store.schemas import CaseVectorPayload
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

CASE_MUTATION_ADVISORY_LOCK = 7_214_801_901
ENTITY_MUTATION_ADVISORY_LOCK = 7_214_801_902
EVENT_MUTATION_ADVISORY_LOCK = 7_214_801_903


class CaseMutationBusyError(RuntimeError):
    """Another worker currently owns serialized Case mutation."""


async def try_case_mutation_lock(session: AsyncSession) -> bool:
    """Acquire the serialized Case mutation namespace for this transaction."""

    return await try_mutation_lock(session, CASE_MUTATION_ADVISORY_LOCK)


async def try_mutation_lock(session: AsyncSession, lock_id: int) -> bool:
    """Acquire one mutation namespace for this transaction."""

    return bool(await session.scalar(select(func.pg_try_advisory_xact_lock(lock_id))))


def case_vector_payload(case: Case) -> CaseVectorPayload:
    """Build the rebuildable vector payload for a Case."""

    return CaseVectorPayload(
        slug=case.slug,
        title_uk=case.title_uk,
        summary_uk=case.summary_uk,
        status=case.status,
        article_count=case.article_count,
        event_count=case.event_count,
        metadata=case.metadata_,
    )


async def rebuild_case_entities(
    session: AsyncSession,
    pairs: set[tuple[UUID, UUID]],
) -> None:
    """Rebuild materialized public Case-to-Entity links."""

    for case_id, entity_id in pairs:
        rows = (
            (
                await session.execute(
                    select(ArticleEntity.article_id)
                    .join(
                        ArticleEntityCase,
                        ArticleEntityCase.article_entity_id == ArticleEntity.id,
                    )
                    .join(Article, Article.id == ArticleEntity.article_id)
                    .where(
                        ArticleEntityCase.case_id == case_id,
                        ArticleEntity.entity_id == entity_id,
                    )
                    .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            await session.execute(
                delete(CaseEntity).where(
                    CaseEntity.case_id == case_id,
                    CaseEntity.entity_id == entity_id,
                )
            )
            continue
        await session.execute(
            insert(CaseEntity)
            .values(
                case_id=case_id,
                entity_id=entity_id,
                first_article_id=rows[0],
                mention_count=len(rows),
            )
            .on_conflict_do_update(
                index_elements=[CaseEntity.case_id, CaseEntity.entity_id],
                set_={"first_article_id": rows[0], "mention_count": len(rows)},
            )
        )


async def rebuild_case_events(
    session: AsyncSession,
    pairs: set[tuple[UUID, UUID]],
) -> None:
    """Rebuild materialized public Case-to-Event links and Event counts."""

    for case_id, event_id in pairs:
        rows = (
            (
                await session.execute(
                    select(ArticleEvent.article_id)
                    .join(
                        ArticleEventCase,
                        ArticleEventCase.article_event_id == ArticleEvent.id,
                    )
                    .join(Article, Article.id == ArticleEvent.article_id)
                    .where(
                        ArticleEventCase.case_id == case_id,
                        ArticleEvent.event_id == event_id,
                    )
                    .order_by(Article.published_at.asc().nulls_last(), Article.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            await session.execute(
                delete(CaseEvent).where(
                    CaseEvent.case_id == case_id,
                    CaseEvent.event_id == event_id,
                )
            )
            continue
        event = await session.get(Event, event_id)
        if event is None:
            continue
        await session.execute(
            insert(CaseEvent)
            .values(
                case_id=case_id,
                event_id=event_id,
                first_article_id=rows[0],
                event_year=event.event_year,
                event_month=event.event_month,
                event_day=event.event_day,
                supporting_article_count=len(rows),
            )
            .on_conflict_do_update(
                index_elements=[CaseEvent.case_id, CaseEvent.event_id],
                set_={
                    "first_article_id": rows[0],
                    "event_year": event.event_year,
                    "event_month": event.event_month,
                    "event_day": event.event_day,
                    "supporting_article_count": len(rows),
                },
            )
        )
    for case_id in {case_id for case_id, _ in pairs}:
        event_count = await session.scalar(
            select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case_id)
        )
        await session.execute(
            update(Case).where(Case.id == case_id).values(event_count=event_count or 0)
        )


async def refresh_case_counts(session: AsyncSession, case: Case) -> None:
    """Refresh reader-facing Case article and Event counts."""

    row = (
        await session.execute(
            select(
                func.count(CaseArticle.id),
                func.min(Article.published_at),
                func.max(Article.published_at),
            )
            .join(Article, Article.id == CaseArticle.article_id)
            .where(CaseArticle.case_id == case.id)
        )
    ).one()
    case.article_count = row[0]
    case.first_seen_at = row[1]
    case.last_updated_at = row[2]
    case.event_count = int(
        await session.scalar(
            select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id == case.id)
        )
        or 0
    )
