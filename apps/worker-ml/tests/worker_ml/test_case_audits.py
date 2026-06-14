import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest
from shkandal_database.jobs import ClaimedJob
from shkandal_database.models import Case
from worker_ml import case_audits
from worker_ml.case_audits import CaseCoherenceAuditJobHandler, _validate_article_coverage
from worker_ml.llm.contracts import CaseCoherenceAuditOutput
from worker_ml.llm.runner import LlmTaskResult, LlmTaskRunner


def _output(article_ids: list[str]) -> CaseCoherenceAuditOutput:
    stories = [
        {
            "story_ref": "original",
            "title_uk": "Справа",
            "summary_uk": "Опис.",
            "article_ids": article_ids,
            "reason_uk": "Одна історія.",
        }
    ]
    return CaseCoherenceAuditOutput.model_validate(
        {
            "outcome": "coherent",
            "reason_uk": "Одна справа.",
            "stories": stories,
        }
    )


def _job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        job_type="audit_case_coherence",
        article_id=None,
        case_id=uuid4(),
        payload={},
        attempt_count=1,
        max_attempts=3,
    )


def _handler(
    *outputs: CaseCoherenceAuditOutput,
    card_batch_size: int = 40,
) -> tuple[CaseCoherenceAuditJobHandler, AsyncMock]:
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        side_effect=[LlmTaskResult(output=output, run_id=uuid4()) for output in outputs]
    )
    handler = CaseCoherenceAuditJobHandler(
        Mock(),
        runner,
        Mock(),
        model_name="shkandal-case-coherence-audit",
        card_batch_size=card_batch_size,
    )
    return handler, runner.run_with_provenance


def _cards(*article_ids: str) -> list[dict[str, str]]:
    return [{"article_id": article_id, "title_uk": article_id} for article_id in article_ids]


def _inconclusive() -> CaseCoherenceAuditOutput:
    return CaseCoherenceAuditOutput(
        outcome="inconclusive",
        reason_uk="Недостатньо доказів.",
        stories=[],
    )


def _call_payload(call: Any) -> dict[str, object]:
    variables = call.kwargs["variables"]
    return cast(dict[str, object], json.loads(variables["case_json"]))


def _session_context(session: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _split_output(article_a: str, article_b: str) -> CaseCoherenceAuditOutput:
    return CaseCoherenceAuditOutput.model_validate(
        {
            "outcome": "split",
            "reason_uk": "Дві справи.",
            "stories": [
                {
                    "story_ref": "original",
                    "title_uk": "Перша справа",
                    "summary_uk": "Опис.",
                    "article_ids": [article_a, article_b],
                    "reason_uk": "Перша історія.",
                },
                {
                    "story_ref": "story_other",
                    "title_uk": "Друга справа",
                    "summary_uk": "Опис.",
                    "article_ids": [article_b],
                    "reason_uk": "Друга історія.",
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_audit_retries_missing_article_coverage_and_accepts_correction() -> None:
    article_a = str(uuid4())
    article_b = str(uuid4())
    handler, invoke = _handler(_output([article_a]), _output([article_a, article_b]))

    output, _ = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(article_a, article_b),
    )

    assert output.stories[0].article_ids == [article_a, article_b]
    assert invoke.await_count == 2
    retry_payload = _call_payload(invoke.await_args_list[1])
    assert retry_payload["article_cards"] == _cards(article_a, article_b)
    assert retry_payload["previous_invalid_audit"] == _output([article_a]).model_dump(mode="json")
    assert retry_payload["coverage_validation_error"] == (
        f"audit omits article ids: ['{article_b}']"
    )
    assert invoke.await_args_list[1].kwargs["metadata"]["phase"] == "final_coverage_retry"


@pytest.mark.asyncio
async def test_audit_retries_unknown_article_coverage_and_accepts_correction() -> None:
    article_id = str(uuid4())
    unknown_id = str(uuid4())
    handler, invoke = _handler(_output([article_id, unknown_id]), _output([article_id]))

    output, _ = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(article_id),
    )

    assert output.stories[0].article_ids == [article_id]
    retry_payload = _call_payload(invoke.await_args_list[1])
    assert retry_payload["coverage_validation_error"] == (
        f"audit references unknown article ids: ['{unknown_id}']"
    )


@pytest.mark.asyncio
async def test_audit_becomes_inconclusive_after_two_invalid_coverage_responses() -> None:
    article_a = str(uuid4())
    article_b = str(uuid4())
    handler, invoke = _handler(_output([article_a]), _output([article_a]))

    output, run_id = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(article_a, article_b),
    )

    assert output.outcome == "inconclusive"
    assert output.stories == []
    assert run_id is not None
    assert invoke.await_count == 2


@pytest.mark.asyncio
async def test_batch_coverage_is_corrected_before_reconciliation() -> None:
    article_ids = [str(uuid4()) for _ in range(4)]
    handler, invoke = _handler(
        _output([article_ids[0]]),
        _output(article_ids[:2]),
        _output(article_ids[2:]),
        _output(article_ids),
        card_batch_size=2,
    )

    output, _ = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(*article_ids),
    )

    assert output.outcome == "coherent"
    phases = [call.kwargs["metadata"]["phase"] for call in invoke.await_args_list]
    assert phases == ["batch_1", "batch_1_coverage_retry", "batch_2", "reconciliation"]
    reconciliation_payload = _call_payload(invoke.await_args_list[3])
    batch_audits = reconciliation_payload["batch_audits"]
    assert isinstance(batch_audits, list)
    assert batch_audits[0] == _output(article_ids[:2]).model_dump(mode="json")


@pytest.mark.asyncio
async def test_reconciliation_retry_receives_all_original_article_cards() -> None:
    article_ids = [str(uuid4()) for _ in range(4)]
    handler, invoke = _handler(
        _output(article_ids[:2]),
        _output(article_ids[2:]),
        _output(article_ids[:3]),
        _output(article_ids),
        card_batch_size=2,
    )
    cards = _cards(*article_ids)

    output, _ = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=cards,
    )

    assert output.outcome == "coherent"
    retry_call = invoke.await_args_list[3]
    assert retry_call.kwargs["metadata"]["phase"] == "reconciliation_coverage_retry"
    assert _call_payload(retry_call)["article_cards"] == cards


