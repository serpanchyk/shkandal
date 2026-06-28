"""LangChain-backed LLM task execution."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol, TypeVar, cast
from uuid import UUID

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError
from pydantic import BaseModel, SecretStr, ValidationError

from worker_ml.config import MlConfig
from worker_ml.llm.contracts import LlmRunType
from worker_ml.llm.normalization import NormalizationResult
from worker_ml.llm.prompts import PromptRegistry
from worker_ml.llm.runs import LlmRunStore
from worker_ml.llm.schema import runtime_schema_json
from worker_ml.llm.tasks import LLM_TASKS

OutputT = TypeVar("OutputT", bound=BaseModel)
logger = logging.getLogger(__name__)


class LlmRateLimitError(RuntimeError):
    """Provider rate limit with the requested retry time."""

    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LlmDependencyUnavailableError(RuntimeError):
    """Raised when the configured LiteLLM proxy cannot be reached."""


@dataclass(frozen=True)
class LlmTaskResult:
    """Validated LLM output and its persisted run provenance."""

    output: BaseModel
    run_id: UUID | None


@dataclass(frozen=True)
class JsonParseResult:
    """Parsed JSON plus any narrowly applied syntax recovery."""

    value: Any
    escaped_control_characters: bool = False


@dataclass(frozen=True)
class RepairAttempt:
    """One repair response and its validation diagnostics."""

    output: Any | None
    raw_text: str | None
    error: str | None
    model_name: str | None = None
    schema_echo: bool = False


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
        max_completion_tokens=settings.llm_max_output_tokens,
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
                run_type: _task_chain(
                    registry=registry,
                    run_type=cast(LlmRunType, run_type),
                    prompt_name=run_type,
                    settings=settings,
                    model_name=model_name,
                )
                for run_type, model_name in aliases.items()
                if run_type != "repair"
            },
        )
        task_chains["case_creation_after_dropped_links"] = _task_chain(
            registry=registry,
            run_type="case_resolution",
            prompt_name="case_creation_after_dropped_links",
            settings=settings,
            model_name=aliases["case_resolution"],
        )
        repair_chain = cast(
            AsyncTextChain,
            registry.chat_prompt("repair")
            | create_litellm_chat_model(settings=settings, model_name=aliases["repair"]),
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
        prompt_name: str | None = None,
    ) -> LlmTaskResult:
        """Run an LLM task and return validated output with run provenance."""

        task = LLM_TASKS[run_type]
        output_model = task.output_model
        prompt = self._prompt_registry.get(prompt_name or run_type)
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
        resolved_model_name: str | None = None
        normalized: NormalizationResult | None = None
        parse_repaired = False
        request_duration_seconds: float | None = None
        repair_duration_seconds: float | None = None
        try:
            request_started_at = time.monotonic()
            provider_output = await invoke_chain(
                self._chain_for(prompt.name),
                dict(variables),
            )
            request_duration_seconds = time.monotonic() - request_started_at
            await self._record_successful_request()
            resolved_model_name = _provider_output_model_name(provider_output)
            raw_text, parse_result, parsed_model_name = _coerce_provider_output(
                provider_output,
                allow_array=task.allow_top_level_array,
            )
            resolved_model_name = parsed_model_name or resolved_model_name
            raw_json = parse_result.value
            parse_repaired = parse_result.escaped_control_characters
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
                repair_attempt = await self._repair(
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
                    model_name=resolved_model_name or model_name,
                    metadata=_timing_metadata(
                        metadata,
                        request_duration_seconds=request_duration_seconds,
                        repair_duration_seconds=repair_duration_seconds,
                    ),
                )
                raise
            if repair_attempt.output is None:
                fallback = task.invalid_output_fallback(repair_attempt.error or str(exc))
                failure_metadata = _repair_failure_metadata(
                    metadata,
                    repair_attempt,
                    request_duration_seconds=request_duration_seconds,
                    repair_duration_seconds=repair_duration_seconds,
                )
                if fallback is not None:
                    fallback_reason = repair_attempt.error or str(exc)
                    fallback_metadata = {
                        **failure_metadata,
                        "audit_fallback_reason": fallback_reason,
                    }
                    logger.warning(
                        "worker_ml_llm_audit_inconclusive_fallback",
                        extra={
                            "run_type": run_type,
                            "run_id": str(run_id) if run_id else None,
                            "reason": fallback_reason,
                        },
                    )
                    if self._run_store is not None and run_id is not None:
                        await self._run_store.finish_run(
                            run_id=run_id,
                            status="repaired",
                            model_name=resolved_model_name or model_name,
                            raw_output=_raw_provenance(raw_text, raw_json, parse_repaired),
                            repaired_output=fallback.model_dump(mode="json"),
                            metadata=fallback_metadata,
                        )
                    return LlmTaskResult(output=fallback, run_id=run_id)
                if self._run_store is not None and run_id is not None:
                    await self._run_store.finish_run(
                        run_id=run_id,
                        status="failed",
                        model_name=resolved_model_name or model_name,
                        raw_output=_raw_provenance(raw_text, raw_json, parse_repaired),
                        error_message=repair_attempt.error or str(exc),
                        metadata=failure_metadata,
                    )
                raise ValueError(repair_attempt.error or str(exc)) from exc

            normalized = task.normalize(
                run_type=run_type,
                output=repair_attempt.output,
                variables=variables,
            )
            parsed = output_model.model_validate(normalized.output)
            if self._run_store is not None and run_id is not None:
                await self._run_store.finish_run(
                    run_id=run_id,
                    status="repaired",
                    model_name=resolved_model_name or model_name,
                    raw_output=_raw_provenance(raw_text, raw_json, parse_repaired),
                    repaired_output=normalized.output,
                    metadata=_timing_metadata(
                        _repair_model_metadata(
                            _normalization_metadata(metadata, normalized.actions),
                            repair_attempt.model_name,
                        ),
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
                    model_name=resolved_model_name or model_name,
                    raw_output=_raw_provenance(raw_text, raw_json, parse_repaired),
                    error_message=str(exc),
                    metadata=failed_metadata,
                )
            raise

        if self._run_store is not None and run_id is not None:
            was_normalized = normalized is not None and bool(normalized.actions)
            was_repaired = parse_repaired or was_normalized
            success_metadata = _normalization_metadata(
                metadata, normalized.actions if normalized else []
            )
            if parse_repaired:
                success_metadata = {
                    **success_metadata,
                    "parse_repair": "escaped_control_characters",
                }
            await self._run_store.finish_run(
                run_id=run_id,
                status="repaired" if was_repaired else "succeeded",
                model_name=resolved_model_name or model_name,
                raw_output=_raw_provenance(raw_text, raw_json, parse_repaired),
                repaired_output=normalized.output if was_repaired else None,
                metadata=_timing_metadata(
                    success_metadata,
                    request_duration_seconds=request_duration_seconds,
                    repair_duration_seconds=repair_duration_seconds,
                ),
            )
        return LlmTaskResult(output=parsed, run_id=run_id)

    def _chain_for(self, run_type: str) -> AsyncTextChain:
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
    ) -> RepairAttempt:
        if self._repair_chain is None:
            return RepairAttempt(None, None, validation_error)

        repaired_text = ""
        repair_model_name: str | None = None
        try:
            repair_output = await invoke_chain(
                self._repair_chain,
                {
                    "schema_json": runtime_schema_json(output_model),
                    "validation_error": validation_error,
                    "invalid_output": invalid_output,
                },
            )
            repaired_text, repaired_parse_result, repair_model_name = _coerce_provider_output(
                repair_output,
                allow_array=LLM_TASKS[run_type].allow_top_level_array,
            )
            await self._record_successful_request()
            task = LLM_TASKS[run_type]
            repaired_json = repaired_parse_result.value
            if _is_schema_echo(repaired_json):
                return RepairAttempt(
                    None,
                    repaired_text,
                    "repair response echoed JSON schema",
                    model_name=repair_model_name,
                    schema_echo=True,
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
            return RepairAttempt(repaired_json, repaired_text, None, model_name=repair_model_name)
        except (ValueError, ValidationError) as exc:
            return RepairAttempt(None, repaired_text, str(exc), model_name=repair_model_name)

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
        model_name: str | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        if self._run_store is None or run_id is None:
            return
        await self._run_store.finish_run(
            run_id=run_id,
            status="failed",
            model_name=model_name,
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
        "article_gate": settings.llm_article_gate_model,
        "article_card": settings.llm_article_card_model,
        "case_resolution": settings.llm_case_resolution_model,
        "case_link_audit": settings.llm_case_coherence_audit_model,
        "entity_resolution": settings.llm_entity_resolution_model,
        "event_resolution": settings.llm_event_resolution_model,
        "refresh_case": settings.llm_refresh_case_model,
        "case_coherence_audit": settings.llm_case_coherence_audit_model,
        "case_public_interest_audit": settings.llm_case_public_interest_audit_model,
        "case_duplicate_audit": settings.llm_case_duplicate_audit_model,
        "repair": settings.llm_repair_model,
    }


def _task_chain(
    *,
    registry: PromptRegistry,
    run_type: LlmRunType,
    prompt_name: str,
    settings: MlConfig,
    model_name: str,
) -> AsyncTextChain:
    """Create a text or guarded structured-output task chain."""

    model = create_litellm_chat_model(settings=settings, model_name=model_name)
    if settings.llm_structured_output_mode == "disabled":
        return cast(AsyncTextChain, registry.chat_prompt(prompt_name) | model)

    task = LLM_TASKS[run_type]
    method: Literal["function_calling", "json_schema"] = (
        "function_calling"
        if settings.llm_structured_output_mode == "tool_calling"
        else "json_schema"
    )
    structured_model = model.with_structured_output(
        task.output_model,
        method=method,
        include_raw=True,
    )
    return cast(AsyncTextChain, registry.chat_prompt(prompt_name) | structured_model)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse an LLM response that must contain one JSON object."""

    value = parse_json_response(text, allow_array=False)
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    return value


