"""LangChain-backed LLM task execution."""

from __future__ import annotations

import json
import time
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
from worker_ml.llm.contracts import LlmRunType
from worker_ml.llm.normalization import NormalizationResult
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runs import LlmRunStore
from worker_ml.llm.schema import prompt_schema_json
from worker_ml.llm.tasks import LLM_TASKS

OutputT = TypeVar("OutputT", bound=BaseModel)


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

        task = LLM_TASKS[run_type]
        output_model = task.output_model
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
        raw_json: Any = None
        normalized: NormalizationResult | None = None
        request_duration_seconds: float | None = None
        repair_duration_seconds: float | None = None
        try:
            request_started_at = time.monotonic()
            raw_text = str(await invoke_chain(self._chain_for(run_type), dict(variables)))
            request_duration_seconds = time.monotonic() - request_started_at
            await self._record_successful_request()
            raw_json = parse_json_response(raw_text, allow_array=task.allow_top_level_array)
            normalized = task.normalize(
                run_type=run_type,
                output=raw_json,
                variables=variables,
            )
            parsed = output_model.model_validate(normalized.output)
            _validate_resolution_coverage(
                run_type=run_type, output=normalized.output, variables=variables
            )
        except (ValueError, ValidationError) as exc:
            try:
                repair_started_at = time.monotonic()
                repaired_json, repair_error = await self._repair(
                    run_type=run_type,
                    output_model=output_model,
                    validation_error=str(exc),
                    invalid_output=raw_text,
                    variables=variables,
                )
                repair_duration_seconds = time.monotonic() - repair_started_at
            except LlmRateLimitError as rate_limit_exc:
                await self._finish_rate_limited_run(
                    run_id=run_id,
                    raw_text=raw_text,
                    raw_json=raw_json,
                    error=rate_limit_exc,
                    metadata=_timing_metadata(
                        metadata,
                        request_duration_seconds=request_duration_seconds,
                        repair_duration_seconds=repair_duration_seconds,
                    ),
                )
                raise
            if repaired_json is None:
                if self._run_store is not None and run_id is not None:
                    await self._run_store.finish_run(
                        run_id=run_id,
                        status="failed",
                        raw_output=raw_json or {"text": raw_text},
                        error_message=repair_error or str(exc),
                        metadata=_timing_metadata(
                            metadata,
                            request_duration_seconds=request_duration_seconds,
                            repair_duration_seconds=repair_duration_seconds,
                        ),
                    )
                raise ValueError(repair_error or str(exc)) from exc

            normalized = task.normalize(
                run_type=run_type,
                output=repaired_json,
                variables=variables,
            )
            parsed = output_model.model_validate(normalized.output)
            if self._run_store is not None and run_id is not None:
                await self._run_store.finish_run(
                    run_id=run_id,
                    status="repaired",
                    raw_output=raw_json or {"text": raw_text},
                    repaired_output=normalized.output,
                    metadata=_timing_metadata(
                        _normalization_metadata(metadata, normalized.actions),
                        request_duration_seconds=request_duration_seconds,
                        repair_duration_seconds=repair_duration_seconds,
                    ),
                )
            return LlmTaskResult(output=parsed, run_id=run_id)
        except Exception as exc:
            if self._run_store is not None and run_id is not None:
                if request_duration_seconds is None:
                    request_duration_seconds = time.monotonic() - request_started_at
                failed_metadata = _timing_metadata(
                    metadata,
                    request_duration_seconds=request_duration_seconds,
                    repair_duration_seconds=repair_duration_seconds,
                )
                if isinstance(exc, LlmRateLimitError):
                    failed_metadata = {
                        **failed_metadata,
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
            was_normalized = normalized is not None and bool(normalized.actions)
            await self._run_store.finish_run(
                run_id=run_id,
                status="repaired" if was_normalized else "succeeded",
                raw_output=raw_json,
                repaired_output=normalized.output if was_normalized else None,
                metadata=_timing_metadata(
                    _normalization_metadata(metadata, normalized.actions if normalized else []),
                    request_duration_seconds=request_duration_seconds,
                    repair_duration_seconds=repair_duration_seconds,
                ),
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
        run_type: LlmRunType,
        output_model: type[BaseModel],
        validation_error: str,
        invalid_output: str,
        variables: Mapping[str, Any],
    ) -> tuple[Any | None, str | None]:
        if self._repair_chain is None:
            return None, validation_error

        try:
            repaired_text = str(
                await invoke_chain(
                    self._repair_chain,
                    {
                        "schema_json": prompt_schema_json(output_model),
                        "validation_error": validation_error,
                        "invalid_output": invalid_output,
                    },
                )
            )
            await self._record_successful_request()
            task = LLM_TASKS[run_type]
            repaired_json = parse_json_response(
                repaired_text, allow_array=task.allow_top_level_array
            )
            normalized = task.normalize(
                run_type=run_type,
                output=repaired_json,
                variables=variables,
            )
            output_model.model_validate(normalized.output)
            _validate_resolution_coverage(
                run_type=run_type, output=normalized.output, variables=variables
            )
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
        "case_copy_update": settings.llm_case_copy_update_model,
        "case_coherence_audit": settings.llm_case_coherence_audit_model,
        "repair": settings.llm_repair_model,
    }


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM response that must contain one JSON object."""

    value = parse_json_response(text, allow_array=False)
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    return value


def parse_json_response(text: str, *, allow_array: bool) -> Any:
    """Parse an LLM response as JSON, optionally allowing a top-level array."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    value = json.loads(stripped)
    if not allow_array and not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    if allow_array and not isinstance(value, (dict, list)):
        raise ValueError("LLM output must be a JSON object or array")
    return value


