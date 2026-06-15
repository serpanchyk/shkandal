"""Tests for LLM output contracts."""

import pytest
from pydantic import ValidationError
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseCoherenceAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
)


def test_case_coherence_audit_accepts_overlapping_article_assignments() -> None:
    output = CaseCoherenceAuditOutput.model_validate(
        {
            "outcome": "split",
            "reason_uk": "Змішані дві справи.",
            "stories": [
                {
                    "story_ref": "original",
                    "title_uk": "Перша справа",
                    "summary_uk": "Опис першої справи.",
                    "article_ids": ["article-a", "article-bridge"],
                    "reason_uk": "Домінантна історія.",
                },
                {
                    "story_ref": "story_second",
                    "title_uk": "Друга справа",
                    "summary_uk": "Опис другої справи.",
                    "article_ids": ["article-b", "article-bridge"],
                    "reason_uk": "Окрема історія.",
                },
            ],
        }
    )

    assert output.outcome == "split"


def test_case_coherence_audit_rejects_split_without_original_story() -> None:
    with pytest.raises(ValueError, match="exactly one original"):
        CaseCoherenceAuditOutput.model_validate(
            {
                "outcome": "split",
                "reason_uk": "Змішані справи.",
                "stories": [
                    {
                        "story_ref": "story_a",
                        "title_uk": "Перша",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-a"],
                        "reason_uk": "Причина.",
                    },
                    {
                        "story_ref": "story_b",
                        "title_uk": "Друга",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-b"],
                        "reason_uk": "Причина.",
                    },
                ],
            }
        )


def test_article_card_contract_accepts_representative_json() -> None:
    output = ArticleCardOutput.model_validate(
        {
            "title_uk": "Справа про закупівлі у міській раді",
            "summary_uk": "Стаття описує підозру щодо закупівель.",
            "is_case_candidate": True,
            "noise_reason": None,
            "main_event_title_uk": "НАБУ повідомило про підозру",
            "entities": [
                {
                    "provisional_ref": "entity_city_council",
                    "name_uk": "Міська рада",
                    "entity_type": "institution",
                    "aliases": ["рада"],
                    "description_uk": "Орган місцевого самоврядування.",
                }
            ],
            "events": [
                {
                    "provisional_ref": "event_suspicion",
                    "title_uk": "НАБУ повідомило про підозру",
                    "description_uk": "Детективи повідомили посадовцю про підозру.",
                    "event_date": "2026-06-05",
                    "event_date_precision": "day",
                    "location_uk": "Київ",
                }
            ],
            "case_signature_terms": ["міська рада", "закупівлі", "підозра"],
        }
    )

    assert output.entities[0].entity_type == "institution"
    assert output.events[0].event_date_precision == "day"


@pytest.mark.parametrize(
    "noise_reason",
    [
        "culture",
        "diplomacy",
        "policy_law",
        "routine_regulatory",
        "routine_crime",
        "foreign_no_ukraine_nexus",
    ],
)
def test_article_card_contract_accepts_non_case_card_without_case_signals(
    noise_reason: str,
) -> None:
    output = ArticleCardOutput.model_validate(
        {
            "title_uk": "Огляд культурної виставки",
            "summary_uk": "Матеріал розповідає про мистецьку виставку.",
            "is_case_candidate": False,
            "noise_reason": noise_reason,
            "main_event_title_uk": None,
            "entities": [],
            "events": [],
            "case_signature_terms": [],
        }
    )

    assert output.noise_reason == noise_reason


