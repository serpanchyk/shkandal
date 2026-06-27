"""Tests for LangChain-independent LLM runner behavior."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel
from worker_ml.config import MlConfig
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseCoherenceAuditOutput,
    CaseCopyUpdateOutput,
    CaseDuplicateAuditOutput,
    CaseLinkAuditOutput,
    CasePublicInterestAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    LlmRunType,
)
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runner import (
    LlmDependencyUnavailableError,
    LlmRateLimitError,
    LlmTaskRunner,
    create_litellm_chat_model,
    invoke_chain,
    model_aliases,
    parse_json_object,
    parse_json_response,
)
from worker_ml.llm.runs import LlmRunStore
from worker_ml.llm.tasks import LLM_TASKS


@pytest.mark.asyncio
async def test_runner_returns_valid_output_without_repair() -> None:
    cooldown_observer = Mock()
    cooldown_observer.clear_expired_ambiguous_observation = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={
            "article_card": FakeChain(
                '{"title_uk":"Заголовок","summary_uk":"Опис","is_case_candidate":false,'
                '"noise_reason":"generic_news","main_event_title_uk":null,"entities":[],'
                '"events":[],"case_signature_terms":[]}'
            )
        },
        cooldown_observer=cooldown_observer,
    )

    result = await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result, ArticleCardOutput)
    assert result.title_uk == "Заголовок"
    cooldown_observer.clear_expired_ambiguous_observation.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_returns_persisted_run_provenance() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "article_card": FakeChain(
                '{"title_uk":"Заголовок","summary_uk":"Опис","is_case_candidate":false,'
                '"noise_reason":"generic_news","main_event_title_uk":null,"entities":[],'
                '"events":[],"case_signature_terms":[]}'
            )
        },
    )

    result = await runner.run_with_provenance(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert result.run_id == run_id
    assert isinstance(result.output, ArticleCardOutput)
    run_store.finish_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_persists_resolved_model_from_text_response() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "article_card": FakeObjectChain(
                AIMessage(
                    content=(
                        '{"title_uk":"Заголовок","summary_uk":"Опис",'
                        '"is_case_candidate":false,"noise_reason":"generic_news",'
                        '"main_event_title_uk":null,"entities":[],"events":[],'
                        '"case_signature_terms":[]}'
                    ),
                    response_metadata={"model_name": "openai/MamayLM-Gemma-3-27B-IT-v2.0"},
                )
            )
        },
    )

    await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert run_store.create_run.await_args.kwargs["model_name"] == "shkandal-article-card"
    assert (
        run_store.finish_run.await_args.kwargs["model_name"] == "openai/MamayLM-Gemma-3-27B-IT-v2.0"
    )


@pytest.mark.asyncio
async def test_runner_persists_resolved_model_from_structured_response() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    parsed = ArticleCardOutput.model_validate(
        {
            "title_uk": "Заголовок",
            "summary_uk": "Опис",
            "case_diagnosis": {
                "ukraine_nexus_uk": None,
                "concrete_story_core_uk": None,
                "public_accountability_anchor_uk": None,
                "continuation_potential_uk": None,
                "noise_signals_uk": [],
            },
            "is_case_candidate": False,
            "noise_reason": "generic_news",
            "main_event_title_uk": None,
            "entities": [],
            "events": [],
            "case_signature_terms": [],
        }
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "article_card": FakeObjectChain(
                {
                    "raw": AIMessage(
                        content="",
                        response_metadata={"model_name": "MamayLLM"},
                    ),
                    "parsed": parsed,
                    "parsing_error": None,
                }
            )
        },
    )

    result = await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert result == parsed
    assert run_store.finish_run.await_args.kwargs["model_name"] == "MamayLLM"


@pytest.mark.asyncio
async def test_runner_records_prompt_override_under_case_resolution_run_type() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "case_creation_after_dropped_links": FakeChain(
                json.dumps(
                    {
                        "diagnosis": {
                            "article_story_core_uk": "Стаття описує конкретну закупівлю.",
                            "specific_case_core_uk": "Нова закупівельна справа.",
                            "only_broad_overlap_uk": None,
                            "merge_blockers_uk": [],
                            "separate_story_cores_uk": [],
                            "case_coherence_test_uk": "Так, це одна конкретна справа.",
                            "matching_existing_case_ids": [],
                            "new_case_core_uk": "Нова закупівельна справа.",
                            "rejection_signals_uk": [],
                            "broad_theme_warning_uk": None,
                        },
                        "existing_case_links": [],
                        "new_cases": [
                            {
                                "new_case_ref": "new_case_1",
                                "title_uk": "Закупівля дронів у компанії X",
                                "summary_uk": "Нова справа щодо конкретної закупівлі.",
                                "link_reason_uk": "Стаття започатковує окрему справу.",
                                "confidence": 0.86,
                            }
                        ],
                        "decision_reason_uk": "Після відкидання кандидатів лишилась нова справа.",
                        "outcome": "resolved",
                    },
                    ensure_ascii=False,
                )
            )
        },
    )

    result = await runner.run_with_provenance(
        run_type="case_resolution",
        prompt_name="case_creation_after_dropped_links",
        model_name="shkandal-case-resolution",
        variables={"resolution_json": "{}", "schema_json": "{}"},
    )

    assert result.run_id == run_id
    assert isinstance(result.output, CaseResolutionOutput)
    assert run_store.create_run.await_args.kwargs["run_type"] == "case_resolution"
    assert (
        run_store.create_run.await_args.kwargs["prompt_name"] == "case_creation_after_dropped_links"
    )


@pytest.mark.asyncio
async def test_runner_persists_deterministically_normalized_output_as_repaired() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    raw_output = (
        '{"title_uk":"Новини","summary_uk":"Опис","is_case_candidate":false,'
        '"noise_reason":null,"main_event_title_uk":"Подія","entities":[],'
        '"events":[],"case_signature_terms":["подія"]}'
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": FakeChain(raw_output)},
    )

    result = await runner.run_with_provenance(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result.output, ArticleCardOutput)
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["raw_output"]["main_event_title_uk"] == "Подія"
    assert call["repaired_output"]["main_event_title_uk"] is None
    assert call["metadata"]["normalization_actions"]


@pytest.mark.asyncio
async def test_runner_repairs_only_unescaped_json_control_characters() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    raw_output = (
        '{"title_uk":"Заголовок","summary_uk":"Перший рядок\nДругий рядок",'
        '"is_case_candidate":false,"noise_reason":"generic_news",'
        '"main_event_title_uk":null,"entities":[],"events":[],"case_signature_terms":[]}'
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": FakeChain(raw_output)},
    )

    result = await runner.run_with_provenance(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    output = cast(ArticleCardOutput, result.output)
    assert output.summary_uk == "Перший рядок\nДругий рядок"
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["raw_output"] == {"text": raw_output}
    assert call["repaired_output"]["summary_uk"] == "Перший рядок\nДругий рядок"
    assert call["metadata"]["parse_repair"] == "escaped_control_characters"


def test_parse_json_response_escapes_only_control_characters_inside_strings() -> None:
    payload = parse_json_response(
        '{\n"summary_uk": "Перший\tрядок\u0001\nДругий рядок",\n"ok": true\n}',
        allow_array=False,
    )

    assert payload == {"summary_uk": "Перший\tрядок\u0001\nДругий рядок", "ok": True}


@pytest.mark.asyncio
async def test_runner_accepts_repair_output_with_raw_string_newline() -> None:
    repair_output = (
        '{"title_uk":"Виправлено","summary_uk":"Перший рядок\nДругий рядок",'
        '"is_case_candidate":false,"noise_reason":"generic_news",'
        '"main_event_title_uk":null,"entities":[],"events":[],"case_signature_terms":[]}'
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={"article_card": FakeChain("not json")},
        repair_chain=FakeChain(repair_output),
    )

    result = await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result, ArticleCardOutput)
    assert result.summary_uk == "Перший рядок\nДругий рядок"


@pytest.mark.asyncio
async def test_runner_persists_non_candidate_entity_link_as_repaired_reject() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    bad_entity_id = str(uuid4())
    case_id = str(uuid4())
    raw_output = json.dumps(
        {
            "entities": [
                {
                    "provisional_ref": "entity_a",
                    "diagnosis": {
                        "is_named_stable_actor": True,
                        "material_case_ids": [case_id],
                        "identity_match_evidence_uk": "Назва схожа.",
                        "identity_conflict_uk": None,
                        "rejection_signal_uk": None,
                    },
                    "action": "link_existing",
                    "existing_entity_id": bad_entity_id,
                    "new_canonical_name_uk": None,
                    "entity_type": None,
                    "aliases": [],
                    "description_uk": "Опис.",
                    "confidence": 0.7,
                    "case_assignments": [{"case_id": case_id, "relevance_reason_uk": "Причина."}],
                    "reason_uk": "Та сама сутність.",
                    "rejection_reason": None,
                }
            ]
        }
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"entity_resolution": FakeChain(raw_output)},
    )

    result = await runner.run_with_provenance(
        run_type="entity_resolution",
        model_name="shkandal-entity-resolution",
        variables={
            "resolution_json": json.dumps(
                {
                    "items": [
                        {
                            "provisional": {"provisional_ref": "entity_a"},
                            "candidates": [],
                        }
                    ]
                }
            ),
            "schema_json": "{}",
        },
    )

    output = cast(EntityResolutionOutput, result.output)
    assert output.entities[0].action == "reject"
    assert output.entities[0].rejection_reason == "insufficient_identity"
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["raw_output"]["entities"][0]["existing_entity_id"] == bad_entity_id
    assert call["repaired_output"]["entities"][0]["existing_entity_id"] is None
    assert call["repaired_output"]["entities"][0]["case_assignments"] == []
    assert "reject non-candidate identity" in " ".join(call["metadata"]["normalization_actions"])


@pytest.mark.asyncio
async def test_runner_accepts_structured_dict_output_without_text_parsing() -> None:
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={
            "article_card": FakeObjectChain(
                {
                    "title_uk": "Заголовок",
                    "summary_uk": "Опис",
                    "is_case_candidate": False,
                    "noise_reason": "generic_news",
                    "main_event_title_uk": None,
                    "entities": [],
                    "events": [],
                    "case_signature_terms": [],
                }
            )
        },
    )

    result = await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result, ArticleCardOutput)
    assert result.title_uk == "Заголовок"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_type", "raw_output", "expected_model", "expected_key", "expected_ref"),
    [
        (
            "entity_resolution",
            json.dumps(
                [
                    {
                        "provisional_ref": "entity_a",
                        "diagnosis": {
                            "is_named_stable_actor": True,
                            "material_case_ids": ["case-a"],
                            "identity_match_evidence_uk": None,
                            "identity_conflict_uk": None,
                            "rejection_signal_uk": None,
                        },
                        "action": "create_new",
                        "existing_entity_id": None,
                        "new_canonical_name_uk": "Орган",
                        "entity_type": "organization",
                        "aliases": [],
                        "description_uk": "Орган.",
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": str(uuid4()), "relevance_reason_uk": "Причина"}
                        ],
                        "reason_uk": "Потрібно створити нову сутність.",
                        "rejection_reason": None,
                    }
                ]
            ),
            EntityResolutionOutput,
            "entities",
            "entity_a",
        ),
        (
            "event_resolution",
            json.dumps(
                [
                    {
                        "provisional_ref": "event_a",
                        "diagnosis": {
                            "is_concrete_occurrence": True,
                            "occurrence_core_uk": "Подія.",
                            "anchor_summary_uk": "Дія і учасники визначені.",
                            "candidate_match_evidence_uk": None,
                            "anchor_conflict_uk": None,
                            "temporal_scope_check_uk": (
                                "Подія вже відбулася і не виходить за поточну дату."
                            ),
                            "future_date_warning_uk": None,
                            "material_case_ids": ["case-a"],
                            "rejection_signal_uk": None,
                        },
                        "action": "create_new",
                        "existing_event_id": None,
                        "new_title_uk": "Подія",
                        "description_uk": "Опис.",
                        "event_date": None,
                        "event_date_precision": "unknown",
                        "location_uk": None,
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": str(uuid4()), "relevance_reason_uk": "Причина"}
                        ],
                        "reason_uk": "Потрібно створити нову подію.",
                        "rejection_reason": None,
                    }
                ]
            ),
            EventResolutionOutput,
            "events",
            "event_a",
        ),
    ],
)
async def test_runner_wraps_top_level_resolution_arrays_before_validation(
    run_type: LlmRunType,
    raw_output: str,
    expected_model: type[Any],
    expected_key: str,
    expected_ref: str,
) -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={run_type: FakeChain(raw_output)},
    )

    result = await runner.run_with_provenance(
        run_type=run_type,
        model_name=f"shkandal-{run_type.replace('_', '-')}",
        variables={
            "resolution_json": json.dumps(
                {"items": [{"provisional": {"provisional_ref": expected_ref}}]}
            ),
            "schema_json": "{}",
        },
    )

    assert isinstance(result.output, expected_model)
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["repaired_output"][expected_key][0]["provisional_ref"] == expected_ref
    assert call["metadata"]["normalization_actions"] == [f"wrap {expected_key} array"]


@pytest.mark.asyncio
async def test_runner_fails_when_repaired_resolution_output_drops_decisions() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    repair_output = json.dumps(
        {
            "entities": [
                {
                    "provisional_ref": "entity_a",
                    "action": "reject",
                    "confidence": 0.4,
                    "case_assignments": [],
                    "reason_uk": "Не сутність.",
                    "rejection_reason": "not_an_entity",
                }
            ]
        }
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"entity_resolution": FakeChain("not json")},
        repair_chain=FakeChain(repair_output),
    )

    with pytest.raises(ValueError, match="exactly cover provisional refs"):
        await runner.run(
            run_type="entity_resolution",
            model_name="shkandal-entity-resolution",
            variables={
                "resolution_json": json.dumps(
                    {
                        "items": [
                            {"provisional": {"provisional_ref": "entity_a"}},
                            {"provisional": {"provisional_ref": "entity_b"}},
                        ]
                    }
                ),
                "schema_json": "{}",
            },
        )

    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "failed"
    assert "exactly cover provisional refs" in call["error_message"]


@pytest.mark.asyncio
async def test_runner_repairs_invalid_output_once() -> None:
    repair_chain = FakeChain(
        '{"title_uk":"Виправлено","summary_uk":"Опис","is_case_candidate":false,'
        '"noise_reason":"generic_news","main_event_title_uk":null,"entities":[],'
        '"events":[],"case_signature_terms":[]}'
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={"article_card": FakeChain('{"title_uk":"Без обовязкових полів"}')},
        repair_chain=repair_chain,
    )

    result = await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result, ArticleCardOutput)
    assert result.title_uk == "Виправлено"
    assert repair_chain.calls[0]["invalid_output"] == '{"title_uk":"Без обовязкових полів"}'
    assert "article_json" not in repair_chain.calls[0]
    assert '"enum"' in repair_chain.calls[0]["schema_json"]


@pytest.mark.asyncio
async def test_runner_truncates_overlong_case_resolution_fields_without_repair() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    long_text = "Дуже довгий конкретний фактичний опис " * 12
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "case_resolution": FakeChain(
                json.dumps(
                    {
                        "diagnosis": {
                            "article_story_core_uk": long_text,
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
                                "new_case_ref": "new_case",
                                "title_uk": "Нова справа",
                                "summary_uk": "Опис.",
                                "link_reason_uk": "Причина.",
                                "confidence": 0.8,
                            }
                        ],
                        "decision_reason_uk": long_text,
                        "outcome": "resolved",
                    },
                    ensure_ascii=False,
                )
            )
        },
    )

    result = await runner.run_with_provenance(
        run_type="case_resolution",
        model_name="shkandal-case-resolution",
        variables={"resolution_json": "{}", "schema_json": "{}"},
    )

    output = cast(CaseResolutionOutput, result.output)
    assert len(output.diagnosis.article_story_core_uk or "") <= 240
    assert len(output.decision_reason_uk) <= 320
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert (
        "truncate diagnosis.article_story_core_uk to 240"
        in call["metadata"]["normalization_actions"]
    )


@pytest.mark.asyncio
async def test_runner_truncates_overlong_case_resolution_fields_after_repair() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    long_text = "Дуже довгий конкретний фактичний опис " * 12
    repair_output = json.dumps(
        {
            "diagnosis": {
                "article_story_core_uk": long_text,
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
                    "new_case_ref": "new_case",
                    "title_uk": "Нова справа",
                    "summary_uk": "Опис.",
                    "link_reason_uk": "Причина.",
                    "confidence": 0.8,
                }
            ],
            "decision_reason_uk": long_text,
            "outcome": "resolved",
        },
        ensure_ascii=False,
    )
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"case_resolution": FakeChain("not json")},
        repair_chain=FakeChain(repair_output),
    )

    result = await runner.run_with_provenance(
        run_type="case_resolution",
        model_name="shkandal-case-resolution",
        variables={"resolution_json": "{}", "schema_json": "{}"},
    )

    output = cast(CaseResolutionOutput, result.output)
    assert len(output.diagnosis.article_story_core_uk or "") <= 240
    assert len(output.decision_reason_uk) <= 320
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert len(call["repaired_output"]["decision_reason_uk"]) <= 320


@pytest.mark.asyncio
async def test_runner_records_primary_and_repair_models_separately() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "article_card": FakeObjectChain(
                AIMessage(
                    content='{"title_uk":"Без обовязкових полів"}',
                    response_metadata={"model_name": "MamayLLM"},
                )
            )
        },
        repair_chain=FakeObjectChain(
            AIMessage(
                content=(
                    '{"title_uk":"Виправлено","summary_uk":"Опис",'
                    '"is_case_candidate":false,"noise_reason":"generic_news",'
                    '"main_event_title_uk":null,"entities":[],"events":[],'
                    '"case_signature_terms":[]}'
                ),
                response_metadata={"model_name": "RepairLLM"},
            )
        ),
    )

    await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    call = run_store.finish_run.await_args.kwargs
    assert call["model_name"] == "MamayLLM"
    assert call["metadata"]["repair_model_name"] == "RepairLLM"


@pytest.mark.asyncio
async def test_runner_preserves_primary_model_when_text_parse_fails() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "article_card": FakeObjectChain(
                AIMessage(
                    content="not json",
                    response_metadata={"model_name": "MamayLLM"},
                )
            )
        },
        repair_chain=FakeObjectChain(
            AIMessage(
                content=(
                    '{"title_uk":"Виправлено","summary_uk":"Опис",'
                    '"is_case_candidate":false,"noise_reason":"generic_news",'
                    '"main_event_title_uk":null,"entities":[],"events":[],'
                    '"case_signature_terms":[]}'
                ),
                response_metadata={"model_name": "RepairLLM"},
            )
        ),
    )

    await runner.run(
        run_type="article_card",
        model_name="shkandal-article-card",
        variables={"article_json": "{}", "schema_json": "{}"},
    )

    call = run_store.finish_run.await_args.kwargs
    assert call["model_name"] == "MamayLLM"
    assert call["metadata"]["repair_model_name"] == "RepairLLM"


@pytest.mark.asyncio
async def test_runner_fails_after_invalid_repair() -> None:
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={"article_card": FakeChain("not json")},
        repair_chain=FakeChain("still not json"),
    )

    with pytest.raises(ValueError):
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )


@pytest.mark.asyncio
async def test_case_copy_update_accepts_long_rationale_fields() -> None:
    long_reason = "Поточна назва надто вузько описує один епізод. " * 20
    long_core = "Стійке ядро назви зберігає центральний сюжет справи. " * 12
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={
            "case_copy_update": FakeChain(
                json.dumps(
                    {
                        "title_diagnosis": {
                            "current_title_specific_enough": False,
                            "replacement_needed_reason_uk": long_reason,
                            "proposed_title_core_uk": long_core,
                        },
                        "replacement_title_uk": "Справа про центральний сюжет",
                        "summary_uk": "Нейтральний підсумок справи.",
                        "title_reason_uk": long_reason,
                        "title_action": "replace",
                    },
                    ensure_ascii=False,
                )
            )
        },
    )

    result = await runner.run(
        run_type="case_copy_update",
        model_name="shkandal-case-copy-update",
        variables={"case_json": "{}", "schema_json": "{}"},
    )

    output = cast(CaseCopyUpdateOutput, result)
    assert output.title_reason_uk == long_reason
    assert output.title_diagnosis.replacement_needed_reason_uk == long_reason
    assert output.title_diagnosis.proposed_title_core_uk == long_core


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_type", "output_type", "variables"),
    [
        (
            "case_link_audit",
            CaseLinkAuditOutput,
            {"case_json": "{}", "schema_json": "{}"},
        ),
        (
            "case_coherence_audit",
            CaseCoherenceAuditOutput,
            {"case_json": "{}", "schema_json": "{}"},
        ),
        (
            "case_public_interest_audit",
            CasePublicInterestAuditOutput,
            {"case_json": "{}", "schema_json": "{}"},
        ),
        (
            "case_duplicate_audit",
            CaseDuplicateAuditOutput,
            {"cases_json": "{}", "schema_json": "{}"},
        ),
    ],
)
async def test_invalid_audit_repair_becomes_persisted_inconclusive(
    run_type: LlmRunType,
    output_type: type[BaseModel],
    variables: dict[str, str],
) -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    schema_echo = '{"type":"object","properties":{"outcome":{"type":"string"}}}'
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={run_type: FakeChain("not json")},
        repair_chain=FakeChain(schema_echo),
    )

    result = await runner.run_with_provenance(
        run_type=run_type,
        model_name=f"shkandal-{run_type.replace('_', '-')}",
        variables=variables,
    )

    output = output_type.model_validate(result.output)
    assert output.model_dump()["outcome"] == "inconclusive"
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["repaired_output"]["outcome"] == "inconclusive"
    assert call["metadata"]["repair_attempt_output"] == schema_echo
    assert call["metadata"]["schema_echo"] is True
    assert call["metadata"]["audit_fallback_reason"] == "repair response echoed JSON schema"


@pytest.mark.asyncio
async def test_runner_normalizes_case_audit_story_reasons_and_duplicate_article_ids() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={
            "case_coherence_audit": FakeChain(
                json.dumps(
                    {
                        "diagnosis": {
                            "shared_specific_core_uk": None,
                            "shared_only_broad_theme_uk": None,
                            "merge_blockers_uk": ["Є щонайменше дві історії."],
                            "split_story_cores_uk": ["Перша справа.", "Друга справа."],
                            "detached_article_signals_uk": [],
                            "coherence_test_uk": "Ні, це дві різні історії.",
                        },
                        "reason_uk": "Статті описують одну історію.",
                        "outcome": "split",
                        "stories": [
                            {
                                "story_ref": "original",
                                "title_uk": "Перша справа",
                                "summary_uk": "Опис першої справи.",
                                "article_ids": ["article-a", "article-a", "article-b"],
                            },
                            {
                                "story_ref": "story_1",
                                "title_uk": "Друга справа",
                                "summary_uk": "Опис другої справи.",
                                "article_ids": ["article-c"],
                            },
                        ],
                    }
                )
            )
        },
    )

    result = await runner.run_with_provenance(
        run_type="case_coherence_audit",
        model_name="shkandal-case-coherence-audit",
        variables={"case_json": "{}", "schema_json": "{}"},
    )

    assert isinstance(result.output, CaseCoherenceAuditOutput)
    assert result.output.stories[0].reason_uk == "Статті описують одну історію."
    assert result.output.stories[0].article_ids == ["article-a", "article-b"]
    call = run_store.finish_run.await_args.kwargs
    assert call["status"] == "repaired"
    assert call["repaired_output"]["stories"][0]["article_ids"] == ["article-a", "article-b"]
    assert call["repaired_output"]["stories"][0]["reason_uk"] == "Статті описують одну історію."


@pytest.mark.asyncio
async def test_runner_persists_unexpected_call_failure() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": FailingChain()},
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert run_store.finish_run.await_args.kwargs["status"] == "failed"
    assert run_store.finish_run.await_args.kwargs["error_message"] == "provider unavailable"
    assert run_store.finish_run.await_args.kwargs["model_name"] == "shkandal-article-card"


@pytest.mark.asyncio
async def test_runner_normalizes_litellm_connection_failure() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": ConnectionErrorChain()},
    )

    with pytest.raises(LlmDependencyUnavailableError, match="LiteLLM proxy unavailable"):
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert run_store.finish_run.await_args.kwargs["status"] == "failed"
    assert run_store.finish_run.await_args.kwargs["error_message"] == "LiteLLM proxy unavailable"
    assert run_store.finish_run.await_args.kwargs["model_name"] == "shkandal-article-card"


@pytest.mark.asyncio
async def test_runner_does_not_normalize_litellm_prompt_timeout() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": TimeoutChain()},
    )

    with pytest.raises(openai.APITimeoutError):
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert run_store.finish_run.await_args.kwargs["status"] == "failed"
    assert run_store.finish_run.await_args.kwargs["model_name"] == "shkandal-article-card"


def test_parse_json_object_accepts_markdown_json_fence() -> None:
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_json_parse_fallback_rejects_other_malformed_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_json_response('{"ok": true,}', allow_array=False)


def test_model_aliases_use_stage_specific_settings() -> None:
    aliases = model_aliases(MlConfig())

    assert aliases["article_card"] == "shkandal-article-card"
    assert aliases["case_resolution"] == "shkandal-case-resolution"
    assert aliases["case_link_audit"] == "shkandal-case-coherence-audit"
    assert aliases["entity_resolution"] == "shkandal-entity-resolution"
    assert aliases["event_resolution"] == "shkandal-event-resolution"
    assert aliases["case_copy_update"] == "shkandal-case-copy-update"
    assert aliases["repair"] == "shkandal-repair"


@pytest.mark.asyncio
async def test_runner_normalizes_provider_rate_limit_and_persists_metadata() -> None:
    run_id = uuid4()
    run_store = Mock(spec=LlmRunStore)
    run_store.create_run = AsyncMock(return_value=run_id)
    run_store.finish_run = AsyncMock()
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        run_store=run_store,
        task_chains={"article_card": RateLimitedChain(retry_after="120")},
    )

    with pytest.raises(LlmRateLimitError) as raised:
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert raised.value.retry_after_seconds == 120
    assert run_store.finish_run.await_args.kwargs["metadata"]["rate_limited"] is True


@pytest.mark.asyncio
async def test_runner_rate_limit_without_retry_after_is_ambiguous() -> None:
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={"article_card": RateLimitedChain()},
    )

    with pytest.raises(LlmRateLimitError) as raised:
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert raised.value.retry_after_seconds is None


@pytest.mark.asyncio
async def test_runner_rate_limit_with_invalid_retry_after_is_ambiguous() -> None:
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={"article_card": RateLimitedChain(retry_after="not-a-duration")},
    )

    with pytest.raises(LlmRateLimitError) as raised:
        await runner.run(
            run_type="article_card",
            model_name="shkandal-article-card",
            variables={"article_json": "{}", "schema_json": "{}"},
        )

    assert raised.value.retry_after_seconds is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [422, 500])
async def test_non_rate_limit_api_errors_are_not_normalized(status_code: int) -> None:
    with pytest.raises(openai.APIStatusError) as raised:
        await invoke_chain(ApiErrorChain(status_code), {})

    assert raised.value.status_code == status_code


def test_chat_model_uses_five_minute_request_timeout() -> None:
    model = create_litellm_chat_model(
        settings=MlConfig(llm_request_timeout_seconds=300),
        model_name="shkandal-article-card",
    )

    assert model.request_timeout == 300


class FakeChain:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[Mapping[str, Any]] = []

    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        self.calls.append(input)
        return self.response


class FakeObjectChain:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[Mapping[str, Any]] = []

    async def ainvoke(self, input: Mapping[str, Any]) -> Any:
        self.calls.append(input)
        return self.response


class FailingChain:
    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        raise RuntimeError("provider unavailable")


class ConnectionErrorChain:
    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        request = httpx.Request("POST", "http://litellm:4000/v1/chat/completions")
        raise openai.APIConnectionError(request=request)


class TimeoutChain:
    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        request = httpx.Request("POST", "http://litellm:4000/v1/chat/completions")
        raise openai.APITimeoutError(request=request)


class RateLimitedChain:
    def __init__(self, retry_after: str | None = None) -> None:
        self.retry_after = retry_after

    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        headers = {"retry-after": self.retry_after} if self.retry_after is not None else {}
        response = httpx.Response(
            429,
            headers=headers,
            request=httpx.Request("POST", "https://provider.example/v1/chat/completions"),
        )
        raise openai.RateLimitError("quota exhausted", response=response, body=None)


class ApiErrorChain:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        response = httpx.Response(
            self.status_code,
            request=httpx.Request("POST", "https://provider.example/v1/chat/completions"),
        )
        raise openai.APIStatusError("provider error", response=response, body=None)


def test_task_registry_declares_contract_and_response_shape() -> None:
    assert LLM_TASKS["article_card"].output_model is ArticleCardOutput
    assert LLM_TASKS["entity_resolution"].allow_top_level_array is True
    assert LLM_TASKS["case_resolution"].allow_top_level_array is False
