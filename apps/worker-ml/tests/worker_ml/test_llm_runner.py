"""Tests for LangChain-independent LLM runner behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import openai
import pytest
from worker_ml.config import MlConfig
from worker_ml.llm.contracts import ArticleCardOutput
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runner import (
    LlmRateLimitError,
    LlmTaskRunner,
    create_litellm_chat_model,
    invoke_chain,
    model_aliases,
    parse_json_object,
)
from worker_ml.llm.runs import LlmRunStore


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


def test_parse_json_object_accepts_markdown_json_fence() -> None:
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_model_aliases_use_stage_specific_settings() -> None:
    aliases = model_aliases(MlConfig())

    assert aliases["article_card"] == "shkandal-article-card"
    assert aliases["case_resolution"] == "shkandal-case-resolution"
    assert aliases["entity_resolution"] == "shkandal-entity-resolution"
    assert aliases["event_resolution"] == "shkandal-event-resolution"
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


class FailingChain:
    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        raise RuntimeError("provider unavailable")


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
