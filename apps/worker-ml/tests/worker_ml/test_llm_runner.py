"""Tests for LangChain-independent LLM runner behavior."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from worker_ml.config import MlConfig
from worker_ml.llm.contracts import ArticleCardOutput
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runner import LlmTaskRunner, model_aliases, parse_json_object


@pytest.mark.asyncio
async def test_runner_returns_valid_output_without_repair() -> None:
    runner = LlmTaskRunner(
        prompt_registry=PromptRegistry(),
        task_chains={
            "article_card": FakeChain(
                '{"title_uk":"Заголовок","summary_uk":"Опис","entities":[],"events":[],'
                '"key_terms":[],"source_metadata":{}}'
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
async def test_runner_repairs_invalid_output_once() -> None:
    repair_chain = FakeChain(
        '{"title_uk":"Виправлено","summary_uk":"Опис","entities":[],"events":[],'
        '"key_terms":[],"source_metadata":{}}'
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


def test_parse_json_object_accepts_markdown_json_fence() -> None:
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_model_aliases_use_stage_specific_settings() -> None:
    aliases = model_aliases(MlConfig())

    assert aliases["article_card"] == "shkandal-article-card"
    assert aliases["case_resolution"] == "shkandal-case-resolution"
    assert aliases["entity_resolution"] == "shkandal-entity-resolution"
    assert aliases["event_resolution"] == "shkandal-event-resolution"
    assert aliases["repair"] == "shkandal-repair"


class FakeChain:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[Mapping[str, Any]] = []

    async def ainvoke(self, input: Mapping[str, Any]) -> str:
        self.calls.append(input)
        return self.response
