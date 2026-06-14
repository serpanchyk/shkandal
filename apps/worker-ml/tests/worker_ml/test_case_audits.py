from uuid import uuid4

import pytest
from worker_ml.case_audits import _validate_article_coverage
from worker_ml.llm.contracts import CaseCoherenceAuditOutput


def _output(article_ids: list[str]) -> CaseCoherenceAuditOutput:
    return CaseCoherenceAuditOutput.model_validate(
        {
            "outcome": "coherent",
            "reason_uk": "Одна справа.",
            "stories": [
                {
                    "story_ref": "original",
                    "title_uk": "Справа",
                    "summary_uk": "Опис.",
                    "article_ids": article_ids,
                    "reason_uk": "Одна історія.",
                }
            ],
        }
    )


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
