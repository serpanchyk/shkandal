"""Identity retrieval queries and rebuildable vector payloads."""

from typing import Any

from shkandal_database.models import Entity, Event
from shkandal_vector_store.schemas import EntityVectorPayload, EventVectorPayload


def entity_query(item: dict[str, Any]) -> str:
    """Build a retrieval query for one provisional Entity."""

    values = [item.get("name_uk"), item.get("entity_type"), item.get("description_uk")]
    return "\n".join(str(value) for value in values if value)


def event_query(item: dict[str, Any]) -> str:
    """Build a retrieval query for one provisional Event."""

    values = [
        item.get("title_uk"),
        item.get("description_uk"),
        item.get("event_date"),
        item.get("location_uk"),
    ]
    return "\n".join(str(value) for value in values if value)


def entity_vector_payload(entity: Entity) -> EntityVectorPayload:
    """Build the rebuildable vector payload for an Entity."""

    return EntityVectorPayload(
        slug=entity.slug,
        entity_type=entity.entity_type,
        canonical_name_uk=entity.canonical_name_uk,
        aliases=entity.aliases,
        description_uk=entity.description_uk,
        metadata=entity.metadata_,
    )


def event_vector_payload(event: Event) -> EventVectorPayload:
    """Build the rebuildable vector payload for an Event."""

    return EventVectorPayload(
        slug=event.slug,
        title_uk=event.title_uk,
        description_uk=event.description_uk,
        event_year=event.event_year,
        event_month=event.event_month,
        event_day=event.event_day,
        event_date_precision=event.event_date_precision,
        location_uk=event.location_uk,
        metadata=event.metadata_,
    )
