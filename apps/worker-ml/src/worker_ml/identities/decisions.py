"""Identity-resolution decision validation and source grounding."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from shkandal_database.models import Event

from worker_ml.llm.contracts import (
    EntityResolutionDecision,
    EntityResolutionOutput,
    EventResolutionDecision,
    EventResolutionOutput,
)


def validate_coverage(
    provisional: list[dict[str, Any]],
    decisions: Sequence[EntityResolutionDecision | EventResolutionDecision],
    case_ids: set[UUID],
) -> None:
    """Require one decision per provisional item and linked Case assignments."""

    expected = {str(item["provisional_ref"]) for item in provisional}
    actual = {decision.provisional_ref for decision in decisions}
    if actual != expected:
        raise ValueError("resolution decisions must exactly cover provisional refs")
    allowed = {str(case_id) for case_id in case_ids}
    for decision in decisions:
        if any(assignment.case_id not in allowed for assignment in decision.case_assignments):
            raise ValueError("resolution assigned an item to an unlinked Case")


def normalize_invalid_entity_links(
    provisional: list[dict[str, Any]],
    output: EntityResolutionOutput,
    candidate_ids: dict[str, set[str]],
) -> EntityResolutionOutput:
    """Create a source-grounded Entity instead of merging an invalid identity."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    decisions = []
    for decision in output.entities:
        if decision.action in {"create_new", "reject"}:
            decisions.append(decision)
            continue
        if decision.existing_entity_id in candidate_ids[decision.provisional_ref]:
            decisions.append(decision)
            continue
        item = by_ref[decision.provisional_ref]
        decisions.append(
            decision.model_copy(
                update={
                    "action": "create_new",
                    "existing_entity_id": None,
                    "new_canonical_name_uk": str(item["name_uk"]),
                    "entity_type": str(item["entity_type"]),
                    "aliases": list(item.get("aliases", [])),
                    "description_uk": str(item["description_uk"]),
                }
            )
        )
    return EntityResolutionOutput(entities=decisions)


def normalize_invalid_event_links(
    provisional: list[dict[str, Any]],
    output: EventResolutionOutput,
    candidate_ids: dict[str, set[str]],
) -> EventResolutionOutput:
    """Create a source-grounded Event instead of merging an invalid identity."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    decisions = []
    for decision in output.events:
        if decision.action in {"create_new", "reject"}:
            decisions.append(decision)
            continue
        if decision.existing_event_id in candidate_ids[decision.provisional_ref]:
            decisions.append(decision)
            continue
        decisions.append(source_grounded_event_create(decision, by_ref[decision.provisional_ref]))
    return EventResolutionOutput(events=decisions)


def normalize_event_link_anchors(
    provisional: list[dict[str, Any]],
    output: EventResolutionOutput,
    candidates: list[list[dict[str, Any]]],
) -> EventResolutionOutput:
    """Ground linked Event anchors in source evidence and reject conflicting merges."""

    by_ref = {str(item["provisional_ref"]): item for item in provisional}
    candidates_by_ref = {
        str(item["provisional_ref"]): {
            str(candidate["event_id"]): candidate for candidate in item_candidates
        }
        for item, item_candidates in zip(provisional, candidates, strict=True)
    }
    accepted_anchors: dict[str, dict[str, Any]] = {}
    decisions = []
    for decision in output.events:
        if decision.action != "link_existing":
            decisions.append(decision)
            continue
        item = by_ref[decision.provisional_ref]
        event_date = item.get("event_date")
        precision = str(item.get("event_date_precision", "unknown"))
        location = item.get("location_uk")
        year, month, day = date_parts(event_date, precision)
        candidate = candidates_by_ref[decision.provisional_ref].get(str(decision.existing_event_id))
        event_id = str(decision.existing_event_id)
        anchors = accepted_anchors.get(event_id, candidate)
        if anchors is not None and (
            _event_date_conflicts(anchors, year, month, day)
            or _event_location_conflicts(anchors, location)
        ):
            decisions.append(source_grounded_event_create(decision, item))
            continue
        accepted_anchors[event_id] = _merge_event_anchors(anchors, year, month, day, location)
        decisions.append(
            decision.model_copy(
                update={
                    "event_date": event_date,
                    "event_date_precision": precision,
                    "location_uk": location,
                }
            )
        )
    return EventResolutionOutput(events=decisions)


def source_grounded_event_create(
    decision: EventResolutionDecision,
    item: dict[str, Any],
) -> EventResolutionDecision:
    """Replace an unsafe Event merge with a source-grounded Event creation."""

    return decision.model_copy(
        update={
            "action": "create_new",
            "existing_event_id": None,
            "new_title_uk": str(item["title_uk"]),
            "description_uk": str(item["description_uk"]),
            "event_date": item.get("event_date"),
            "event_date_precision": item.get("event_date_precision", "unknown"),
            "location_uk": item.get("location_uk"),
        }
    )


def merged_assignments(
    decisions: Sequence[EntityResolutionDecision | EventResolutionDecision],
) -> dict[str, str]:
    """Merge duplicate identity decisions into one set of Case assignments."""

    merged: dict[str, str] = {}
    for decision in decisions:
        for assignment in decision.case_assignments:
            merged.setdefault(assignment.case_id, assignment.relevance_reason_uk)
    return merged


def with_provisional_refs(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Give pre-reference article cards deterministic refs during rollout."""

    return [
        {**item, "provisional_ref": item.get("provisional_ref") or f"{prefix}_{index}"}
        for index, item in enumerate(items, start=1)
    ]


