"""Tests for LLM output contracts."""

import pytest
from pydantic import ValidationError
from worker_ml.llm.contracts import (
    ArticleCardOutput,
    ArticleGateOutput,
    CaseCoherenceAuditOutput,
    CaseDuplicateAuditOutput,
    CaseLinkAuditOutput,
    CaseResolutionOutput,
    EntityResolutionOutput,
    EventResolutionOutput,
)


def article_case_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "ukraine_nexus_uk": "Подія стосується українського органу місцевого самоврядування.",
        "concrete_story_core_uk": "Розслідування щодо закупівель міської ради.",
        "public_accountability_anchor_uk": "Йдеться про публічні закупівлі та підозру посадовцям.",
        "continuation_potential_uk": "Можливі подальші процесуальні дії.",
        "noise_signals_uk": [],
    }
    diagnosis.update(changes)
    return diagnosis


def case_coherence_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "shared_specific_core_uk": "Усі статті описують одну закупівельну справу.",
        "shared_only_broad_theme_uk": None,
        "merge_blockers_uk": [],
        "split_story_cores_uk": [],
        "detached_article_signals_uk": [],
        "coherence_test_uk": "Так, усі статті описуються одним конкретним реченням.",
    }
    diagnosis.update(changes)
    return diagnosis


def case_resolution_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "article_story_core_uk": "Стаття описує окрему відстежувану закупівельну історію.",
        "specific_case_core_uk": "Закупівля міськрадою послуг за завищеною ціною.",
        "only_broad_overlap_uk": None,
        "merge_blockers_uk": [],
        "separate_story_cores_uk": [],
        "case_coherence_test_uk": "Так, справу можна описати одним конкретним реченням.",
        "matching_existing_case_ids": [],
        "new_case_core_uk": "Закупівля міськрадою послуг за завищеною ціною.",
        "rejection_signals_uk": [],
        "broad_theme_warning_uk": None,
    }
    diagnosis.update(changes)
    return diagnosis


def case_link_audit_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "article_story_core_uk": "Стаття описує той самий тендер міськради.",
        "case_story_core_uk": "Справу утворюють статті про той самий тендер міськради.",
        "shared_specific_core_uk": "Той самий тендер міськради з підозрою в завищенні ціни.",
        "only_broad_overlap_uk": None,
        "disconnect_signals_uk": [],
        "coherence_test_uk": "Так, це одне конкретне речення про той самий тендер.",
    }
    diagnosis.update(changes)
    return diagnosis


def entity_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "is_named_stable_actor": True,
        "material_case_ids": ["case-a"],
        "identity_match_evidence_uk": "Назва і роль точно збігаються з candidate.",
        "identity_conflict_uk": None,
        "rejection_signal_uk": None,
    }
    diagnosis.update(changes)
    return diagnosis


def event_diagnosis(**changes: object) -> dict[str, object]:
    diagnosis: dict[str, object] = {
        "is_concrete_occurrence": True,
        "occurrence_core_uk": "НАБУ повідомило посадовцю про підозру.",
        "anchor_summary_uk": "Дія, учасник і процесуальний етап збігаються.",
        "candidate_match_evidence_uk": "Candidate описує ту саму підозру тому самому посадовцю.",
        "anchor_conflict_uk": None,
        "temporal_scope_check_uk": "Подія вже відбулася і не виходить за поточну дату.",
        "future_date_warning_uk": None,
        "material_case_ids": ["case-a"],
        "rejection_signal_uk": None,
    }
    diagnosis.update(changes)
    return diagnosis