@pytest.mark.asyncio
async def test_model_selected_inconclusive_audit_is_not_retried() -> None:
    handler, invoke = _handler(_inconclusive())

    output, run_id = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(str(uuid4())),
    )

    assert output == _inconclusive()
    assert run_id is not None
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_audit_is_not_retried() -> None:
    article_id = str(uuid4())
    handler, invoke = _handler(_output([article_id]))

    output, run_id = await handler._run_audit(
        job=_job(),
        case_context={"case_id": str(uuid4())},
        cards=_cards(article_id),
    )

    assert output == _output([article_id])
    assert run_id is not None
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_coverage_fallback_is_recorded_without_decisive_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_a = str(uuid4())
    article_b = str(uuid4())
    case = Case(
        id=uuid4(),
        slug="case-a",
        title_uk="Справа",
        summary_uk="Опис.",
        status="active",
        evidence_revision=2,
    )
    read_session = MagicMock()
    read_session.get = AsyncMock(return_value=case)
    write_session = MagicMock()
    write_session.get = AsyncMock(return_value=case)
    write_session.commit = AsyncMock()
    session_factory = Mock(
        side_effect=[_session_context(read_session), _session_context(write_session)]
    )
    runner = Mock(spec=LlmTaskRunner)
    runner.run_with_provenance = AsyncMock(
        side_effect=[
            LlmTaskResult(output=_output([article_a]), run_id=uuid4()),
            LlmTaskResult(output=_output([article_a]), run_id=uuid4()),
        ]
    )
    record_audit = AsyncMock()
    apply_decisive_audit = AsyncMock()
    monkeypatch.setattr(
        case_audits, "_audit_cards", AsyncMock(return_value=_cards(article_a, article_b))
    )
    monkeypatch.setattr(case_audits, "_try_case_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(case_audits, "_try_lock", AsyncMock(return_value=True))
    monkeypatch.setattr(case_audits, "_record_audit", record_audit)
    monkeypatch.setattr(case_audits, "_apply_decisive_audit", apply_decisive_audit)
    handler = CaseCoherenceAuditJobHandler(
        session_factory,
        runner,
        Mock(),
        model_name="shkandal-case-coherence-audit",
        card_batch_size=40,
    )

    output = await handler.handle(_job())

    assert output is not None
    assert output.outcome == "inconclusive"
    record_audit.assert_awaited_once()
    apply_decisive_audit.assert_not_awaited()
    write_session.commit.assert_awaited_once()


def test_audit_coverage_requires_every_input_article() -> None:
    article_a = str(uuid4())
    article_b = str(uuid4())

    with pytest.raises(ValueError, match="omits article ids"):
        _validate_article_coverage(_output([article_a]), {article_a, article_b})


def test_audit_coverage_rejects_unknown_articles() -> None:
    article_a = str(uuid4())

    with pytest.raises(ValueError, match="unknown article ids"):
        _validate_article_coverage(_output([article_a, str(uuid4())]), {article_a})


def test_inconclusive_audit_needs_no_article_assignments() -> None:
    output = CaseCoherenceAuditOutput.model_validate(
        {"outcome": "inconclusive", "reason_uk": "Недостатньо доказів.", "stories": []}
    )

    _validate_article_coverage(output, {str(uuid4())})


def test_audit_coverage_allows_overlapping_article_assignments() -> None:
    article_a = str(uuid4())
    article_b = str(uuid4())

    _validate_article_coverage(_split_output(article_a, article_b), {article_a, article_b})
