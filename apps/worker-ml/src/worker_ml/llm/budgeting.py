"""Deterministic prompt-budget helpers for LLM evidence payloads."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetedText:
    """Text trimmed to a configured character budget."""

    text: str
    original_chars: int
    included_chars: int

    @property
    def truncated(self) -> bool:
        return self.included_chars < self.original_chars


def budget_text(value: str | None, *, limit: int) -> BudgetedText:
    """Return text trimmed to a positive character limit."""

    if limit <= 0:
        raise ValueError("text budget limit must be positive")
    text = value or ""
    trimmed = text[:limit]
    return BudgetedText(text=trimmed, original_chars=len(text), included_chars=len(trimmed))


def prompt_size_chars(*parts: str) -> int:
    """Return the combined prompt payload size in characters."""

    return sum(len(part) for part in parts)


def json_dumps_compact(payload: Any) -> str:
    """Serialize prompt JSON in the compact format used by worker-ml prompts."""

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def compact_article_card(card: dict[str, Any]) -> dict[str, Any]:
    """Keep only compact factual article-card context for case-level audits."""

    return {
        "article_id": card.get("article_id"),
        "published_at": card.get("published_at"),
        "title_uk": card.get("title_uk"),
        "summary_uk": card.get("summary_uk"),
    }


def compact_article_cards(cards: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact a sequence of article cards for prompt evidence."""

    return [compact_article_card(card) for card in cards]


def first_latest_sample(cards: Sequence[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Keep the earliest and latest evidence when a chronological list is too large."""

    if limit <= 0:
        raise ValueError("card limit must be positive")
    if len(cards) <= limit:
        return list(cards)
    first_count = limit // 2
    latest_count = limit - first_count
    return [*cards[:first_count], *cards[-latest_count:]]


def lifecycle_sample(cards: Sequence[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Sample a Case lifecycle while preserving first and latest evidence."""

    if limit <= 0:
        raise ValueError("card limit must be positive")
    if len(cards) <= limit:
        return list(cards)
    selected = {0, len(cards) - 1}
    for index in range(1, limit - 1):
        selected.add(round(index * (len(cards) - 1) / (limit - 1)))
    return [cards[index] for index in sorted(selected)]


def count_metadata(
    *,
    prefix: str,
    original_count: int,
    included_count: int,
) -> dict[str, Any]:
    """Return standard prompt input-count metadata."""

    return {
        f"{prefix}_count": original_count,
        f"included_{prefix}_count": included_count,
        "input_truncated": included_count < original_count,
    }