def parse_json_response(text: str, *, allow_array: bool) -> Any:
    """Parse an LLM response as JSON, optionally allowing a top-level array."""

    return _parse_json_response(text, allow_array=allow_array).value


def _parse_json_response(text: str, *, allow_array: bool) -> JsonParseResult:
    """Parse JSON with a fallback only for unescaped control characters."""

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```").strip()
        stripped = stripped.removesuffix("```").strip()
    escaped_control_characters = False
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        if not exc.msg.startswith("Invalid control character"):
            raise
        repaired = _escape_control_characters_inside_json_strings(stripped)
        value = json.loads(repaired)
        escaped_control_characters = True
    if not allow_array and not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    if allow_array and not isinstance(value, (dict, list)):
        raise ValueError("LLM output must be a JSON object or array")
    return JsonParseResult(value, escaped_control_characters)


def _coerce_provider_output(
    output: Any,
    *,
    allow_array: bool,
) -> tuple[str, JsonParseResult, str | None]:
    """Accept text-mode JSON or already-validated structured model output."""

    output, model_name = _unwrap_provider_output(output)
    if isinstance(output, BaseModel):
        value = output.model_dump(mode="json")
        return json.dumps(value, ensure_ascii=False), JsonParseResult(value), model_name
    if isinstance(output, dict):
        return json.dumps(output, ensure_ascii=False), JsonParseResult(output), model_name
    if allow_array and isinstance(output, list):
        return json.dumps(output, ensure_ascii=False), JsonParseResult(output), model_name
    text = str(output)
    return text, _parse_json_response(text, allow_array=allow_array), model_name