@pytest.mark.parametrize(
    "changes",
    [
        {"noise_reason": "culture"},
        {"main_event_title_uk": None},
        {"events": []},
        {"case_signature_terms": []},
        {"events": [{"title_uk": "Подія", "description_uk": "Опис"}] * 4},
        {
            "entities": [
                {
                    "name_uk": f"Сутність {index}",
                    "entity_type": "organization",
                    "description_uk": "Роль у статті.",
                }
                for index in range(9)
            ]
        },
    ],
)
def test_article_card_contract_rejects_invalid_case_shape(changes: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "title_uk": "Справа",
        "summary_uk": "Опис справи.",
        "is_case_candidate": True,
        "noise_reason": None,
        "main_event_title_uk": "НБУ оштрафував банк",
        "entities": [],
        "events": [
            {
                "title_uk": "НБУ оштрафував банк",
                "description_uk": "Регулятор наклав штраф.",
            }
        ],
        "case_signature_terms": ["НБУ", "штраф"],
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        ArticleCardOutput.model_validate(payload)


def test_article_card_contract_rejects_case_signals_for_non_case_card() -> None:
    with pytest.raises(ValidationError):
        ArticleCardOutput.model_validate(
            {
                "title_uk": "Рейтинг",
                "summary_uk": "Матеріал містить рейтинг.",
                "is_case_candidate": False,
                "noise_reason": "ranking",
                "main_event_title_uk": None,
                "entities": [],
                "events": [],
                "case_signature_terms": ["рейтинг"],
            }
        )


@pytest.mark.parametrize(
    "rejection_reason",
    [
        "not_an_entity",
        "insufficient_identity",
        "not_stable_actor",
        "not_material_to_case",
        "background_or_related_material",
        "location_only",
        "role_without_name",
        "unsupported_by_context",
    ],
)
def test_entity_resolution_contract_accepts_strict_rejection_reasons(
    rejection_reason: str,
) -> None:
    output = EntityResolutionOutput.model_validate(
        {
            "entities": [
                {
                    "provisional_ref": "entity_rejected",
                    "reason_uk": "Сутність не можна додати до глобального графа.",
                    "action": "reject",
                    "confidence": 0.9,
                    "rejection_reason": rejection_reason,
                }
            ]
        }
    )

    assert output.entities[0].rejection_reason == rejection_reason


@pytest.mark.parametrize(
    "alias",
    [
        "орган, який викрив схему",
        "колишній посадовець",
        "підозрюваний у справі",
        "переможець тендеру",
    ],
)
def test_entity_resolution_contract_rejects_role_aliases(alias: str) -> None:
    with pytest.raises(ValidationError, match="aliases cannot be role descriptions"):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_company",
                        "reason_uk": "Компанія матеріально важлива для справи.",
                        "action": "create_new",
                        "new_canonical_name_uk": "ТОВ «Приклад»",
                        "entity_type": "company",
                        "aliases": [alias],
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Предмет справи."}
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "description_uk",
    [
        "Орган, який викрив схему.",
        "Суд, який продовжив обов'язки.",
        "Компанія, яка фігурує у справі.",
        "Країна, де затримали особу.",
    ],
)
def test_entity_resolution_contract_rejects_case_role_descriptions(
    description_uk: str,
) -> None:
    with pytest.raises(
        ValidationError, match="description_uk cannot describe a case-specific role"
    ):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_company",
                        "reason_uk": "Компанія матеріально важлива для справи.",
                        "action": "create_new",
                        "new_canonical_name_uk": "ТОВ «Приклад»",
                        "entity_type": "company",
                        "description_uk": description_uk,
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Предмет справи."}
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    ("event_date", "precision"),
    [
        ("2026-06", "day"),
        ("2026-06-05", "month"),
        ("2026", "unknown"),
        (None, "year"),
    ],
)
def test_article_card_contract_rejects_inconsistent_event_dates(
    event_date: str | None,
    precision: str,
) -> None:
    with pytest.raises(ValidationError):
        ArticleCardOutput.model_validate(
            {
                "title_uk": "Справа",
                "summary_uk": "Опис справи.",
                "is_case_candidate": True,
                "noise_reason": None,
                "main_event_title_uk": "Суд ухвалив рішення",
                "entities": [],
                "events": [
                    {
                        "title_uk": "Суд ухвалив рішення",
                        "description_uk": "Суд розглянув справу.",
                        "event_date": event_date,
                        "event_date_precision": precision,
                    }
                ],
                "case_signature_terms": ["суд", "рішення"],
            }
        )


def test_case_resolution_contract_accepts_explicit_rejection() -> None:
    output = CaseResolutionOutput.model_validate(
        {
            "decision_reason_uk": "Немає конкретної відстежуваної справи.",
            "outcome": "rejected",
            "existing_case_links": [],
            "new_cases": [],
            "case_relations": [],
        }
    )

    assert output.outcome == "rejected"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "decision_reason_uk": "Немає дії.",
            "outcome": "resolved",
            "existing_case_links": [],
            "new_cases": [],
            "case_relations": [],
        },
        {
            "decision_reason_uk": "Помилкова дія.",
            "outcome": "rejected",
            "existing_case_links": [],
            "new_cases": [
                {
                    "new_case_ref": "new_case",
                    "title_uk": "Нова справа",
                    "summary_uk": "Опис.",
                    "link_reason_uk": "Причина.",
                    "confidence": 0.8,
                }
            ],
            "case_relations": [],
        },
    ],
)
def test_case_resolution_contract_rejects_inconsistent_outcome(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CaseResolutionOutput.model_validate(payload)


def test_other_resolution_contracts_accept_empty_decisions() -> None:
    assert EntityResolutionOutput.model_validate({"entities": []})
    assert EventResolutionOutput.model_validate({"events": []})
