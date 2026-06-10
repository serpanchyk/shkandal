"""Tests for LLM output contracts."""

import pytest
from pydantic import ValidationError
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
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
    ["culture", "diplomacy", "policy_law", "routine_regulatory", "routine_crime"],
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


def test_case_resolution_contract_rejects_empty_decisions() -> None:
    with pytest.raises(ValidationError):
        CaseResolutionOutput.model_validate(
            {"existing_case_links": [], "new_cases": [], "case_relations": []}
        )


def test_other_resolution_contracts_accept_empty_decisions() -> None:
    assert EntityResolutionOutput.model_validate({"entities": []})
    assert EventResolutionOutput.model_validate({"events": []})
