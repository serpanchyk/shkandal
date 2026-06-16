"""Tests for conservative deterministic LLM output normalization."""

import json

import pytest
from pydantic import ValidationError
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
)
from worker_ml.llm.normalization import normalize_llm_output


def test_normalizes_observed_article_card_contract_failures() -> None:
    result = normalize_llm_output(
        run_type="article_card",
        variables={},
        output={
            "title_uk": "Справа",
            "summary_uk": "Опис.",
            "case_diagnosis": {
                "ukraine_nexus_uk": "Подія стосується українського суду.",
                "concrete_story_core_uk": "Судове рішення у конкретній справі.",
                "public_accountability_anchor_uk": "Йдеться про дію державного органу.",
                "continuation_potential_uk": "Можливе оскарження або наступні етапи.",
                "noise_signals_uk": [],
            },
            "is_case_candidate": True,
            "noise_reason": "generic_news",
            "main_event_title_uk": "Суд ухвалив рішення",
            "entities": [
                {
                    "provisional_ref": "invalid ref",
                    "name_uk": "Орган",
                    "entity_type": "government_agency",
                    "aliases": None,
                    "description_uk": "Учасник справи.",
                }
            ],
            "events": [
                {
                    "provisional_ref": None,
                    "title_uk": "Суд ухвалив рішення",
                    "description_uk": "Суд розглянув справу.",
                    "event_date": "2026-06",
                    "event_date_precision": "day",
                }
            ],
            "case_signature_terms": ["суд"],
        },
    )

    output = ArticleCardOutput.model_validate(result.output)
    assert output.entities[0].provisional_ref == "entity_1"
    assert output.entities[0].entity_type == "institution"
    assert output.entities[0].aliases == []
    assert output.events[0].provisional_ref == "event_1"
    assert output.events[0].event_date_precision == "month"
    assert output.noise_reason is None
    assert result.actions


def test_normalizes_non_case_signals_and_invalid_noise_reason() -> None:
    result = normalize_llm_output(
        run_type="article_card",
        variables={},
        output={
            "title_uk": "Новини",
            "summary_uk": "Огляд новин.",
            "is_case_candidate": False,
            "noise_reason": "other",
            "main_event_title_uk": "Подія",
            "entities": [{"name_uk": "Орган"}],
            "events": [{"title_uk": "Подія"}],
            "case_signature_terms": ["подія"],
        },
    )

    output = ArticleCardOutput.model_validate(result.output)
    assert output.noise_reason == "generic_news"
    assert output.entities == []
    assert output.events == []
    assert output.case_signature_terms == []


def test_resolution_refs_follow_supplied_provisional_inputs_one_to_one() -> None:
    variables = {
        "resolution_json": json.dumps(
            {
                "items": [
                    {"provisional": {"provisional_ref": "entity_first"}},
                    {"provisional": {"provisional_ref": "entity_second"}},
                ]
            }
        )
    }
    result = normalize_llm_output(
        run_type="entity_resolution",
        variables=variables,
        output={
            "entities": [
                {
                    "provisional_ref": "entity_bad",
                    "action": "reject",
                    "confidence": 0.5,
                    "case_assignments": [],
                    "reason_uk": "",
                    "rejection_reason": None,
                },
                {
                    "provisional_ref": "also_bad",
                    "action": "reject",
                    "confidence": 0.4,
                    "case_assignments": [],
                    "reason_uk": "Не сутність.",
                    "rejection_reason": "not_an_entity",
                },
            ]
        },
    )

    output = EntityResolutionOutput.model_validate(result.output)
    assert [item.provisional_ref for item in output.entities] == [
        "entity_first",
        "entity_second",
    ]
    assert output.entities[0].rejection_reason == "not_case_relevant"
    assert output.entities[0].reason_uk


def test_resolution_refs_preserve_valid_reordered_decisions() -> None:
    variables = {
        "resolution_json": json.dumps(
            {
                "items": [
                    {"provisional": {"provisional_ref": "entity_first"}},
                    {"provisional": {"provisional_ref": "entity_second"}},
                ]
            }
        )
    }
    result = normalize_llm_output(
        run_type="entity_resolution",
        variables=variables,
        output={
            "entities": [
                {
                    "provisional_ref": "entity_second",
                    "action": "reject",
                    "confidence": 0.5,
                    "case_assignments": [],
                    "reason_uk": "Не сутність.",
                    "rejection_reason": "not_an_entity",
                },
                {
                    "provisional_ref": "entity_first",
                    "action": "reject",
                    "confidence": 0.4,
                    "case_assignments": [],
                    "reason_uk": "Не сутність.",
                    "rejection_reason": "not_an_entity",
                },
            ]
        },
    )

    assert [item["provisional_ref"] for item in result.output["entities"]] == [
        "entity_second",
        "entity_first",
    ]


def test_accepted_resolution_without_case_assignment_becomes_reject() -> None:
    result = normalize_llm_output(
        run_type="event_resolution",
        variables={
            "resolution_json": json.dumps(
                {"items": [{"provisional": {"provisional_ref": "event_one"}}]}
            )
        },
        output={
            "events": [
                {
                    "provisional_ref": "event_one",
                    "action": "create_new",
                    "existing_event_id": None,
                    "new_title_uk": "Подія",
                    "description_uk": "Опис.",
                    "event_date": "not-a-date",
                    "event_date_precision": "day",
                    "confidence": 0.8,
                    "case_assignments": [],
                    "reason_uk": "",
                    "rejection_reason": None,
                }
            ]
        },
    )

    output = EventResolutionOutput.model_validate(result.output)
    decision = output.events[0]
    assert decision.action == "reject"
    assert decision.new_title_uk is None
    assert decision.event_date is None
    assert decision.event_date_precision == "unknown"
    assert decision.rejection_reason == "not_case_relevant"


