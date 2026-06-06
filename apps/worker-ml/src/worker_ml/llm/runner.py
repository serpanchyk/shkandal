"""LangChain-backed LLM task execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, TypeVar, cast

from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr, ValidationError

from worker_ml.config import MlConfig
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
    LlmRunType,
)
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runs import LlmRunStore

OutputT = TypeVar("OutputT", bound=BaseModel)

RUN_TYPE_MODELS: dict[LlmRunType, type[BaseModel]] = {
    "article_card": ArticleCardOutput,
    "case_resolution": CaseResolutionOutput,
    "entity_resolution": EntityResolutionOutput,
    "event_resolution": EventResolutionOutput,
}


class AsyncTextChain(Protocol):
    """Minimal protocol implemented by LangChain runnables and test fakes."""

    async def ainvoke(self, input: Mapping[str, Any]) -> Any:
        """Invoke the chain asynchronously."""


def create_litellm_chat_model(*, settings: MlConfig, model_name: str) -> ChatOpenAI:
    """Create a LangChain chat model pointed at the LiteLLM proxy."""

    return ChatOpenAI(
        model=model_name,
        api_key=SecretStr(settings.llm_api_key),
        base_url=settings.llm_api_base,
        temperature=0,
    )


class LlmTaskRunner:
    """Run one structured LLM task with optional one-shot repair."""

    def __init__(
        self,
        *,
        prompt_registry: PromptRegistry,
        run_store: LlmRunStore | None = None,
        task_chains: Mapping[str, AsyncTextChain] | None = None,
        repair_chain: AsyncTextChain | None = None,
    ) -> None:
        self._prompt_registry = prompt_registry
        self._run_store = run_store
        self._task_chains = dict(task_chains or {})
        self._repair_chain = repair_chain

    @classmethod
    def from_config(
        cls,
        *,
        settings: MlConfig,
        run_store: LlmRunStore | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> LlmTaskRunner:
        """Create a production runner using LangChain and LiteLLM proxy."""

        registry = prompt_registry or PromptRegistry()
        aliases = model_aliases(settings)
        task_chains = cast(
            dict[str, AsyncTextChain],
            {
                run_type: registry.chat_prompt(run_type)
                | create_litellm_chat_model(settings=settings, model_name=model_name)
                | StrOutputParser()
                for run_type, model_name in aliases.items()
                if run_type != "repair"
            },
        )
        repair_chain = cast(
            AsyncTextChain,
            registry.chat_prompt("repair")
            | create_litellm_chat_model(settings=settings, model_name=aliases["repair"])
            | StrOutputParser(),
        )
        return cls(
            prompt_registry=registry,
            run_store=run_store,
            task_chains=task_chains,
            repair_chain=repair_chain,
        )

    async def run(
        self,
        *,
        run_type: LlmRunType,
        model_name: str,
        variables: Mapping[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> BaseModel:
        """Run an LLM task, validate output, and repair invalid output once."""

        output_model = RUN_TYPE_MODELS[run_type]
        prompt = self._prompt_registry.get(run_type)
        run_id = None
        if self._run_store is not None:
            run_id = await self._run_store.create_run(
                run_type=run_type,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                model_name=model_name,
                metadata=metadata,
            )

        raw_text = ""
        raw_json: dict[str, Any] | None = None
        try:
            raw_text = str(await self._chain_for(run_type).ainvoke(dict(variables)))
            raw_json = parse_json_object(raw_text)
            parsed = output_model.model_validate(raw_json)
        except (ValueError, ValidationError) as exc:
            repaired_json, repair_error = await self._repair(
                output_model=output_model,
                validation_error=str(exc),
                invalid_output=raw_text,
            )
            if repaired_json is None:
                if self._run_store is not None and run_id is not None:
                    await self._run_store.finish_run(
                        run_id=run_id,
                        status="failed",
                        raw_output=raw_json or {"text": raw_text},
                        error_message=repair_error or str(exc),
                        metadata=metadata,
                    )
                raise ValueError(repair_error or str(exc)) from exc

            parsed = output_model.model_validate(repaired_json)
            if self._run_store is not None and run_id is not None:
                await self._run_store.finish_run(
                    run_id=run_id,
                    status="repaired",
                    raw_output=raw_json or {"text": raw_text},
                    repaired_output=repaired_json,
                    metadata=metadata,
                )
            return parsed

        if self._run_store is not None and run_id is not None:
            await self._run_store.finish_run(
                run_id=run_id,
                status="succeeded",
                raw_output=raw_json,
                metadata=metadata,
            )
        return parsed

    def _chain_for(self, run_type: LlmRunType) -> AsyncTextChain:
        try:
            return self._task_chains[run_type]
        except KeyError as exc:
            raise ValueError(f"missing LLM chain for run type: {run_type}") from exc

    async def _repair(
        self,
        *,
        output_model: type[BaseModel],
        validation_error: str,
        invalid_output: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if self._repair_chain is None:
            return None, validation_error

        try:
            repaired_text = str(
                await self._repair_chain.ainvoke(
                    {
                        "schema_json": json.dumps(
                            output_model.model_json_schema(),
                            ensure_ascii=False,
                        ),
                        "validation_error": validation_error,
                        "invalid_output": invalid_output,
                    }
                )
            )
            repaired_json = parse_json_object(repaired_text)
            output_model.model_validate(repaired_json)
            return repaired_json, None
        except (ValueError, ValidationError) as exc:
            return None, str(exc)


def model_aliases(settings: MlConfig) -> dict[str, str]:
    """Return logical LiteLLM aliases by task name."""

    return {
        "article_card": settings.llm_article_card_model,
        "case_resolution": settings.llm_case_resolution_model,
        "entity_resolution": settings.llm_entity_resolution_model,
        "event_resolution": settings.llm_event_resolution_model,
        "repair": settings.llm_repair_model,
    }


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM response that must contain one JSON object."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    return value
