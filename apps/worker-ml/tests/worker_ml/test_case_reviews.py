"""Tests for automatic Case public-interest and duplicate reviews."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from shkandal_database.models import Case
from worker_ml.cases.reviews import _compact_cards, _merge_order
from worker_ml.llm.contracts import (
    CaseDuplicateAuditOutput,
    CasePublicInterestAuditOutput,
)
from worker_ml.llm.contracts.cases import (
    CaseDuplicateDiagnosis,
    CasePublicInterestDiagnosis,
)


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
    assert CasePublicInterestAuditOutput(
        diagnosis=CasePublicInterestDiagnosis(
            concrete_story_core_uk=None,
            public_interest_anchor_uk=None,
            durability_signal_uk=None,
            hide_signals_uk=[],
        ),
        reason_uk="Недостатньо доказів.",
        outcome="inconclusive",
    )
    assert CaseDuplicateAuditOutput(
        diagnosis=CaseDuplicateDiagnosis(
            case_a_core_uk=None,
            case_b_core_uk=None,
            shared_specific_core_uk=None,
            relation_anchor_uk=None,
            only_broad_overlap_uk=None,
            merge_blockers_uk=[],
        ),
        reason_uk="Недостатньо доказів.",
        outcome="inconclusive",
    )


def test_public_interest_keep_requires_non_speculative_durable_signal_without_hide_flags() -> None:
    with pytest.raises(ValueError, match="hide signals"):
        CasePublicInterestAuditOutput(
            diagnosis=CasePublicInterestDiagnosis(
                concrete_story_core_uk="Побутове вбивство після тривалого конфлікту.",
                public_interest_anchor_uk="Домашнє насильство.",
                durability_signal_uk="Триває судовий процес.",
                hide_signals_uk=["Побутовий конфлікт"],
            ),
            reason_uk="Тема насильства нібито важлива.",
            outcome="keep",
        )

    with pytest.raises(ValueError, match="observed durability signal"):
        CasePublicInterestAuditOutput(
            diagnosis=CasePublicInterestDiagnosis(
                concrete_story_core_uk="Локальна кримінальна історія.",
                public_interest_anchor_uk="Реакція місцевої громади.",
                durability_signal_uk="Можливе подальше розслідування.",
                hide_signals_uk=[],
            ),
            reason_uk="Може отримати розвиток.",
            outcome="keep",
        )