def test_case_coherence_audit_accepts_overlapping_article_assignments() -> None:
    output = CaseCoherenceAuditOutput.model_validate(
        {
            "diagnosis": case_coherence_diagnosis(
                shared_specific_core_uk=None,
                split_story_cores_uk=["Перша закупівельна справа.", "Друга закупівельна справа."],
                coherence_test_uk="Ні, це дві різні історії.",
            ),
            "outcome": "split",
            "reason_uk": "Змішані дві справи.",
            "stories": [
                {
                    "story_ref": "original",
                    "title_uk": "Перша справа",
                    "summary_uk": "Опис першої справи.",
                    "article_ids": ["article-a", "article-bridge"],
                    "reason_uk": "Домінантна історія.",
                },
                {
                    "story_ref": "story_second",
                    "title_uk": "Друга справа",
                    "summary_uk": "Опис другої справи.",
                    "article_ids": ["article-b", "article-bridge"],
                    "reason_uk": "Окрема історія.",
                },
            ],
        }
    )

    assert output.outcome == "split"


def test_case_coherence_audit_rejects_split_without_original_story() -> None:
    with pytest.raises(ValueError, match="exactly one original"):
        CaseCoherenceAuditOutput.model_validate(
            {
                "diagnosis": case_coherence_diagnosis(
                    shared_specific_core_uk=None,
                    split_story_cores_uk=["Перша історія.", "Друга історія."],
                    coherence_test_uk="Ні, це дві різні історії.",
                ),
                "outcome": "split",
                "reason_uk": "Змішані справи.",
                "stories": [
                    {
                        "story_ref": "story_a",
                        "title_uk": "Перша",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-a"],
                        "reason_uk": "Причина.",
                    },
                    {
                        "story_ref": "story_b",
                        "title_uk": "Друга",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-b"],
                        "reason_uk": "Причина.",
                    },
                ],
            }
        )


def test_case_coherence_audit_rejects_assigned_detached_article() -> None:
    with pytest.raises(ValueError, match="cannot both assign and detach"):
        CaseCoherenceAuditOutput.model_validate(
            {
                "diagnosis": case_coherence_diagnosis(),
                "outcome": "coherent",
                "reason_uk": "Одна справа.",
                "stories": [
                    {
                        "story_ref": "original",
                        "title_uk": "Справа",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-a"],
                        "reason_uk": "Стаття належить до історії.",
                    }
                ],
                "detached_articles": [
                    {
                        "article_id": "article-a",
                        "reason_uk": "Стаття не належить до жодної історії.",
                    }
                ],
            }
        )


def test_case_coherence_audit_rejects_duplicate_detached_article() -> None:
    with pytest.raises(ValueError, match="detached article ids must be unique"):
        CaseCoherenceAuditOutput.model_validate(
            {
                "diagnosis": case_coherence_diagnosis(),
                "outcome": "coherent",
                "reason_uk": "Одна справа.",
                "stories": [
                    {
                        "story_ref": "original",
                        "title_uk": "Справа",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-a"],
                        "reason_uk": "Стаття належить до історії.",
                    }
                ],
                "detached_articles": [
                    {
                        "article_id": "article-b",
                        "reason_uk": "Стаття описує іншу історію.",
                    },
                    {
                        "article_id": "article-b",
                        "reason_uk": "Стаття описує іншу історію.",
                    },
                ],
            }
        )


def test_case_coherence_audit_rejects_coherent_without_shared_specific_core() -> None:
    with pytest.raises(ValueError, match="shared specific core"):
        CaseCoherenceAuditOutput.model_validate(
            {
                "diagnosis": case_coherence_diagnosis(
                    shared_specific_core_uk=None,
                    coherence_test_uk="Ні, це не одна конкретна історія.",
                ),
                "outcome": "coherent",
                "reason_uk": "Надто широке об'єднання.",
                "stories": [
                    {
                        "story_ref": "original",
                        "title_uk": "Справа",
                        "summary_uk": "Опис.",
                        "article_ids": ["article-a"],
                        "reason_uk": "Стаття належить до історії.",
                    }
                ],
            }
        )


def test_case_link_audit_accepts_connect_with_specific_shared_core() -> None:
    output = CaseLinkAuditOutput.model_validate(
        {
            "diagnosis": case_link_audit_diagnosis(),
            "reason_uk": "Стаття описує той самий тендер і той самий процес підзвітності.",
            "outcome": "connect",
        }
    )

    assert output.outcome == "connect"