def test_entity_resolution_removes_only_unsupported_english_canonical_name() -> None:
    output = {
        "entities": [
            {
                "provisional_ref": "entity_one",
                "action": "reject",
                "new_canonical_name_en": "Unsupported",
                "confidence": 0.5,
                "case_assignments": [],
                "reason_uk": "Не сутність.",
                "rejection_reason": "not_an_entity",
            }
        ]
    }

    result = normalize_llm_output(run_type="entity_resolution", variables={}, output=output)

    EntityResolutionOutput.model_validate(result.output)
    assert "new_canonical_name_en" not in result.output["entities"][0]
    assert "entities[0]: remove unsupported English canonical name" in result.actions


def test_entity_resolution_keeps_other_unknown_fields_strictly_invalid() -> None:
    output = {
        "entities": [
            {
                "provisional_ref": "entity_one",
                "action": "reject",
                "unknown_field": "unsupported",
                "confidence": 0.5,
                "case_assignments": [],
                "reason_uk": "Не сутність.",
                "rejection_reason": "not_an_entity",
            }
        ]
    }

    result = normalize_llm_output(run_type="entity_resolution", variables={}, output=output)

    with pytest.raises(ValidationError):
        EntityResolutionOutput.model_validate(result.output)


def test_case_resolution_truncates_whitelisted_diagnostic_fields() -> None:
    long_text = "Дуже довгий конкретний фактичний опис " * 12
    result = normalize_llm_output(
        run_type="case_resolution",
        variables={},
        output={
            "diagnosis": {
                "article_story_core_uk": long_text,
                "specific_case_core_uk": "Конкретна історія закупівлі.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": long_text,
                "matching_existing_case_ids": [],
                "new_case_core_uk": "Конкретна історія закупівлі.",
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
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
            "decision_reason_uk": long_text,
            "outcome": "resolved",
        },
    )

    output = CaseResolutionOutput.model_validate(result.output)
    assert len(output.diagnosis.article_story_core_uk or "") <= 240
    assert len(output.diagnosis.case_coherence_test_uk) <= 240
    assert len(output.decision_reason_uk) <= 320
    assert "truncate diagnosis.article_story_core_uk to 240" in result.actions
    assert "truncate decision_reason_uk to 320" in result.actions


def test_entity_resolution_truncates_whitelisted_nested_reason_fields() -> None:
    long_text = "Дуже довгий доказ тотожності " * 20
    result = normalize_llm_output(
        run_type="entity_resolution",
        variables={},
        output={
            "entities": [
                {
                    "provisional_ref": "entity_one",
                    "diagnosis": {
                        "is_named_stable_actor": False,
                        "material_case_ids": [],
                        "identity_match_evidence_uk": long_text,
                        "identity_conflict_uk": None,
                        "rejection_signal_uk": long_text,
                    },
                    "action": "reject",
                    "confidence": 0.5,
                    "case_assignments": [],
                    "reason_uk": long_text,
                    "rejection_reason": "not_an_entity",
                }
            ]
        },
    )

    output = EntityResolutionOutput.model_validate(result.output)
    assert len(output.entities[0].diagnosis.identity_match_evidence_uk or "") == 240
    assert len(output.entities[0].diagnosis.rejection_signal_uk or "") == 240
    assert len(output.entities[0].reason_uk) == 320
    assert "truncate entities[0].diagnosis.identity_match_evidence_uk to 240" in result.actions
    assert "truncate entities[0].reason_uk to 320" in result.actions


def test_does_not_invent_missing_case_candidate_facts() -> None:
    result = normalize_llm_output(
        run_type="article_card",
        variables={},
        output={
            "title_uk": "Справа",
            "summary_uk": "Опис.",
            "is_case_candidate": True,
            "noise_reason": None,
            "main_event_title_uk": None,
            "entities": [],
            "events": [],
            "case_signature_terms": [],
        },
    )

    try:
        ArticleCardOutput.model_validate(result.output)
    except ValueError:
        pass
    else:
        raise AssertionError("normalization must not invent missing case facts")


def test_case_resolution_keeps_non_whitelisted_fields_strictly_invalid() -> None:
    result = normalize_llm_output(
        run_type="case_resolution",
        variables={},
        output={
            "diagnosis": {
                "article_story_core_uk": "Конкретне ядро історії.",
                "specific_case_core_uk": "Конкретна історія закупівлі.",
                "only_broad_overlap_uk": None,
                "merge_blockers_uk": [],
                "separate_story_cores_uk": [],
                "case_coherence_test_uk": "Так, це одне конкретне речення.",
                "matching_existing_case_ids": [],
                "new_case_core_uk": "Конкретна історія закупівлі.",
                "rejection_signals_uk": [],
                "broad_theme_warning_uk": None,
            },
            "existing_case_links": [],
            "new_cases": [
                {
                    "new_case_ref": "bad-ref",
                    "title_uk": "Нова справа " * 80,
                    "summary_uk": "Опис.",
                    "link_reason_uk": "Причина.",
                    "confidence": 0.8,
                }
            ],
            "case_relations": [],
            "decision_reason_uk": "Створюємо нову конкретну справу.",
            "outcome": "resolved",
        },
    )

    with pytest.raises(ValidationError):
        CaseResolutionOutput.model_validate(result.output)