def _validate_resolution_coverage(
    *,
    run_type: LlmRunType,
    output: Mapping[str, Any],
    variables: Mapping[str, Any],
) -> None:
    if run_type not in {"entity_resolution", "event_resolution"}:
        return

    decisions_key = "entities" if run_type == "entity_resolution" else "events"
    expected_refs = _expected_resolution_refs(variables)
    decisions = output.get(decisions_key)
    actual_refs: list[str] = []
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, dict):
                ref = decision.get("provisional_ref")
                if isinstance(ref, str):
                    actual_refs.append(ref)

    expected_set = set(expected_refs)
    actual_set = set(actual_refs)
    if actual_set == expected_set and len(actual_refs) == len(expected_refs):
        return

    missing = [ref for ref in expected_refs if ref not in actual_set]
    unexpected = [ref for ref in actual_refs if ref not in expected_set]
    details = []
    if missing:
        details.append(f"missing={missing}")
    if unexpected:
        details.append(f"unexpected={unexpected}")
    if len(actual_refs) != len(expected_refs) and not details:
        details.append(f"expected={len(expected_refs)} actual={len(actual_refs)}")
    raise ValueError(
        "resolution decisions must exactly cover provisional refs"
        + (f" ({'; '.join(details)})" if details else "")
    )


def _expected_resolution_refs(variables: Mapping[str, Any]) -> list[str]:
    value = variables.get("resolution_json")
    if not isinstance(value, str):
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    refs: list[str] = []
    for item in items:
        provisional = item.get("provisional") if isinstance(item, dict) else None
        ref = provisional.get("provisional_ref") if isinstance(provisional, dict) else None
        if not isinstance(ref, str):
            return []
        refs.append(ref)
    return refs


def _timing_metadata(
    metadata: dict[str, Any] | None,
    *,
    request_duration_seconds: float | None,
    repair_duration_seconds: float | None,
) -> dict[str, Any]:
    values = dict(metadata or {})
    if request_duration_seconds is not None:
        values["request_duration_seconds"] = round(request_duration_seconds, 6)
    if repair_duration_seconds is not None:
        values["repair_duration_seconds"] = round(repair_duration_seconds, 6)
    return values


def _normalization_metadata(
    metadata: dict[str, Any] | None,
    actions: list[str],
) -> dict[str, Any]:
    values = dict(metadata or {})
    if actions:
        values["normalization_actions"] = actions
    return values


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