def test_case_link_audit_rejects_connect_on_broad_overlap() -> None:
    with pytest.raises(ValueError, match="shared specific core"):
        CaseLinkAuditOutput.model_validate(
            {
                "diagnosis": case_link_audit_diagnosis(
                    shared_specific_core_uk=None,
                    only_broad_overlap_uk="Збігається лише орган місцевого самоврядування.",
                ),
                "reason_uk": "Збіг лише інституційний.",
                "outcome": "connect",
            }
        )


def test_case_link_audit_rejects_drop_without_disconnect_basis() -> None:
    with pytest.raises(ValueError, match="factual reason to disconnect"):
        CaseLinkAuditOutput.model_validate(
            {
                "diagnosis": case_link_audit_diagnosis(),
                "reason_uk": "Підстав від'єднання немає.",
                "outcome": "drop",
            }
        )


def test_article_gate_contract_accepts_candidate_decision() -> None:
    output = ArticleGateOutput.model_validate(
        {
            "case_diagnosis": article_case_diagnosis(),
            "noise_reason": None,
            "case_decision_reason_uk": "Матеріал описує конкретну закупівельну справу.",
            "is_case_candidate": True,
        }
    )

    assert output.is_case_candidate is True


@pytest.mark.parametrize(
    "noise_reason",
    [
        "culture",
        "diplomacy",
        "policy_law",
        "routine_regulatory",
        "routine_crime",
        "foreign_no_ukraine_nexus",
    ],
)
def test_article_gate_contract_accepts_rejected_decision(noise_reason: str) -> None:
    output = ArticleGateOutput.model_validate(
        {
            "case_diagnosis": article_case_diagnosis(
                ukraine_nexus_uk=None,
                concrete_story_core_uk=None,
                public_accountability_anchor_uk=None,
                continuation_potential_uk=None,
                noise_signals_uk=["Культурний матеріал без справи."],
            ),
            "noise_reason": noise_reason,
            "case_decision_reason_uk": "Матеріал не описує окрему справу.",
            "is_case_candidate": False,
        }
    )

    assert output.noise_reason == noise_reason


def test_article_gate_contract_rejects_candidate_without_ukraine_nexus() -> None:
    with pytest.raises(ValidationError, match="Ukraine nexus"):
        ArticleGateOutput.model_validate(
            {
                "case_diagnosis": article_case_diagnosis(ukraine_nexus_uk=None),
                "noise_reason": None,
                "case_decision_reason_uk": "Матеріал описує справу.",
                "is_case_candidate": True,
            }
        )


def test_article_gate_contract_rejects_rejection_without_noise_reason() -> None:
    with pytest.raises(ValidationError, match="noise reason"):
        ArticleGateOutput.model_validate(
            {
                "case_diagnosis": article_case_diagnosis(
                    ukraine_nexus_uk=None,
                    concrete_story_core_uk=None,
                    public_accountability_anchor_uk=None,
                    continuation_potential_uk=None,
                ),
                "noise_reason": None,
                "case_decision_reason_uk": "Матеріал не описує справу.",
                "is_case_candidate": False,
            }
        )


def test_article_card_contract_accepts_representative_json() -> None:
    output = ArticleCardOutput.model_validate(
        {
            "title_uk": "Справа про закупівлі у міській раді",
            "summary_uk": "Стаття описує підозру щодо закупівель.",
            "main_event_title_uk": "НАБУ повідомило про підозру",
            "entities": [
                {
                    "provisional_ref": "entity_city_council",
                    "name_uk": "Міська рада",
                    "entity_type": "institution",
                    "aliases": ["рада"],
                    "description_uk": "Орган місцевого самоврядування.",
                }
            ],
            "events": [
                {
                    "provisional_ref": "event_suspicion",
                    "title_uk": "НАБУ повідомило про підозру",
                    "description_uk": "Детективи повідомили посадовцю про підозру.",
                    "event_date": "2026-06-05",
                    "event_date_precision": "day",
                    "location_uk": "Київ",
                }
            ],
            "case_signature_terms": ["міська рада", "закупівлі", "підозра"],
        }
    )

    assert output.entities[0].entity_type == "institution"
    assert output.events[0].event_date_precision == "day"


