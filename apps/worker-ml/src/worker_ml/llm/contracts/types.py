"""Pydantic contracts for structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

LlmRunType = Literal[
    "article_gate",
    "article_card",
    "case_resolution",
    "case_link_audit",
    "entity_resolution",
    "event_resolution",
    "refresh_case",
    "case_coherence_audit",
    "case_public_interest_audit",
    "case_duplicate_audit",
]
EntityType = Literal[
    "person",
    "organization",
    "institution",
    "company",
    "political_party",
    "informal_group",
    "unknown_actor",
    "other",
]
EventDatePrecision = Literal["day", "month", "year", "unknown"]
NoiseReason = Literal[
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
]


class StrictOutput(BaseModel):
    """Base model for rejecting undeclared LLM fields."""

    model_config = ConfigDict(extra="forbid")