def _unwrap_provider_output(output: Any) -> tuple[Any, str | None]:
    """Return the task payload and resolved provider model from a LangChain response."""

    if isinstance(output, BaseMessage):
        return output.content, _resolved_model_name(output)
    if (
        isinstance(output, dict)
        and isinstance(output.get("raw"), BaseMessage)
        and {"parsed", "parsing_error"}.issubset(output)
    ):
        raw = cast(BaseMessage, output["raw"])
        parsed = output.get("parsed")
        return (parsed if parsed is not None else raw.content), _resolved_model_name(raw)
    return output, None


def _provider_output_model_name(output: Any) -> str | None:
    """Return provider model metadata before parsing can fail."""

    return _unwrap_provider_output(output)[1]


def _resolved_model_name(message: BaseMessage) -> str | None:
    """Extract the provider-returned model identifier without normalizing it."""

    value = message.response_metadata.get("model_name")
    return value if isinstance(value, str) and value else None


def _escape_control_characters_inside_json_strings(text: str) -> str:
    """Escape raw U+0000-U+001F characters only while inside JSON strings."""

    chars: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string and ord(char) < 0x20:
            chars.append(_json_control_character_escape(char))
            escaped = False
            continue
        chars.append(char)
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
    return "".join(chars)


def _json_control_character_escape(char: str) -> str:
    return {
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }.get(char, f"\\u{ord(char):04x}")


def _is_schema_echo(value: Any) -> bool:
    """Detect repair responses that return a JSON Schema instead of task output."""

    return isinstance(value, dict) and (
        "$schema" in value
        or "$defs" in value
        or (value.get("type") in {"object", "array"} and isinstance(value.get("properties"), dict))
    )


def _repair_failure_metadata(
    metadata: dict[str, Any] | None,
    attempt: RepairAttempt,
    *,
    request_duration_seconds: float | None,
    repair_duration_seconds: float | None,
) -> dict[str, Any]:
    result = _timing_metadata(
        _repair_model_metadata(metadata, attempt.model_name),
        request_duration_seconds=request_duration_seconds,
        repair_duration_seconds=repair_duration_seconds,
    )
    if attempt.raw_text is not None:
        result["repair_attempt_output"] = attempt.raw_text
    if attempt.schema_echo:
        result["schema_echo"] = True
    if attempt.error:
        result["repair_failure_reason"] = attempt.error
    return result


def _repair_model_metadata(
    metadata: dict[str, Any] | None,
    repair_model_name: str | None,
) -> dict[str, Any]:
    """Attach the resolved repair model when the repair provider returned one."""

    result = dict(metadata or {})
    if repair_model_name is not None:
        result["repair_model_name"] = repair_model_name
    return result


def _raw_provenance(raw_text: str, raw_json: Any, preserve_text: bool) -> Any:
    """Return exact provider text when parsing required syntax recovery."""

    return {"text": raw_text} if preserve_text or raw_json is None else raw_json


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
    """Invoke an LLM chain and normalize provider dependency failures."""

    try:
        return await chain.ainvoke(variables)
    except RateLimitError as exc:
        raise LlmRateLimitError(
            str(exc),
            retry_after_seconds=parse_retry_after_seconds(exc),
        ) from exc
    except APITimeoutError:
        raise
    except APIConnectionError as exc:
        raise LlmDependencyUnavailableError("LiteLLM proxy unavailable") from exc


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