@pytest.mark.parametrize(
    "changes",
    [
        {"main_event_title_uk": ""},
        {"events": []},
        {"case_signature_terms": []},
        {"events": [{"title_uk": "Подія", "description_uk": "Опис"}] * 4},
        {
            "entities": [
                {
                    "name_uk": f"Сутність {index}",
                    "entity_type": "organization",
                    "description_uk": "Роль у статті.",
                }
                for index in range(9)
            ]
        },
    ],
)
def test_article_card_contract_rejects_invalid_shape(changes: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "title_uk": "Справа",
        "summary_uk": "Опис справи.",
        "main_event_title_uk": "НБУ оштрафував банк",
        "entities": [],
        "events": [
            {
                "title_uk": "НБУ оштрафував банк",
                "description_uk": "Регулятор наклав штраф.",
            }
        ],
        "case_signature_terms": ["НБУ", "штраф"],
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        ArticleCardOutput.model_validate(payload)


@pytest.mark.parametrize(
    "rejection_reason",
    [
        "not_an_entity",
        "insufficient_identity",
        "not_stable_actor",
        "not_material_to_case",
        "background_or_related_material",
        "location_only",
        "role_without_name",
        "unsupported_by_context",
    ],
)
def test_entity_resolution_contract_accepts_strict_rejection_reasons(
    rejection_reason: str,
) -> None:
    output = EntityResolutionOutput.model_validate(
        {
            "entities": [
                {
                    "provisional_ref": "entity_rejected",
                    "diagnosis": entity_diagnosis(
                        is_named_stable_actor=False,
                        material_case_ids=[],
                        identity_match_evidence_uk=None,
                        rejection_signal_uk="Це не придатна глобальна сутність.",
                    ),
                    "reason_uk": "Сутність не можна додати до глобального графа.",
                    "action": "reject",
                    "confidence": 0.9,
                    "rejection_reason": rejection_reason,
                }
            ]
        }
    )

    assert output.entities[0].rejection_reason == rejection_reason


def event_resolution_decision(**changes: object) -> dict[str, object]:
    """Build one valid accepted Event decision for contract tests."""

    decision: dict[str, object] = {
        "provisional_ref": "event_decision",
        "diagnosis": event_diagnosis(
            candidate_match_evidence_uk=None,
        ),
        "reason_uk": "Описано конкретну подію.",
        "action": "create_new",
        "existing_event_id": None,
        "new_title_uk": "НАБУ повідомило посадовцю про підозру",
        "description_uk": "НАБУ повідомило посадовцю про підозру.",
        "event_date": None,
        "event_date_precision": "unknown",
        "date_evidence_text": None,
        "confidence": 0.9,
        "case_assignments": [{"case_id": "case-a", "relevance_reason_uk": "Етап справи."}],
        "rejection_reason": None,
    }
    decision.update(changes)
    return decision


@pytest.mark.parametrize(
    "rejection_reason",
    [
        "not_an_event",
        "insufficient_identity",
        "too_broad",
        "multi_event_summary",
        "background_fact",
        "planned_future_event",
        "opinion_or_prediction",
        "date_conflict_with_candidate",
        "unsupported_by_context",
    ],
)
def test_event_resolution_contract_accepts_strict_rejection_reasons(
    rejection_reason: str,
) -> None:
    output = EventResolutionOutput.model_validate(
        {
            "events": [
                {
                    "provisional_ref": "event_rejected",
                    "diagnosis": event_diagnosis(
                        is_concrete_occurrence=False,
                        occurrence_core_uk=None,
                        anchor_summary_uk=None,
                        candidate_match_evidence_uk=None,
                        material_case_ids=[],
                        rejection_signal_uk="Це не конкретна глобальна подія.",
                    ),
                    "reason_uk": "Це не придатна глобальна подія.",
                    "action": "reject",
                    "confidence": 0.9,
                    "rejection_reason": rejection_reason,
                }
            ]
        }
    )

    assert output.events[0].rejection_reason == rejection_reason


def test_entity_resolution_contract_rejects_accepted_entity_without_stable_actor() -> None:
    with pytest.raises(ValidationError, match="named stable actor"):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_actor",
                        "diagnosis": entity_diagnosis(
                            is_named_stable_actor=False,
                            identity_match_evidence_uk=None,
                        ),
                        "reason_uk": "Хибно прийнята сутність.",
                        "action": "link_existing",
                        "existing_entity_id": "00000000-0000-0000-0000-000000000001",
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Причина"}
                        ],
                    }
                ]
            }
        )


