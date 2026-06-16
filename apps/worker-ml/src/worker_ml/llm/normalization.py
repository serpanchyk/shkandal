"""Conservative deterministic normalization for structured LLM output."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from worker_ml.llm.contracts import LlmRunType

ENTITY_TYPES = {
    "person",
    "organization",
    "institution",
    "company",
    "political_party",
    "informal_group",
    "unknown_actor",
    "other",
}
ENTITY_TYPE_ALIASES = {
    "government": "institution",
    "government_agency": "institution",
    "state_body": "institution",
    "ngo": "organization",
    "nonprofit": "organization",
    "party": "political_party",
    "politician": "person",
    "public_official": "person",
}
NOISE_REASONS = {
    "culture",
    "opinion",
    "statistics",
    "pr",
    "advertising",
    "generic_news",
    "ranking",
    "explainer",
    "lifestyle",
    "broad_analysis",
    "diplomacy",
    "policy_law",
    "routine_regulatory",
    "routine_crime",
    "foreign_no_ukraine_nexus",
}
SAFE_REJECTION_REASON_UK = "Не стосується пов'язаної справи."
INSUFFICIENT_IDENTITY_REASON_UK = (
    "Неможливо безпечно підтвердити тотожність із отриманими кандидатами."
)
TRAILING_TRUNCATION_CHARS = " \t\r\n,;:.-"
SHORT_TEXT_LIMITS: dict[LlmRunType, dict[str, int]] = {
    "article_card": {
        "case_diagnosis.ukraine_nexus_uk": 240,
        "case_diagnosis.concrete_story_core_uk": 240,
        "case_diagnosis.public_accountability_anchor_uk": 240,
        "case_diagnosis.continuation_potential_uk": 240,
        "case_decision_reason_uk": 320,
    },
    "case_resolution": {
        "diagnosis.article_story_core_uk": 240,
        "diagnosis.specific_case_core_uk": 240,
        "diagnosis.only_broad_overlap_uk": 240,
        "diagnosis.case_coherence_test_uk": 240,
        "diagnosis.new_case_core_uk": 240,
        "diagnosis.broad_theme_warning_uk": 240,
        "decision_reason_uk": 320,
    },
    "case_link_audit": {
        "diagnosis.article_story_core_uk": 240,
        "diagnosis.case_story_core_uk": 240,
        "diagnosis.shared_specific_core_uk": 240,
        "diagnosis.only_broad_overlap_uk": 240,
        "diagnosis.coherence_test_uk": 240,
        "reason_uk": 320,
    },
    "case_coherence_audit": {
        "diagnosis.shared_specific_core_uk": 240,
        "diagnosis.shared_only_broad_theme_uk": 240,
        "diagnosis.coherence_test_uk": 240,
        "reason_uk": 320,
    },
    "case_public_interest_audit": {
        "diagnosis.concrete_story_core_uk": 240,
        "diagnosis.public_interest_anchor_uk": 240,
        "diagnosis.durability_signal_uk": 240,
        "reason_uk": 320,
    },
    "case_duplicate_audit": {
        "diagnosis.case_a_core_uk": 240,
        "diagnosis.case_b_core_uk": 240,
        "diagnosis.shared_specific_core_uk": 240,
        "diagnosis.relation_anchor_uk": 240,
        "diagnosis.only_broad_overlap_uk": 240,
        "reason_uk": 320,
    },
    "entity_resolution": {
        "entities[].diagnosis.identity_match_evidence_uk": 240,
        "entities[].diagnosis.identity_conflict_uk": 240,
        "entities[].diagnosis.rejection_signal_uk": 240,
        "entities[].reason_uk": 320,
    },
    "event_resolution": {
        "events[].diagnosis.occurrence_core_uk": 240,
        "events[].diagnosis.anchor_summary_uk": 240,
        "events[].diagnosis.candidate_match_evidence_uk": 240,
        "events[].diagnosis.anchor_conflict_uk": 240,
        "events[].diagnosis.temporal_scope_check_uk": 240,
        "events[].diagnosis.future_date_warning_uk": 240,
        "events[].diagnosis.rejection_signal_uk": 240,
        "events[].reason_uk": 320,
    },
}


@dataclass(frozen=True)
class NormalizationResult:
    """Normalized JSON and descriptions of deterministic changes."""

    output: dict[str, Any]
    actions: list[str]


def normalize_llm_output(
    *,
    run_type: LlmRunType,
    output: dict[str, Any] | list[Any],
    variables: Mapping[str, Any],
) -> NormalizationResult:
    """Normalize only contract shape that does not require inventing facts."""

    normalized = copy.deepcopy(output)
    actions: list[str] = []
    if run_type == "article_card":
        if not isinstance(normalized, dict):
            raise ValueError("article card output must be a JSON object")
        _normalize_article_card(normalized, actions)
    elif run_type == "case_coherence_audit":
        if not isinstance(normalized, dict):
            raise ValueError("case coherence audit output must be a JSON object")
        _normalize_case_coherence_audit(normalized, actions)
    elif run_type in {"entity_resolution", "event_resolution"}:
        decisions_key = "entities" if run_type == "entity_resolution" else "events"
        if isinstance(normalized, list):
            normalized = {decisions_key: normalized}
            actions.append(f"wrap {decisions_key} array")
        if not isinstance(normalized, dict):
            raise ValueError("resolution output must be a JSON object or array")
        _normalize_resolution_refs(normalized, variables, run_type, actions)
        _normalize_invalid_candidate_links(normalized, variables, run_type, actions)
        decisions = normalized.get(decisions_key)
        if isinstance(decisions, list):
            for index, decision in enumerate(decisions):
                if not isinstance(decision, dict):
                    continue
                if run_type == "entity_resolution":
                    _normalize_entity_decision(decision, actions, f"entities[{index}]")
                else:
                    _normalize_event_decision(decision, actions, f"events[{index}]")
    elif run_type == "case_copy_update":
        if not isinstance(normalized, dict):
            raise ValueError("case copy update output must be a JSON object")
        if normalized.get("title_action") == "keep":
            _set(normalized, "replacement_title_uk", None, actions, "clear kept replacement title")
    elif not isinstance(normalized, dict):
        raise ValueError("LLM output must be a JSON object")
    _truncate_short_text_fields(normalized, run_type, actions)
    return NormalizationResult(output=normalized, actions=actions)


def _normalize_article_card(output: dict[str, Any], actions: list[str]) -> None:
    if not isinstance(output.get("case_diagnosis"), dict):
        _set(
            output,
            "case_diagnosis",
            {
                "ukraine_nexus_uk": None,
                "concrete_story_core_uk": None,
                "public_accountability_anchor_uk": None,
                "continuation_potential_uk": None,
                "noise_signals_uk": [],
            },
            actions,
            "default case diagnosis",
        )
    if output.get("is_case_candidate") is False:
        if output.get("noise_reason") not in NOISE_REASONS:
            _set(output, "noise_reason", "generic_news", actions, "default non-case noise reason")
        _set(output, "main_event_title_uk", None, actions, "clear non-case main event")
        _set(output, "entities", [], actions, "clear non-case entities")
        _set(output, "events", [], actions, "clear non-case events")
        _set(output, "case_signature_terms", [], actions, "clear non-case signature terms")
        return

    if output.get("is_case_candidate") is True:
        _set(output, "noise_reason", None, actions, "clear case-candidate noise reason")
    _trim_list(output, "entities", 8, actions)
    _trim_list(output, "events", 3, actions)
    _trim_list(output, "case_signature_terms", 8, actions)
    entities = output.get("entities")
    if isinstance(entities, list):
        for index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            _normalize_provisional_ref(entity, "entity", index + 1, actions)
            _normalize_entity_type(entity, actions, f"entities[{index}]")
            _normalize_aliases(entity, actions, f"entities[{index}]")
    events = output.get("events")
    if isinstance(events, list):
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            _normalize_provisional_ref(event, "event", index + 1, actions)
            _normalize_date(event, actions, f"events[{index}]")


def _normalize_entity_decision(decision: dict[str, Any], actions: list[str], path: str) -> None:
    if not isinstance(decision.get("diagnosis"), dict):
        _set(
            decision,
            "diagnosis",
            {
                "is_named_stable_actor": False,
                "material_case_ids": [],
                "identity_match_evidence_uk": None,
                "identity_conflict_uk": None,
                "rejection_signal_uk": None,
            },
            actions,
            f"{path}: default diagnosis",
        )
    if "new_canonical_name_en" in decision:
        decision.pop("new_canonical_name_en")
        actions.append(f"{path}: remove unsupported English canonical name")
    _normalize_entity_type(decision, actions, path)
    _normalize_aliases(decision, actions, path)
    action = decision.get("action")
    assignments = decision.get("case_assignments")
    if action != "reject" and not assignments:
        _convert_to_reject(
            decision,
            actions,
            path,
            clear_fields=("existing_entity_id", "new_canonical_name_uk"),
        )
        return
    if action == "reject":
        _set(decision, "existing_entity_id", None, actions, f"{path}: clear rejected entity id")
        _set(
            decision,
            "new_canonical_name_uk",
            None,
            actions,
            f"{path}: clear rejected canonical name",
        )
        _set(decision, "case_assignments", [], actions, f"{path}: clear rejected assignments")
        _default_rejection(decision, actions, path)
        return
    _set(decision, "rejection_reason", None, actions, f"{path}: clear accepted rejection reason")
    if action == "create_new":
        _set(decision, "existing_entity_id", None, actions, f"{path}: clear new entity id")
    elif action not in {"rename_existing"}:
        _set(
            decision,
            "new_canonical_name_uk",
            None,
            actions,
            f"{path}: clear forbidden canonical name",
        )


def _normalize_event_decision(decision: dict[str, Any], actions: list[str], path: str) -> None:
    if not isinstance(decision.get("diagnosis"), dict):
        _set(
            decision,
            "diagnosis",
            {
                "is_concrete_occurrence": False,
                "occurrence_core_uk": None,
                "anchor_summary_uk": None,
                "candidate_match_evidence_uk": None,
                "anchor_conflict_uk": None,
                "temporal_scope_check_uk": "Не вдалося безпечно перевірити часові межі події.",
                "future_date_warning_uk": None,
                "material_case_ids": [],
                "rejection_signal_uk": None,
            },
            actions,
            f"{path}: default diagnosis",
        )
    _normalize_date(decision, actions, path)
    action = decision.get("action")
    assignments = decision.get("case_assignments")
    if action != "reject" and not assignments:
        _convert_to_reject(
            decision,
            actions,
            path,
            clear_fields=("existing_event_id", "new_title_uk"),
        )
        return
    if action == "reject":
        _set(decision, "existing_event_id", None, actions, f"{path}: clear rejected event id")
        _set(decision, "new_title_uk", None, actions, f"{path}: clear rejected event title")
        _set(decision, "case_assignments", [], actions, f"{path}: clear rejected assignments")
        _default_rejection(decision, actions, path)
        return
    _set(decision, "rejection_reason", None, actions, f"{path}: clear accepted rejection reason")
    if action == "create_new":
        _set(decision, "existing_event_id", None, actions, f"{path}: clear new event id")
    elif action == "link_existing":
        _set(decision, "new_title_uk", None, actions, f"{path}: clear linked event title")


def _normalize_resolution_refs(
    output: dict[str, Any],
    variables: Mapping[str, Any],
    run_type: LlmRunType,
    actions: list[str],
) -> None:
    decisions_key = "entities" if run_type == "entity_resolution" else "events"
    decisions = output.get(decisions_key)
    expected_refs = _expected_resolution_refs(variables)
    if not isinstance(decisions, list) or len(decisions) != len(expected_refs):
        return
    actual_refs = [
        decision.get("provisional_ref") if isinstance(decision, dict) else None
        for decision in decisions
    ]
    if actual_refs == expected_refs or (
        all(isinstance(ref, str) for ref in actual_refs) and set(actual_refs) == set(expected_refs)
    ):
        return
    if len(set(expected_refs)) != len(expected_refs):
        return
    for index, (decision, expected_ref) in enumerate(zip(decisions, expected_refs, strict=True)):
        if isinstance(decision, dict):
            _set(
                decision,
                "provisional_ref",
                expected_ref,
                actions,
                f"{decisions_key}[{index}]: align provisional ref",
            )


def _normalize_invalid_candidate_links(
    output: dict[str, Any],
    variables: Mapping[str, Any],
    run_type: LlmRunType,
    actions: list[str],
) -> None:
    decisions_key = "entities" if run_type == "entity_resolution" else "events"
    id_key = "existing_entity_id" if run_type == "entity_resolution" else "existing_event_id"
    title_key = "new_canonical_name_uk" if run_type == "entity_resolution" else "new_title_uk"
    decisions = output.get(decisions_key)
    if not isinstance(decisions, list):
        return
    candidate_ids = _candidate_ids_by_ref(variables, id_key)
    if not candidate_ids:
        return
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            continue
        action = decision.get("action")
        if action == "reject" or action == "create_new":
            continue
        ref = decision.get("provisional_ref")
        existing_id = decision.get(id_key)
        if (
            not isinstance(ref, str)
            or not isinstance(existing_id, str)
            or existing_id in candidate_ids.get(ref, set())
        ):
            continue
        path = f"{decisions_key}[{index}]"
        _convert_to_insufficient_identity_reject(
            decision,
            actions,
            path,
            id_key=id_key,
            title_key=title_key,
        )


def _candidate_ids_by_ref(variables: Mapping[str, Any], id_key: str) -> dict[str, set[str]]:
    value = variables.get("resolution_json")
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {}
    candidate_ids: dict[str, set[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        provisional = item.get("provisional")
        ref = provisional.get("provisional_ref") if isinstance(provisional, dict) else None
        candidates = item.get("candidates")
        if not isinstance(ref, str) or not isinstance(candidates, list):
            continue
        candidate_ids[ref] = {
            candidate[id_key]
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get(id_key), str)
        }
    return candidate_ids


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


def _normalize_provisional_ref(
    item: dict[str, Any], prefix: str, index: int, actions: list[str]
) -> None:
    ref = item.get("provisional_ref")
    if not isinstance(ref, str) or re.fullmatch(rf"{prefix}_[a-z0-9_]+", ref) is None:
        _set(item, "provisional_ref", f"{prefix}_{index}", actions, f"generate {prefix} ref")


def _normalize_entity_type(item: dict[str, Any], actions: list[str], path: str) -> None:
    value = item.get("entity_type")
    if value is None:
        return
    normalized = ENTITY_TYPE_ALIASES.get(str(value), str(value))
    if normalized not in ENTITY_TYPES:
        normalized = "other"
    _set(item, "entity_type", normalized, actions, f"{path}: normalize entity type")


def _normalize_aliases(item: dict[str, Any], actions: list[str], path: str) -> None:
    if item.get("aliases") is None:
        _set(item, "aliases", [], actions, f"{path}: replace null aliases")
    _trim_list(item, "aliases", 8, actions, path=path)


def _normalize_date(item: dict[str, Any], actions: list[str], path: str) -> None:
    value = item.get("event_date")
    precision = None
    if isinstance(value, str):
        for candidate, pattern in (
            ("day", r"\d{4}-\d{2}-\d{2}"),
            ("month", r"\d{4}-\d{2}"),
            ("year", r"\d{4}"),
        ):
            if re.fullmatch(pattern, value):
                precision = candidate
                break
    if precision is None:
        _set(item, "event_date", None, actions, f"{path}: clear invalid event date")
        _set(item, "date_evidence_text", None, actions, f"{path}: clear invalid date evidence")
        precision = "unknown"
    _set(item, "event_date_precision", precision, actions, f"{path}: infer event date precision")


def _normalize_case_coherence_audit(output: dict[str, Any], actions: list[str]) -> None:
    reason_uk = output.get("reason_uk")
    stories = output.get("stories")
    if not isinstance(stories, list):
        return
    for index, story in enumerate(stories):
        if not isinstance(story, dict):
            continue
        if not story.get("reason_uk") and isinstance(reason_uk, str) and reason_uk.strip():
            _set(
                story,
                "reason_uk",
                reason_uk,
                actions,
                f"stories[{index}]: inherit audit reason",
            )
        article_ids = story.get("article_ids")
        if isinstance(article_ids, list):
            deduped: list[Any] = []
            seen: set[Any] = set()
            for article_id in article_ids:
                if article_id in seen:
                    continue
                seen.add(article_id)
                deduped.append(article_id)
            if deduped != article_ids:
                _set(
                    story,
                    "article_ids",
                    deduped,
                    actions,
                    f"stories[{index}]: dedupe article ids",
                )


def _convert_to_reject(
    decision: dict[str, Any],
    actions: list[str],
    path: str,
    *,
    clear_fields: tuple[str, ...],
) -> None:
    _set(decision, "action", "reject", actions, f"{path}: reject without Case assignments")
    for field in clear_fields:
        _set(decision, field, None, actions, f"{path}: clear rejected identity")
    _set(decision, "case_assignments", [], actions, f"{path}: clear rejected assignments")
    _default_rejection(decision, actions, path)


def _convert_to_insufficient_identity_reject(
    decision: dict[str, Any],
    actions: list[str],
    path: str,
    *,
    id_key: str,
    title_key: str,
) -> None:
    _set(decision, "action", "reject", actions, f"{path}: reject non-candidate identity")
    _set(decision, id_key, None, actions, f"{path}: clear non-candidate identity")
    _set(decision, title_key, None, actions, f"{path}: clear rejected identity proposal")
    _set(decision, "case_assignments", [], actions, f"{path}: clear rejected assignments")
    _set(
        decision,
        "rejection_reason",
        "insufficient_identity",
        actions,
        f"{path}: mark insufficient identity",
    )
    _set(
        decision,
        "reason_uk",
        INSUFFICIENT_IDENTITY_REASON_UK,
        actions,
        f"{path}: explain insufficient identity",
    )
    diagnosis = decision.get("diagnosis")
    if isinstance(diagnosis, dict):
        _set(
            diagnosis,
            "rejection_signal_uk",
            INSUFFICIENT_IDENTITY_REASON_UK,
            actions,
            f"{path}: set identity rejection signal",
        )


def _default_rejection(decision: dict[str, Any], actions: list[str], path: str) -> None:
    if not decision.get("rejection_reason"):
        _set(
            decision,
            "rejection_reason",
            "not_case_relevant",
            actions,
            f"{path}: default rejection reason",
        )
    if not decision.get("reason_uk"):
        _set(decision, "reason_uk", SAFE_REJECTION_REASON_UK, actions, f"{path}: default reason")


def _truncate_short_text_fields(
    output: dict[str, Any],
    run_type: LlmRunType,
    actions: list[str],
) -> None:
    limits = SHORT_TEXT_LIMITS.get(run_type)
    if not limits:
        return
    for path, limit in limits.items():
        _truncate_path(output, path.split("."), limit, actions)


def _truncate_path(
    current: Any,
    segments: list[str],
    limit: int,
    actions: list[str],
    *,
    path_prefix: str = "",
) -> None:
    if not segments:
        return
    segment = segments[0]
    if segment.endswith("[]"):
        key = segment.removesuffix("[]")
        values = current.get(key) if isinstance(current, dict) else None
        if not isinstance(values, list):
            return
        for index, value in enumerate(values):
            next_prefix = f"{path_prefix}{key}[{index}]."
            _truncate_path(value, segments[1:], limit, actions, path_prefix=next_prefix)
        return
    if not isinstance(current, dict) or segment not in current:
        return
    if len(segments) == 1:
        value = current.get(segment)
        if not isinstance(value, str) or len(value) <= limit:
            return
        truncated = value[:limit].rstrip(TRAILING_TRUNCATION_CHARS)
        if not truncated:
            truncated = value[:limit].rstrip()
        _set(
            current,
            segment,
            truncated or value[:limit],
            actions,
            f"truncate {path_prefix}{segment} to {limit}",
        )
        return
    _truncate_path(
        current[segment],
        segments[1:],
        limit,
        actions,
        path_prefix=f"{path_prefix}{segment}.",
    )


def _trim_list(
    item: dict[str, Any],
    key: str,
    limit: int,
    actions: list[str],
    *,
    path: str = "",
) -> None:
    value = item.get(key)
    if isinstance(value, list) and len(value) > limit:
        label = f"{path}: trim {key}" if path else f"trim {key}"
        _set(item, key, value[:limit], actions, label)


def _set(
    item: dict[str, Any],
    key: str,
    value: Any,
    actions: list[str],
    action: str,
) -> None:
    if item.get(key) != value:
        item[key] = value
        actions.append(action)
