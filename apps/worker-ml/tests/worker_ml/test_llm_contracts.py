"""Tests for LLM output contracts."""

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
            "entities": [
                {
                    "name_uk": "Міська рада",
                    "entity_type": "institution",
                    "aliases": ["рада"],
                    "description_uk": "Орган місцевого самоврядування.",
                    "evidence_text": "у міській раді",
                }
            ],
            "events": [
                {
                    "title_uk": "НАБУ повідомило про підозру",
                    "description_uk": "Детективи повідомили посадовцю про підозру.",
                    "event_date": "2026-06-05",
                    "event_date_precision": "day",
                    "location_uk": "Київ",
                    "evidence_text": "повідомили про підозру",
                }
            ],
            "key_terms": ["закупівлі", "підозра"],
            "source_metadata": {"source": "example"},
        }
    )

    assert output.entities[0].entity_type == "institution"
    assert output.events[0].event_date_precision == "day"


def test_resolution_contracts_accept_empty_decisions() -> None:
    assert CaseResolutionOutput.model_validate(
        {"existing_case_links": [], "new_cases": [], "case_relations": []}
    )
    assert EntityResolutionOutput.model_validate({"entities": []})
    assert EventResolutionOutput.model_validate({"events": []})
