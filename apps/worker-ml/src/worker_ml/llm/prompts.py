"""Prompt registry for plain Ukrainian prompt files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class PromptDefinition:
    """Stable prompt metadata stored with each LLM run."""

    name: str
    version: str
    filename: str
    input_variables: tuple[str, ...]


PROMPTS: dict[str, PromptDefinition] = {
    "article_card": PromptDefinition(
        name="article_card",
        version="2026-06-15",
        filename="article_card.uk.md",
        input_variables=("article_json", "schema_json"),
    ),
    "case_resolution": PromptDefinition(
        name="case_resolution",
        version="2026-06-15",
        filename="case_resolution.uk.md",
        input_variables=("resolution_json", "schema_json"),
    ),
    "entity_resolution": PromptDefinition(
        name="entity_resolution",
        version="2026-06-12-2",
        filename="entity_resolution.uk.md",
        input_variables=("resolution_json", "schema_json"),
    ),
    "event_resolution": PromptDefinition(
        name="event_resolution",
        version="2026-06-15-1",
        filename="event_resolution.uk.md",
        input_variables=("resolution_json", "schema_json"),
    ),
    "case_copy_update": PromptDefinition(
        name="case_copy_update",
        version="2026-06-12-1",
        filename="case_copy_update.uk.md",
        input_variables=("case_json", "schema_json"),
    ),
    "case_coherence_audit": PromptDefinition(
        name="case_coherence_audit",
        version="2026-06-15-2",
        filename="case_coherence_audit.uk.md",
        input_variables=("case_json", "schema_json"),
    ),
    "case_public_interest_audit": PromptDefinition(
        name="case_public_interest_audit",
        version="2026-06-15-3",
        filename="case_public_interest_audit.uk.md",
        input_variables=("case_json", "schema_json"),
    ),
    "case_duplicate_audit": PromptDefinition(
        name="case_duplicate_audit",
        version="2026-06-15-3",
        filename="case_duplicate_audit.uk.md",
        input_variables=("cases_json", "schema_json"),
    ),
    "repair": PromptDefinition(
        name="repair",
        version="2026-06-15-1",
        filename="repair.uk.md",
        input_variables=("schema_json", "validation_error", "invalid_output"),
    ),
}


class PromptRegistry:
    """Load plain prompt files and adapt them into LangChain templates."""

    def __init__(self, prompt_dir: Path = PROMPT_DIR) -> None:
        self._prompt_dir = prompt_dir

    def get(self, name: str) -> PromptDefinition:
        """Return stable prompt metadata by name."""

        try:
            return PROMPTS[name]
        except KeyError as exc:
            raise ValueError(f"unknown LLM prompt: {name}") from exc

    def load_text(self, name: str) -> str:
        """Load a prompt's source text."""

        definition = self.get(name)
        return (self._prompt_dir / definition.filename).read_text(encoding="utf-8")

    def chat_prompt(self, name: str) -> ChatPromptTemplate:
        """Build a LangChain chat prompt from the plain prompt file."""

        definition = self.get(name)
        text = self.load_text(name)
        prompt = ChatPromptTemplate.from_messages([("user", text)])
        missing_variables = set(definition.input_variables) - set(prompt.input_variables)
        if missing_variables:
            missing = ", ".join(sorted(missing_variables))
            raise ValueError(f"prompt {name} is missing variables: {missing}")
        return prompt