def test_entity_resolution_contract_rejects_accepted_entity_without_material_cases() -> None:
    with pytest.raises(ValidationError, match="material case ids"):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_actor",
                        "diagnosis": entity_diagnosis(material_case_ids=[]),
                        "reason_uk": "Хибно прийнята сутність.",
                        "action": "create_new",
                        "new_canonical_name_uk": "ТОВ «Приклад»",
                        "entity_type": "company",
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Причина"}
                        ],
                    }
                ]
            }
        )


def test_entity_resolution_contract_rejects_link_without_identity_evidence() -> None:
    with pytest.raises(ValidationError, match="identity match evidence"):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_actor",
                        "diagnosis": entity_diagnosis(identity_match_evidence_uk=None),
                        "reason_uk": "Хибне link-рішення.",
                        "action": "link_existing",
                        "existing_entity_id": "00000000-0000-0000-0000-000000000001",
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Причина"}
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    ("event_date", "precision"),
    [
        (None, "day"),
        ("2026-06", "day"),
        ("2026-06-10", "month"),
        ("2026-06", "year"),
        ("2026", "unknown"),
    ],
)
def test_event_resolution_contract_rejects_inconsistent_event_dates(
    event_date: str | None,
    precision: str,
) -> None:
    with pytest.raises(ValidationError):
        EventResolutionOutput.model_validate(
            {
                "events": [
                    event_resolution_decision(
                        event_date=event_date,
                        event_date_precision=precision,
                        date_evidence_text="Дата вказана у статті.",
                    )
                ]
            }
        )


def test_event_resolution_contract_requires_date_evidence() -> None:
    with pytest.raises(ValidationError, match="date_evidence_text"):
        EventResolutionOutput.model_validate(
            {
                "events": [
                    event_resolution_decision(
                        event_date="2026-06-10",
                        event_date_precision="day",
                    )
                ]
            }
        )


def test_event_resolution_contract_allows_future_date_warning() -> None:
    output = EventResolutionOutput.model_validate(
        {
            "events": [
                event_resolution_decision(
                    event_date="2026-06-17",
                    event_date_precision="day",
                    date_evidence_text="Суд призначив розгляд на 17 червня.",
                    diagnosis=event_diagnosis(
                        temporal_scope_check_uk=(
                            "Дата пізніше поточної, але це попередження для рішення."
                        ),
                        future_date_warning_uk="event_date пізніше поточної дати.",
                    ),
                )
            ]
        }
    )

    assert output.events[0].diagnosis.future_date_warning_uk is not None


def test_event_resolution_contract_rejects_evidence_without_date() -> None:
    with pytest.raises(ValidationError, match="null date evidence"):
        EventResolutionOutput.model_validate(
            {"events": [event_resolution_decision(date_evidence_text="10 червня")]}
        )