def date_parts(value: str | None, precision: str) -> tuple[int | None, int | None, int | None]:
    """Convert a partial Event date into persisted date anchors."""

    if value is None or precision == "unknown":
        return None, None, None
    parts = [int(part) for part in value.split("-")]
    return parts[0], parts[1] if len(parts) > 1 else None, parts[2] if len(parts) > 2 else None


def enrich_event_date(
    event: Event,
    year: int | None,
    month: int | None,
    day: int | None,
    precision: str,
) -> None:
    """Fill compatible missing date anchors without rewriting known facts."""

    incoming = (year, month, day)
    current = (event.event_year, event.event_month, event.event_day)
    for current_part, incoming_part in zip(current, incoming, strict=True):
        if current_part is not None and incoming_part is not None and current_part != incoming_part:
            raise ValueError("event decision conflicts with existing date")
    if year is None:
        return
    event.event_year = event.event_year or year
    event.event_month = event.event_month or month
    event.event_day = event.event_day or day
    precision_rank = {"unknown": 0, "year": 1, "month": 2, "day": 3}
    if precision_rank[precision] > precision_rank[event.event_date_precision]:
        event.event_date_precision = precision


def _merge_event_anchors(
    current: dict[str, Any] | None,
    year: int | None,
    month: int | None,
    day: int | None,
    location: Any,
) -> dict[str, Any]:
    anchors = dict(current or {})
    anchors["event_year"] = anchors.get("event_year") or year
    anchors["event_month"] = anchors.get("event_month") or month
    anchors["event_day"] = anchors.get("event_day") or day
    anchors["location_uk"] = anchors.get("location_uk") or location
    return anchors


def _event_date_conflicts(
    candidate: dict[str, Any],
    year: int | None,
    month: int | None,
    day: int | None,
) -> bool:
    incoming = (year, month, day)
    current = (
        candidate.get("event_year"),
        candidate.get("event_month"),
        candidate.get("event_day"),
    )
    return any(
        current_part is not None and incoming_part is not None and current_part != incoming_part
        for current_part, incoming_part in zip(current, incoming, strict=True)
    )


def _event_location_conflicts(candidate: dict[str, Any], location: Any) -> bool:
    current = candidate.get("location_uk")
    return (
        isinstance(current, str)
        and isinstance(location, str)
        and current.casefold() != location.casefold()
    )
