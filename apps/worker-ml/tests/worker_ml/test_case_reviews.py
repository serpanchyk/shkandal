"""Tests for automatic Case public-interest and duplicate reviews."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from shkandal_database.models import Case
from worker_ml.cases.reviews import _compact_cards, _merge_order
from worker_ml.llm.contracts import CaseDuplicateAuditOutput, CasePublicInterestAuditOutput


def _case(*, articles: int, created_at: datetime) -> Case:
    return Case(
        id=uuid4(),
        slug=f"case-{uuid4().hex}",
        title_uk="Справа",
        summary_uk="Опис.",
        status="active",
        article_count=articles,
        created_at=created_at,
    )


def test_merge_survivor_has_most_evidence() -> None:
    now = datetime.now(UTC)
    smaller = _case(articles=2, created_at=now - timedelta(days=1))
    larger = _case(articles=5, created_at=now)

    assert _merge_order(smaller, larger) == (larger, smaller)


def test_merge_survivor_tie_breaks_by_oldest_case() -> None:
    now = datetime.now(UTC)
    older = _case(articles=3, created_at=now - timedelta(days=1))
    newer = _case(articles=3, created_at=now)

    assert _merge_order(newer, older) == (older, newer)


def test_review_cards_keep_only_bounded_factual_context() -> None:
    cards = [
        {
            "article_id": "article-a",
            "published_at": "2026-06-15",
            "title_uk": "Назва",
            "summary_uk": "Опис",
            "entities": [{"name": "Не потрібно"}],
        }
    ]

    assert _compact_cards(cards) == [
        {
            "article_id": "article-a",
            "published_at": "2026-06-15",
            "title_uk": "Назва",
            "summary_uk": "Опис",
        }
    ]


def test_specialized_audit_contracts_allow_inconclusive_without_mutation() -> None:
    assert CasePublicInterestAuditOutput(reason_uk="Недостатньо доказів.", outcome="inconclusive")
    assert CaseDuplicateAuditOutput(reason_uk="Недостатньо доказів.", outcome="inconclusive")