@pytest.mark.parametrize("title", ["Подія 1", "опис події 12", " Подія 2. "])
def test_event_resolution_contract_rejects_placeholder_titles(title: str) -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        EventResolutionOutput.model_validate(
            {"events": [event_resolution_decision(new_title_uk=title)]}
        )


def test_event_resolution_contract_rejects_reject_with_case_assignments() -> None:
    with pytest.raises(ValidationError, match="reject cannot have Case assignments"):
        EventResolutionOutput.model_validate(
            {
                "events": [
                    event_resolution_decision(
                        action="reject",
                        new_title_uk=None,
                        rejection_reason="not_an_event",
                    )
                ]
            }
        )


def test_event_resolution_contract_rejects_accepted_event_without_case_assignment() -> None:
    with pytest.raises(ValidationError, match="at least one Case assignment"):
        EventResolutionOutput.model_validate(
            {"events": [event_resolution_decision(case_assignments=[])]}
        )


def test_event_resolution_contract_rejects_accepted_event_without_concrete_occurrence() -> None:
    with pytest.raises(ValidationError, match="concrete occurrence"):
        EventResolutionOutput.model_validate(
            {
                "events": [
                    event_resolution_decision(
                        diagnosis=event_diagnosis(
                            is_concrete_occurrence=False,
                            occurrence_core_uk=None,
                        )
                    )
                ]
            }
        )


def test_event_resolution_contract_rejects_link_with_anchor_conflict() -> None:
    with pytest.raises(ValidationError, match="anchor conflict"):
        EventResolutionOutput.model_validate(
            {
                "events": [
                    event_resolution_decision(
                        action="link_existing",
                        existing_event_id="00000000-0000-0000-0000-000000000001",
                        new_title_uk=None,
                        diagnosis=event_diagnosis(anchor_conflict_uk="Дата суперечить candidate."),
                    )
                ]
            }
        )


