"""LangChain-backed LLM task execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from openai import RateLimitError
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


class LlmRateLimitError(RuntimeError):
    """Provider rate limit with the requested retry time."""

    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class LlmTaskResult:
    """Validated LLM output and its persisted run provenance."""

    output: BaseModel
    run_id: UUID | None


class AsyncTextChain(Protocol):
    """Minimal protocol implemented by LangChain runnables and test fakes."""

    async def ainvoke(self, input: Mapping[str, Any]) -> Any:
        """Invoke the chain asynchronously."""


class LlmCooldownObserver(Protocol):
    """Cooldown operation triggered by a successful provider request."""

    async def clear_expired_ambiguous_observation(self) -> None:
        """Clear expired ambiguous rate-limit evidence."""


def create_litellm_chat_model(*, settings: MlConfig, model_name: str) -> ChatOpenAI:
    """Create a LangChain chat model pointed at the LiteLLM proxy."""

    return ChatOpenAI(
        model=model_name,
        api_key=SecretStr(settings.llm_api_key),
        base_url=settings.llm_api_base,
        temperature=0,
        max_retries=0,
        timeout=settings.llm_request_timeout_seconds,
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
        cooldown_observer: LlmCooldownObserver | None = None,
    ) -> None:
        self._prompt_registry = prompt_registry
        self._run_store = run_store
        self._task_chains = dict(task_chains or {})
        self._repair_chain = repair_chain
        self._cooldown_observer = cooldown_observer

    @classmethod
    def from_config(
        cls,
        *,
        settings: MlConfig,
        run_store: LlmRunStore | None = None,
        prompt_registry: PromptRegistry | None = None,
        cooldown_observer: LlmCooldownObserver | None = None,
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
            cooldown_observer=cooldown_observer,
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

        return (
            await self.run_with_provenance(
                run_type=run_type,
                model_name=model_name,
                variables=variables,
                metadata=metadata,
            )
        ).output

    async def run_with_provenance(
        self,
        *,
        run_type: LlmRunType,
        model_name: str,
        variables: Mapping[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> LlmTaskResult:
        """Run an LLM task and return validated output with run provenance."""

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
            raw_text = str(await invoke_chain(self._chain_for(run_type), dict(variables)))
            await self._record_successful_request()
            raw_json = parse_json_object(raw_text)
            parsed = output_model.model_validate(raw_json)
        except (ValueError, ValidationError) as exc:
            try:
                repaired_json, repair_error = await self._repair(
                    output_model=output_model,
                    validation_error=str(exc),
                    invalid_output=raw_text,
                )
            except LlmRateLimitError as rate_limit_exc:
                await self._finish_rate_limited_run(
                    run_id=run_id,
                    raw_text=raw_text,
                    raw_json=raw_json,
                    error=rate_limit_exc,
                    metadata=metadata,
                )
                raise
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
            return LlmTaskResult(output=parsed, run_id=run_id)
        except Exception as exc:
            if self._run_store is not None and run_id is not None:
                failed_metadata = metadata
                if isinstance(exc, LlmRateLimitError):
                    failed_metadata = {
                        **(metadata or {}),
                        "rate_limited": True,
                        "retry_after_seconds": exc.retry_after_seconds,
                    }
                await self._run_store.finish_run(
                    run_id=run_id,
                    status="failed",
                    raw_output=raw_json or {"text": raw_text},
                    error_message=str(exc),
                    metadata=failed_metadata,
                )
            raise

        if self._run_store is not None and run_id is not None:
            await self._run_store.finish_run(
                run_id=run_id,
                status="succeeded",
                raw_output=raw_json,
                metadata=metadata,
            )
        return LlmTaskResult(output=parsed, run_id=run_id)

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
                await invoke_chain(
                    self._repair_chain,
                    {
                        "schema_json": json.dumps(
                            output_model.model_json_schema(),
                            ensure_ascii=False,
                        ),
                        "validation_error": validation_error,
                        "invalid_output": invalid_output,
                    },
                )
            )
            await self._record_successful_request()
            repaired_json = parse_json_object(repaired_text)
            output_model.model_validate(repaired_json)
            return repaired_json, None
        except (ValueError, ValidationError) as exc:
            return None, str(exc)

    async def _record_successful_request(self) -> None:
        if self._cooldown_observer is not None:
            await self._cooldown_observer.clear_expired_ambiguous_observation()

    async def _finish_rate_limited_run(
        self,
        *,
        run_id: UUID | None,
        raw_text: str,
        raw_json: dict[str, Any] | None,
        error: LlmRateLimitError,
        metadata: dict[str, Any] | None,
    ) -> None:
        if self._run_store is None or run_id is None:
            return
        await self._run_store.finish_run(
            run_id=run_id,
            status="failed",
            raw_output=raw_json or {"text": raw_text},
            error_message=str(error),
            metadata={
                **(metadata or {}),
                "rate_limited": True,
                "retry_after_seconds": error.retry_after_seconds,
            },
        )


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


async def invoke_chain(chain: AsyncTextChain, variables: Mapping[str, Any]) -> Any:
    """Invoke an LLM chain and normalize provider rate-limit failures."""

    try:
        return await chain.ainvoke(variables)
    except RateLimitError as exc:
        raise LlmRateLimitError(
            str(exc),
            retry_after_seconds=parse_retry_after_seconds(exc),
        ) from exc


def parse_retry_after_seconds(error: RateLimitError) -> int | None:
    """Return a usable provider Retry-After duration, if supplied."""

    value = error.response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(1, int(float(value)))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(1, int((retry_at - datetime.now(UTC)).total_seconds()))