@pytest.mark.parametrize(
    "alias",
    [
        "орган, який викрив схему",
        "колишній посадовець",
        "підозрюваний у справі",
        "переможець тендеру",
    ],
)
def test_entity_resolution_contract_rejects_role_aliases(alias: str) -> None:
    with pytest.raises(ValidationError, match="aliases cannot be role descriptions"):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_company",
                        "diagnosis": entity_diagnosis(identity_match_evidence_uk=None),
                        "reason_uk": "Компанія матеріально важлива для справи.",
                        "action": "create_new",
                        "new_canonical_name_uk": "ТОВ «Приклад»",
                        "entity_type": "company",
                        "aliases": [alias],
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Предмет справи."}
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "description_uk",
    [
        "Орган, який викрив схему.",
        "Суд, який продовжив обов'язки.",
        "Компанія, яка фігурує у справі.",
        "Країна, де затримали особу.",
    ],
)
def test_entity_resolution_contract_rejects_case_role_descriptions(
    description_uk: str,
) -> None:
    with pytest.raises(
        ValidationError, match="description_uk cannot describe a case-specific role"
    ):
        EntityResolutionOutput.model_validate(
            {
                "entities": [
                    {
                        "provisional_ref": "entity_company",
                        "diagnosis": entity_diagnosis(identity_match_evidence_uk=None),
                        "reason_uk": "Компанія матеріально важлива для справи.",
                        "action": "create_new",
                        "new_canonical_name_uk": "ТОВ «Приклад»",
                        "entity_type": "company",
                        "description_uk": description_uk,
                        "confidence": 0.9,
                        "case_assignments": [
                            {"case_id": "case-a", "relevance_reason_uk": "Предмет справи."}
                        ],
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    ("event_date", "precision"),
    [
        ("2026-06", "day"),
        ("2026-06-05", "month"),
        ("2026", "unknown"),
        (None, "year"),
    ],
)
def test_article_card_contract_rejects_inconsistent_event_dates(
    event_date: str | None,
    precision: str,
) -> None:
    with pytest.raises(ValidationError):
        ArticleCardOutput.model_validate(
            {
                "title_uk": "Справа",
                "summary_uk": "Опис справи.",
                "main_event_title_uk": "Суд ухвалив рішення",
                "entities": [],
                "events": [
                    {
                        "title_uk": "Суд ухвалив рішення",
                        "description_uk": "Суд розглянув справу.",
                        "event_date": event_date,
                        "event_date_precision": precision,
                    }
                ],
                "case_signature_terms": ["суд", "рішення"],
            }
        )


def test_case_resolution_contract_accepts_explicit_rejection() -> None:
    output = CaseResolutionOutput.model_validate(
        {
            "diagnosis": case_resolution_diagnosis(
                article_story_core_uk=None,
                new_case_core_uk=None,
                rejection_signals_uk=["Немає конкретної відстежуваної історії."],
            ),
            "decision_reason_uk": "Немає конкретної відстежуваної справи.",
            "outcome": "rejected",
            "existing_case_links": [],
            "new_cases": [],
        }
    )

    assert output.outcome == "rejected"


def test_case_resolution_contract_rejects_resolved_without_story_core() -> None:
    with pytest.raises(ValidationError, match="story core"):
        CaseResolutionOutput.model_validate(
            {
                "diagnosis": case_resolution_diagnosis(
                    article_story_core_uk=None,
                    new_case_core_uk="Нова справа.",
                ),
                "decision_reason_uk": "Немає конкретного ядра статті.",
                "outcome": "resolved",
                "existing_case_links": [],
                "new_cases": [
                    {
                        "new_case_ref": "new_case",
                        "link_reason_uk": "Причина.",
                        "confidence": 0.8,
                    }
                ],
            }
        )


def test_case_resolution_contract_rejects_resolved_without_specific_case_core() -> None:
    with pytest.raises(ValidationError, match="specific case core"):
        CaseResolutionOutput.model_validate(
            {
                "diagnosis": case_resolution_diagnosis(specific_case_core_uk=None),
                "decision_reason_uk": "Немає конкретного ядра справи.",
                "outcome": "resolved",
                "existing_case_links": [],
                "new_cases": [
                    {
                        "new_case_ref": "new_case",
                        "link_reason_uk": "Причина.",
                        "confidence": 0.8,
                    }
                ],
            }
        )


def test_case_duplicate_audit_rejects_merge_without_shared_specific_core() -> None:
    with pytest.raises(ValidationError, match="shared specific core"):
        CaseDuplicateAuditOutput.model_validate(
            {
                "diagnosis": {
                    "case_a_core_uk": "Перша справа.",
                    "case_b_core_uk": "Друга справа.",
                    "shared_specific_core_uk": None,
                    "only_broad_overlap_uk": "Спільний лише орган.",
                    "merge_blockers_uk": [],
                },
                "reason_uk": "Недостатньо підстав для merge.",
                "outcome": "merge",
            }
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "diagnosis": case_resolution_diagnosis(
                new_case_core_uk=None,
                matching_existing_case_ids=[],
            ),
            "decision_reason_uk": "Немає дії.",
            "outcome": "resolved",
            "existing_case_links": [],
            "new_cases": [],
        },
        {
            "diagnosis": case_resolution_diagnosis(
                article_story_core_uk=None,
                new_case_core_uk=None,
                rejection_signals_uk=["Статтю треба було відхилити."],
            ),
            "decision_reason_uk": "Помилкова дія.",
            "outcome": "rejected",
            "existing_case_links": [],
            "new_cases": [
                {
                    "new_case_ref": "new_case",
                    "link_reason_uk": "Причина.",
                    "confidence": 0.8,
                }
            ],
        },
    ],
)
def test_case_resolution_contract_rejects_inconsistent_outcome(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CaseResolutionOutput.model_validate(payload)


def test_other_resolution_contracts_accept_empty_decisions() -> None:
    assert EntityResolutionOutput.model_validate({"entities": []})
    assert EventResolutionOutput.model_validate({"events": []})
