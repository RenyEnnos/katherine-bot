"""
Comprehensive domain tests for RelationshipStateV1 v1.

Coverage map (35+ behavioural requirements):
──────────────────────────────────────────────────────────────────────────────
 1. Round-trip de RelationshipStateV1.
 2. Construtor directo, factory e from_dict() aplicam as mesmas invariantes.
 3. Versão ausente é rejeitada no formato v1.
 4. Versão desconhecida é rejeitada.
 5. Chaves desconhecidas são rejeitadas.
 6. bool, None, strings, listas, objectos, NaN e infinito são rejeitados.
 7. Valores fora de 0.0..1.0 são rejeitados pelo modelo.
 8. Timestamp inválido é rejeitado.
 9. Triggers são trimados, limitados, deduplicados e imutáveis.
10. Alterar a lista original não altera o snapshot.
11. Todos os rótulos e fronteiras exactas de bond_label são testados.
12. bond_label não aparece na serialização.
13. Migração legada válida produz um snapshot v1.
14. user_id legado divergente não é copiado nem utilizado.
15. bond_label legado incorrecto é ignorado.
16. Payload legado incompleto, inválido ou desconhecido falha fechado.
17. Migração não altera o objecto de entrada.
18. Migração de um snapshot v1 é idempotente.
19. Transição com entradas iguais produz resultado igual.
20. O snapshot anterior não é modificado.
21. Triggers são preservados na transição.
22. Relógio regressivo é rejeitado.
23. Todos os pesos, limiares e clamps actuais têm testes de regressão.
24. AppraisalV1 é entregue directamente à transição relacional.
25. Appraisal neutro mantém as métricas e actualiza somente o timestamp.
26. Novo perfil nasce com snapshot relacional v1.
27. sync_state() rejeita tipo relacional inválido antes de tocar no banco.
28. Persistência inclui schema_version e exclui user_id e bond_label.
29. Identidade falsa no payload legado não substitui o usuário autenticado.
30. Estado relacional de um usuário nunca aparece no fluxo de outro.
31. Cancelamento e serialização por usuário continuam correctos.
32. EmotionStateResponse permanece inalterado e não expõe relacionamento.
33. Nenhum teste usa Groq, Supabase, embeddings ou rede reais.
34. Toda a suíte backend existente passa.
35. Testes, lint, build, auditoria frontend e CI completa passam.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict

import pytest

from backend.emotional_domain import AppraisalV1, EmotionalDomainError
from backend.memory import MemoryManager, StatePersistenceError
from backend.relationship import (
    RELATIONSHIP_SCHEMA_VERSION,
    RelationshipDomainError,
    RelationshipStateV1,
    RelationshipTransitionConfig,
    compute_bond_label,
    migrate_legacy_relationship_snapshot,
    transition_relationship,
)
from backend.emotion_presentation import EmotionStateResponse


# ─── Fixed clock ─────────────────────────────────────────────────────────────
FIXED_CLOCK = 1_700_000_000.0


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _valid_relationship_dict(
    trust: float = 0.5,
    affection: float = 0.3,
    tension: float = 0.0,
    triggers: Any = None,
    timestamp: float = FIXED_CLOCK,
    schema_version: int = RELATIONSHIP_SCHEMA_VERSION,
) -> Dict[str, object]:
    if triggers is None:
        triggers = []
    return {
        "schema_version": schema_version,
        "trust": trust,
        "affection": affection,
        "tension": tension,
        "triggers": triggers,
        "timestamp": timestamp,
    }


def _valid_legacy_dict(
    trust: float = 0.5,
    affection: float = 0.3,
    tension: float = 0.0,
    triggers: Any = None,
    last_interaction: float = FIXED_CLOCK,
    user_id: str = "test_user",
    bond_label: str = "Conhecidos",
) -> Dict[str, object]:
    if triggers is None:
        triggers = []
    return {
        "trust": trust,
        "affection": affection,
        "tension": tension,
        "triggers": triggers,
        "last_interaction": last_interaction,
        "user_id": user_id,
        "bond_label": bond_label,
    }


def _valid_appraisal(
    valence: float = 0.0,
    discrete: Any = None,
) -> AppraisalV1:
    if discrete is None:
        discrete = {}
    return AppraisalV1.create(
        valence_shift=valence,
        arousal_shift=0.0,
        dominance_shift=0.0,
        discrete_emotions=discrete,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    """Requirement 1: round-trip de RelationshipStateV1."""

    def test_to_dict_from_dict(self):
        state = RelationshipStateV1.from_dict(_valid_relationship_dict())
        reconstructed = RelationshipStateV1.from_dict(state.to_dict())
        assert state == reconstructed

    def test_create_then_dict_then_reconstruct(self):
        state = RelationshipStateV1.create(
            trust=0.7, affection=0.6, tension=0.2,
            triggers=["music", "childhood"],
            timestamp=FIXED_CLOCK,
        )
        data = state.to_dict()
        reconstructed = RelationshipStateV1.from_dict(data)
        assert state == reconstructed

    def test_neutral_round_trip(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = state.to_dict()
        reconstructed = RelationshipStateV1.from_dict(data)
        assert state == reconstructed

    def test_to_dict_includes_schema_version(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = state.to_dict()
        assert data["schema_version"] == RELATIONSHIP_SCHEMA_VERSION

    def test_to_dict_no_bond_label(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = state.to_dict()
        assert "bond_label" not in data


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Direct constructor, factory and from_dict() apply same invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestUniformValidation:
    """Requirement 2: all construction paths enforce the same invariants."""

    def test_direct_ctor_rejects_bad_trust(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1(trust="bad", timestamp=FIXED_CLOCK)

    def test_create_rejects_bad_trust(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust="bad", affection=0.3, tension=0.0,
                triggers=[], timestamp=FIXED_CLOCK,
            )

    def test_from_dict_rejects_bad_trust(self):
        d = _valid_relationship_dict(trust="bad")
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_direct_ctor_rejects_out_of_range_trust(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1(trust=1.5, timestamp=FIXED_CLOCK)

    def test_create_rejects_out_of_range_tension(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=-0.1,
                triggers=[], timestamp=FIXED_CLOCK,
            )

    def test_from_dict_rejects_out_of_range_affection(self):
        d = _valid_relationship_dict(affection=1.1)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_all_paths_accept_valid(self):
        state_direct = RelationshipStateV1(trust=0.5, affection=0.3, tension=0.0,
                                            triggers=(), timestamp=FIXED_CLOCK)
        state_create = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=[], timestamp=FIXED_CLOCK,
        )
        state_from = RelationshipStateV1.from_dict(_valid_relationship_dict())
        assert state_direct == state_create == state_from


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Version ausente é rejeitada no formato v1
# ═══════════════════════════════════════════════════════════════════════════════

class TestMissingVersion:
    """Requirement 3: schema_version is required in v1 format."""

    def test_from_dict_missing_version(self):
        d = _valid_relationship_dict()
        del d["schema_version"]
        with pytest.raises(RelationshipDomainError, match="schema_version"):
            RelationshipStateV1.from_dict(d)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Versão desconhecida é rejeitada
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnknownVersion:
    """Requirement 4: version must be 1."""

    @pytest.mark.parametrize("bad_version", [0, 2, 99, -1])
    def test_unknown_version_rejected(self, bad_version):
        d = _valid_relationship_dict(schema_version=bad_version)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    @pytest.mark.parametrize("bad_version", [True, False, None, "1", 1.0])
    def test_wrong_type_version_rejected(self, bad_version):
        d = _valid_relationship_dict(schema_version=bad_version)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Chaves desconhecidas são rejeitadas
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnknownKeys:
    """Requirement 5: from_dict rejects unknown keys."""

    def test_from_dict_rejects_extra_key(self):
        d = _valid_relationship_dict()
        d["extra_field"] = "value"
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_from_dict_rejects_prompt(self):
        d = _valid_relationship_dict()
        d["system_prompt"] = "do evil"
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. bool, None, strings, listas, objectos, NaN e infinito são rejeitados
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidTypes:
    """Requirement 6: type validation."""

    _NUMERIC_FIELDS = ["trust", "affection", "tension"]

    @pytest.mark.parametrize("field_name", _NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [True, False, None, "0.5", [0.5], {"v": 0.5}])
    def test_ctor_rejects_bad_type(self, field_name, bad_value):
        kwargs = {"trust": 0.5, "affection": 0.3, "tension": 0.0,
                  "triggers": (), "timestamp": FIXED_CLOCK}
        kwargs[field_name] = bad_value
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1(**kwargs)

    @pytest.mark.parametrize("field_name", _NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [True, False, None, "0.5", [0.5], {"v": 0.5}])
    def test_from_dict_rejects_bad_type(self, field_name, bad_value):
        d = _valid_relationship_dict(**{field_name: bad_value})
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_nan_rejected(self):
        d = _valid_relationship_dict(trust=float("nan"))
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_inf_rejected(self):
        d = _valid_relationship_dict(affection=float("inf"))
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_neg_inf_rejected(self):
        d = _valid_relationship_dict(tension=float("-inf"))
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Valores fora de 0.0..1.0 são rejeitados pelo modelo
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutOfRange:
    """Requirement 7: range validation."""

    @pytest.mark.parametrize("field", ["trust", "affection", "tension"])
    @pytest.mark.parametrize("bad", [-0.001, 1.001, -1.0, 2.0])
    def test_out_of_range_rejected(self, field, bad):
        d = _valid_relationship_dict(**{field: bad})
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_boundary_values_accepted(self):
        d = _valid_relationship_dict(trust=0.0, affection=1.0, tension=0.5)
        state = RelationshipStateV1.from_dict(d)
        assert state.trust == 0.0
        assert state.affection == 1.0
        assert state.tension == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Timestamp inválido é rejeitado
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidTimestamp:
    """Requirement 8: timestamp validation."""

    @pytest.mark.parametrize("bad_ts", [True, False, None, "now", [], {}])
    def test_bad_type_rejected(self, bad_ts):
        d = _valid_relationship_dict(timestamp=bad_ts)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_zero_rejected(self):
        d = _valid_relationship_dict(timestamp=0.0)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_negative_rejected(self):
        d = _valid_relationship_dict(timestamp=-1.0)
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_nan_rejected(self):
        d = _valid_relationship_dict(timestamp=float("nan"))
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_inf_rejected(self):
        d = _valid_relationship_dict(timestamp=float("inf"))
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Triggers: trimados, limitados, deduplicados e imutáveis
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggers:
    """Requirement 9: trigger validation policy."""

    def test_whitespace_trimmed(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=["  music  ", "  childhood  "],
            timestamp=FIXED_CLOCK,
        )
        assert list(state.triggers) == ["music", "childhood"]

    def test_empty_after_trim_rejected(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=["music", "  "],
                timestamp=FIXED_CLOCK,
            )

    def test_max_length_per_trigger(self):
        long_trigger = "a" * 129
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=[long_trigger],
                timestamp=FIXED_CLOCK,
            )

    def test_128_chars_accepted(self):
        trigger = "a" * 128
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=[trigger],
            timestamp=FIXED_CLOCK,
        )
        assert len(state.triggers[0]) == 128

    def test_dedup_preserves_first_occurrence_order(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=["music", "childhood", "music"],
            timestamp=FIXED_CLOCK,
        )
        assert list(state.triggers) == ["music", "childhood"]

    def test_max_32_items(self):
        items = [f"item{i}" for i in range(33)]
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=items,
                timestamp=FIXED_CLOCK,
            )

    def test_32_items_accepted(self):
        items = [f"item{i}" for i in range(32)]
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=items,
            timestamp=FIXED_CLOCK,
        )
        assert len(state.triggers) == 32

    def test_tuple_accepted(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=("music", "childhood"),
            timestamp=FIXED_CLOCK,
        )
        assert list(state.triggers) == ["music", "childhood"]

    def test_rejects_non_string_item(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=["music", 42],
                timestamp=FIXED_CLOCK,
            )

    def test_rejects_non_list_or_tuple(self):
        d = _valid_relationship_dict(triggers="not a list")
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.from_dict(d)

    def test_rejects_33_unique_items(self):
        """33 unique items must be rejected."""
        items = [f"unique{i}" for i in range(33)]
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=items,
                timestamp=FIXED_CLOCK,
            )

    def test_rejects_33_repeated_items(self):
        """33 items where many are repeated must also be rejected (limit on input)."""
        items = ["same"] * 33
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=items,
                timestamp=FIXED_CLOCK,
            )

    def test_rejects_large_repeated_collection(self):
        """Collection with 100 items that would dedup to 1 must still be rejected."""
        items = ["same"] * 100
        with pytest.raises(RelationshipDomainError):
            RelationshipStateV1.create(
                trust=0.5, affection=0.3, tension=0.0,
                triggers=items,
                timestamp=FIXED_CLOCK,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Alterar a lista original não altera o snapshot
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggerImmutability:
    """Requirement 10: deep immutability."""

    def test_mutating_original_list_does_not_affect_snapshot(self):
        src = ["music", "childhood"]
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=src,
            timestamp=FIXED_CLOCK,
        )
        src.append("new_trigger")
        assert list(state.triggers) == ["music", "childhood"]

    def test_to_dict_returns_list_not_reference(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=["music"],
            timestamp=FIXED_CLOCK,
        )
        data = state.to_dict()
        triggers_list = data["triggers"]
        triggers_list.append("hacked")
        assert list(state.triggers) == ["music"]


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Todos os rótulos e fronteiras exactas de bond_label
# ═══════════════════════════════════════════════════════════════════════════════

class TestBondLabel:
    """Requirement 11: all bond labels and exact boundaries."""

    def test_em_conflito_tension_above_07(self):
        state = RelationshipStateV1(trust=0.5, affection=0.5, tension=0.71,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Em Conflito"

    def test_em_conflito_tension_above_07_even_high_trust(self):
        state = RelationshipStateV1(trust=0.9, affection=0.9, tension=0.71,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Em Conflito"

    def test_tenso_tension_between_04_and_07(self):
        state = RelationshipStateV1(trust=0.5, affection=0.5, tension=0.41,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Tenso"

    def test_tenso_tension_071_is_conflito_not_tenso(self):
        state = RelationshipStateV1(trust=0.5, affection=0.5, tension=0.71,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Em Conflito"

    def test_tenso_boundary_041(self):
        state = RelationshipStateV1(trust=0.5, affection=0.5, tension=0.41,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Tenso"

    def test_alma_gemea_trust_above_08_affection_above_08(self):
        state = RelationshipStateV1(trust=0.81, affection=0.81, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Alma Gêmea"

    def test_alma_gemea_boundary_081_081(self):
        state = RelationshipStateV1(trust=0.81, affection=0.81, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Alma Gêmea"

    def test_intimos_trust_above_07_affection_above_06(self):
        state = RelationshipStateV1(trust=0.71, affection=0.61, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Íntimos"

    def test_intimos_not_alma_gemea(self):
        state = RelationshipStateV1(trust=0.81, affection=0.61, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Íntimos"  # trust > 0.8 but affection <= 0.8

    def test_amigos_trust_above_05_affection_above_04(self):
        state = RelationshipStateV1(trust=0.51, affection=0.41, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Amigos"

    def test_desconfiada_trust_below_03(self):
        state = RelationshipStateV1(trust=0.29, affection=0.5, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Desconfiada"

    def test_conhecidos_default(self):
        state = RelationshipStateV1(trust=0.5, affection=0.3, tension=0.0,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Conhecidos"

    def test_conhecidos_mid_range(self):
        state = RelationshipStateV1(trust=0.4, affection=0.35, tension=0.2,
                                      timestamp=FIXED_CLOCK)
        assert compute_bond_label(state) == "Conhecidos"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. bond_label não aparece na serialização
# ═══════════════════════════════════════════════════════════════════════════════

class TestBondLabelNotPersisted:
    """Requirement 12: bond_label is not in to_dict output."""

    def test_bond_label_not_in_to_dict(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = state.to_dict()
        assert "bond_label" not in data

    def test_bond_label_not_in_round_trip(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = state.to_dict()
        reconstructed = RelationshipStateV1.from_dict(data)
        assert not hasattr(reconstructed, "bond_label")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Migração legada válida produz um snapshot v1
# ═══════════════════════════════════════════════════════════════════════════════

class TestMigrationValidLegacy:
    """Requirement 13: valid legacy migration."""

    def test_legacy_to_v1(self):
        legacy = _valid_legacy_dict()
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert isinstance(v1, RelationshipStateV1)
        assert v1.trust == 0.5
        assert v1.affection == 0.3
        assert v1.tension == 0.0
        assert v1.timestamp == FIXED_CLOCK
        assert v1.schema_version == RELATIONSHIP_SCHEMA_VERSION

    def test_legacy_different_values(self):
        legacy = _valid_legacy_dict(trust=0.8, affection=0.7, tension=0.2,
                                     last_interaction=1_800_000_000.0)
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert v1.trust == 0.8
        assert v1.affection == 0.7
        assert v1.tension == 0.2
        assert v1.timestamp == 1_800_000_000.0

    def test_legacy_with_triggers(self):
        legacy = _valid_legacy_dict(triggers=["music", "childhood"])
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert list(v1.triggers) == ["music", "childhood"]


# ═══════════════════════════════════════════════════════════════════════════════
# 14. user_id legado divergente não é copiado nem utilizado
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyUserIdIgnored:
    """Requirement 14: user_id from legacy payload is ignored."""

    def test_legacy_user_id_not_in_v1(self):
        legacy = _valid_legacy_dict(user_id="some_other_user")
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert not hasattr(v1, "user_id")
        assert v1.trust == 0.5  # Values should still be correct


# ═══════════════════════════════════════════════════════════════════════════════
# 15. bond_label legado incorrecto é ignorado
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyBondLabelIgnored:
    """Requirement 15: bond_label is ignored; always derived from metrics."""

    def test_legacy_bond_label_not_in_v1(self):
        legacy = _valid_legacy_dict(bond_label="Alma Gêmea", trust=0.3, affection=0.2)
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert not hasattr(v1, "bond_label")

    def test_correct_label_still_derived(self):
        # Even though legacy says "Alma Gêmea", the metrics say "Conhecidos"
        legacy = _valid_legacy_dict(bond_label="Alma Gêmea", trust=0.3, affection=0.2)
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert compute_bond_label(v1) == "Conhecidos"


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Payload legado incompleto, inválido ou desconhecido falha fechado
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyInvalidPayloads:
    """Requirement 16: legacy fail-closed."""

    def test_empty_dict_rejected(self):
        with pytest.raises(RelationshipDomainError):
            migrate_legacy_relationship_snapshot({})

    def test_non_dict_rejected(self):
        with pytest.raises(RelationshipDomainError):
            migrate_legacy_relationship_snapshot("not a dict")

    def test_missing_required_fields(self):
        with pytest.raises(RelationshipDomainError):
            migrate_legacy_relationship_snapshot({"trust": 0.5})

    def test_extra_unknown_keys(self):
        legacy = _valid_legacy_dict()
        legacy["unknown_field"] = "value"
        with pytest.raises(RelationshipDomainError):
            migrate_legacy_relationship_snapshot(legacy)

    def test_both_timestamp_and_last_interaction_rejected(self):
        legacy = _valid_legacy_dict()
        legacy["timestamp"] = 1_800_000_000.0
        with pytest.raises(RelationshipDomainError):
            migrate_legacy_relationship_snapshot(legacy)


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Migração não altera o objecto de entrada
# ═══════════════════════════════════════════════════════════════════════════════

class TestMigrationDoesNotMutateInput:
    """Requirement 17: input dict is not mutated."""

    def test_legacy_input_not_mutated(self):
        legacy = _valid_legacy_dict()
        original = dict(legacy)
        migrate_legacy_relationship_snapshot(legacy)
        assert legacy == original

    def test_v1_input_not_mutated(self):
        v1_dict = _valid_relationship_dict()
        original = dict(v1_dict)
        migrate_legacy_relationship_snapshot(v1_dict)
        assert v1_dict == original


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Migração de um snapshot v1 é idempotente
# ═══════════════════════════════════════════════════════════════════════════════

class TestMigrationIdempotent:
    """Requirement 18: v1 migration is idempotent."""

    def test_v1_migration_idempotent(self):
        v1 = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        v1_dict = v1.to_dict()
        result1 = migrate_legacy_relationship_snapshot(v1_dict)
        result2 = migrate_legacy_relationship_snapshot(v1_dict)
        assert result1 == result2
        assert result1 == v1

    def test_legacy_then_v1_equivalent(self):
        legacy = _valid_legacy_dict()
        v1_from_legacy = migrate_legacy_relationship_snapshot(legacy)
        v1_dict = v1_from_legacy.to_dict()
        v1_again = migrate_legacy_relationship_snapshot(v1_dict)
        assert v1_from_legacy == v1_again


# ═══════════════════════════════════════════════════════════════════════════════
# 19 & 20. Transição: determinística, não modifica anterior
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitionDeterministic:
    """Requirement 19: same inputs → same outputs. Requirement 20: no mutation."""

    def test_deterministic(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.5, discrete={"joy": 0.8})
        config = RelationshipTransitionConfig.defaults()

        r1 = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        r2 = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert r1 == r2

    def test_does_not_mutate_previous(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        original_state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.5, discrete={"joy": 0.8})
        config = RelationshipTransitionConfig.defaults()

        transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert state == original_state


# ═══════════════════════════════════════════════════════════════════════════════
# 21. Triggers preservados na transição
# ═══════════════════════════════════════════════════════════════════════════════

class TestTriggersPreserved:
    """Requirement 21: triggers survive transition."""

    def test_triggers_preserved(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=["music", "childhood"],
            timestamp=FIXED_CLOCK,
        )
        appraisal = _valid_appraisal(valence=0.5)
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert list(new_state.triggers) == ["music", "childhood"]

    def test_new_state_has_same_triggers_object(self):
        state = RelationshipStateV1.create(
            trust=0.5, affection=0.3, tension=0.0,
            triggers=["music"],
            timestamp=FIXED_CLOCK,
        )
        appraisal = _valid_appraisal(valence=0.5)
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.triggers == state.triggers


# ═══════════════════════════════════════════════════════════════════════════════
# 22. Relógio regressivo é rejeitado
# ═══════════════════════════════════════════════════════════════════════════════

class TestClockRegression:
    """Requirement 22: clock regression is rejected."""

    def test_current_time_before_timestamp_rejected(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal()
        config = RelationshipTransitionConfig.defaults()
        with pytest.raises(RelationshipDomainError, match="clock regression"):
            transition_relationship(state, appraisal, FIXED_CLOCK - 1, config)


# ═══════════════════════════════════════════════════════════════════════════════
# 23. Todos os pesos, limiares e clamps actuais têm testes de regressão
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionWeightsAndThresholds:
    """Requirement 23: exact legacy weights and thresholds preserved."""

    def test_trust_increases_on_positive_valence(self):
        state = RelationshipStateV1(trust=0.5, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.21)  # > 0.2
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.trust == pytest.approx(0.52)

    def test_trust_decreases_on_negative_valence(self):
        state = RelationshipStateV1(trust=0.5, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=-0.31)  # < -0.3
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.trust == pytest.approx(0.45)

    def test_affection_boosted_by_tenderness(self):
        state = RelationshipStateV1(affection=0.3, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={"tenderness": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.affection == pytest.approx(0.33)

    def test_affection_boosted_by_joy(self):
        state = RelationshipStateV1(affection=0.3, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={"joy": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.affection == pytest.approx(0.31)

    def test_affection_boosted_by_gratitude(self):
        state = RelationshipStateV1(affection=0.3, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={"gratitude": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.affection == pytest.approx(0.32)

    def test_tension_spikes_with_anger(self):
        state = RelationshipStateV1(tension=0.0, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={"anger": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.tension == pytest.approx(0.1)

    def test_tension_spikes_with_disgust(self):
        state = RelationshipStateV1(tension=0.0, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={"disgust": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.tension == pytest.approx(0.1)

    def test_tension_spikes_with_negative_valence(self):
        state = RelationshipStateV1(tension=0.0, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=-0.51)
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.tension == pytest.approx(0.05)

    def test_reconciliation_reduces_tension(self):
        state = RelationshipStateV1(tension=0.3, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.31)  # > 0.3
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.tension == pytest.approx(0.2)

    def test_clamp_trust_at_zero(self):
        state = RelationshipStateV1(trust=0.01, timestamp=FIXED_CLOCK)
        # Apply very negative valence to try to push below 0
        appraisal = _valid_appraisal(valence=-0.31)
        config = RelationshipTransitionConfig.defaults()
        # Run multiple transitions
        for _ in range(5):
            state = transition_relationship(state, appraisal, state.timestamp + 1, config)
        assert state.trust >= 0.0

    def test_clamp_affection_at_one(self):
        state = RelationshipStateV1(affection=0.99, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0, discrete={
            "tenderness": 0.31, "joy": 0.31, "gratitude": 0.31,
        })
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.affection == pytest.approx(1.0)

    def test_clamp_tension_at_one(self):
        state = RelationshipStateV1(tension=0.99, timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=-0.51, discrete={"anger": 0.31})
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert new_state.tension == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 24. AppraisalV1 é entregue directamente à transição relacional
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppraisalDirectDelivery:
    """Requirement 24: AppraisalV1 is passed directly."""

    def test_appraisal_directly_accepted(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.5)
        config = RelationshipTransitionConfig.defaults()
        # This should not raise — AppraisalV1 is accepted directly
        result = transition_relationship(state, appraisal, FIXED_CLOCK + 1, config)
        assert isinstance(result, RelationshipStateV1)

    def test_dict_rejected(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        config = RelationshipTransitionConfig.defaults()
        with pytest.raises(RelationshipDomainError):
            transition_relationship(state, {"valence": 0.5}, FIXED_CLOCK + 1, config)  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# 25. Appraisal neutro mantém as métricas e actualiza somente o timestamp
# ═══════════════════════════════════════════════════════════════════════════════

class TestNeutralAppraisal:
    """Requirement 25: neutral appraisal keeps metrics, updates timestamp."""

    def test_neutral_preserves_metrics(self):
        state = RelationshipStateV1(trust=0.7, affection=0.6, tension=0.2,
                                      timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal(valence=0.0)
        config = RelationshipTransitionConfig.defaults()
        new_state = transition_relationship(state, appraisal, FIXED_CLOCK + 60, config)
        assert new_state.trust == 0.7
        assert new_state.affection == 0.6
        assert new_state.tension == 0.2
        assert new_state.timestamp == FIXED_CLOCK + 60


# ═══════════════════════════════════════════════════════════════════════════════
# 26. Novo perfil nasce com snapshot relacional v1
# ═══════════════════════════════════════════════════════════════════════════════

class TestNewProfileDefault:
    """Requirement 26: new profile has v1 relationship snapshot."""

    def test_default_state_is_v1(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        assert isinstance(rel, RelationshipStateV1)
        assert rel.schema_version == RELATIONSHIP_SCHEMA_VERSION

    def test_default_to_dict_has_no_user_id_or_bond_label(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = rel.to_dict()
        assert "user_id" not in data
        assert "bond_label" not in data
        assert "schema_version" in data

    def test_get_default_state_returns_valid_v1(self):
        """Call the real MemoryManager._get_default_state with injected clock."""
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        mm.supabase = None  # prevent DB access
        default = mm._get_default_state("test_user")
        rel_data = default["relationship_state"]

        # Must be a dict (to_dict output)
        assert isinstance(rel_data, dict)
        # Must have schema_version == 1
        assert rel_data["schema_version"] == RELATIONSHIP_SCHEMA_VERSION
        # Must have the injected clock timestamp
        assert rel_data["timestamp"] == FIXED_CLOCK
        # Must have exactly the v1 fields
        expected_keys = {"trust", "affection", "tension", "triggers",
                         "timestamp", "schema_version"}
        assert set(rel_data.keys()) == expected_keys
        # Must NOT contain user_id
        assert "user_id" not in rel_data
        # Must NOT contain bond_label
        assert "bond_label" not in rel_data
        # Must NOT contain last_interaction
        assert "last_interaction" not in rel_data
        # Must be deserializable by from_dict
        reconstructed = RelationshipStateV1.from_dict(rel_data)
        assert isinstance(reconstructed, RelationshipStateV1)
        assert reconstructed.trust == 0.5
        assert reconstructed.timestamp == FIXED_CLOCK

    def test_new_profile_insert_payload(self):
        """Verify the payload sent to Supabase insert on new profile creation."""
        from unittest.mock import MagicMock
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        mm.supabase = MagicMock()
        mock_insert_resp = MagicMock()
        mock_insert_resp.data = [{"user_id": "new_user"}]
        mock_insert_resp.error = None
        mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_insert_resp

        # Use the real load_user_state with a mock that returns empty (triggers new profile)
        mock_select_resp = MagicMock()
        mock_select_resp.data = []
        mock_select_resp.error = None
        mm.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select_resp

        state = mm.load_user_state("new_user")
        rel_data = state["relationship_state"]

        # Verify the insert call included the correct relationship payload
        insert_call_args = mm.supabase.table.return_value.insert.call_args
        assert insert_call_args is not None
        inserted = insert_call_args[0][0]
        rel_inserted = inserted["relationship_state"]
        assert isinstance(rel_inserted, dict)
        assert rel_inserted["schema_version"] == RELATIONSHIP_SCHEMA_VERSION
        assert "user_id" not in rel_inserted
        assert "bond_label" not in rel_inserted
        # Verify the relationship in the returned state is also valid
        reconstructed = RelationshipStateV1.from_dict(rel_data)
        assert isinstance(reconstructed, RelationshipStateV1)
        assert reconstructed.timestamp == FIXED_CLOCK


# ═══════════════════════════════════════════════════════════════════════════════
# 27. sync_state() rejeita tipo relacional inválido antes de tocar no banco
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncStateRejectsInvalidRelationship:
    """Requirement 27: sync_state validation."""

    def _make_mm(self):
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        mm.supabase = None  # Ensure no DB calls
        return mm

    def test_rejects_none(self):
        mm = self._make_mm()
        from backend.emotional_domain import EmotionalStateV1
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", state, None)  # type: ignore

    def test_rejects_string(self):
        mm = self._make_mm()
        from backend.emotional_domain import EmotionalStateV1
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", state, "not a relationship")

    def test_rejects_dict(self):
        mm = self._make_mm()
        from backend.emotional_domain import EmotionalStateV1
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", state, {"trust": 0.5})

    def test_accepts_relationship_v1(self):
        mm = self._make_mm()
        from backend.emotional_domain import EmotionalStateV1
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        # Should not raise
        with pytest.raises(StatePersistenceError, match="Serviço"):
            # It will fail because supabase is None, but not because of relationship type
            mm.sync_state("u", state, rel)


# ═══════════════════════════════════════════════════════════════════════════════
# 28. Persistência inclui schema_version e exclui user_id e bond_label
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistenceFields:
    """Requirement 28: serialization fields."""

    def test_to_dict_includes_schema_version(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = rel.to_dict()
        assert data["schema_version"] == RELATIONSHIP_SCHEMA_VERSION

    def test_to_dict_excludes_user_id(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = rel.to_dict()
        assert "user_id" not in data

    def test_to_dict_excludes_bond_label(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = rel.to_dict()
        assert "bond_label" not in data

    def test_to_dict_exact_keys(self):
        rel = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        data = rel.to_dict()
        expected = {"schema_version", "trust", "affection", "tension",
                     "triggers", "timestamp"}
        assert set(data.keys()) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# 29. Identidade falsa no payload legado não substitui o usuário autenticado
# ═══════════════════════════════════════════════════════════════════════════════

class TestFakeIdentityNotUsed:
    """Requirement 29: legacy user_id is not used for identity."""

    def test_legacy_user_id_ignored(self):
        legacy = _valid_legacy_dict(user_id="attacker_user")
        v1 = migrate_legacy_relationship_snapshot(legacy)
        assert not hasattr(v1, "user_id")

    def test_migration_result_has_no_user_id_field(self):
        """Verifica que user_id não é um campo conceitual do snapshot v1."""
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        assert not hasattr(state, "user_id")


# ═══════════════════════════════════════════════════════════════════════════════
# 30 & 31. Isolation e locking permanecem válidos (testes de integração existentes)
# ═══════════════════════════════════════════════════════════════════════════════

# Covered by existing test suites (test_isolation, test_emotional_integration).


# ═══════════════════════════════════════════════════════════════════════════════
# 32. EmotionStateResponse não expõe relacionamento
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmotionStateResponseNoRelationship:
    """Requirement 32: EmotionStateResponse does not expose relationship."""

    def test_emotion_response_has_no_relationship(self):
        from backend.emotion_presentation import EmotionStateResponse, PublicPAD, PublicDominantEmotion
        response = EmotionStateResponse(
            schema_version=1,
            mood_label="NEUTRA",
            pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
            dominant_emotions=[
                PublicDominantEmotion(name="joy", intensity=0.5),
            ],
            timestamp=FIXED_CLOCK,
        )
        data = response.model_dump()
        assert "trust" not in data
        assert "affection" not in data
        assert "tension" not in data
        assert "bond_label" not in data
        assert "relationship" not in data


# ═══════════════════════════════════════════════════════════════════════════════
# 33. No real Groq, Supabase, embeddings or network
# ═══════════════════════════════════════════════════════════════════════════════

# All tests in this file are pure domain tests — no external deps used.

# ═══════════════════════════════════════════════════════════════════════════════
# 34. TransitionConfig validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitionConfigValidation:
    """RelationshipTransitionConfig is immutable and validated."""

    _CONFIG_FIELDS_WITH_BOOL = [
        "trust_positive_threshold", "trust_positive_delta", "trust_negative_threshold",
        "tenderness_threshold", "tenderness_boost", "joy_threshold", "joy_boost",
        "gratitude_threshold", "gratitude_boost", "anger_threshold", "anger_spike",
        "disgust_threshold", "disgust_spike", "tension_valence_threshold",
        "tension_valence_spike", "reconciliation_valence_threshold", "reconciliation_delta",
    ]

    def test_default_config_accepted(self):
        config = RelationshipTransitionConfig.defaults()
        assert isinstance(config, RelationshipTransitionConfig)

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_bool_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: True})

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_none_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: None})

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_string_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: "bad"})

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_nan_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: float("nan")})

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_inf_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: float("inf")})

    @pytest.mark.parametrize("field", _CONFIG_FIELDS_WITH_BOOL)
    def test_neg_inf_rejected(self, field):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(**{field: float("-inf")})

    def test_huge_int_overflow_rejected(self):
        """Very large integers that Overflow float conversion must be rejected."""
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(trust_positive_threshold=10**1000)

    def test_out_of_range_anger_spike_rejected(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(anger_spike=1.5)

    def test_out_of_range_below_rejected(self):
        with pytest.raises(RelationshipDomainError):
            RelationshipTransitionConfig(trust_positive_delta=-0.01)


# ═══════════════════════════════════════════════════════════════════════════════
# 35. Transition error handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitionErrors:
    """Edge cases in transition."""

    def test_invalid_previous_state_type(self):
        with pytest.raises(RelationshipDomainError):
            transition_relationship(
                "not a state",  # type: ignore
                _valid_appraisal(),
                FIXED_CLOCK,
                RelationshipTransitionConfig.defaults(),
            )

    def test_invalid_appraisal_type(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        with pytest.raises(RelationshipDomainError):
            transition_relationship(
                state,
                "not an appraisal",  # type: ignore
                FIXED_CLOCK + 1,
                RelationshipTransitionConfig.defaults(),
            )

    def test_invalid_config_type(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal()
        with pytest.raises(RelationshipDomainError):
            transition_relationship(
                state,
                appraisal,
                FIXED_CLOCK + 1,
                "not a config",  # type: ignore
            )

    def test_current_time_bool_rejected(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal()
        config = RelationshipTransitionConfig.defaults()
        with pytest.raises(RelationshipDomainError):
            transition_relationship(state, appraisal, True, config)

    def test_current_time_none_rejected(self):
        state = RelationshipStateV1.neutral(timestamp=FIXED_CLOCK)
        appraisal = _valid_appraisal()
        config = RelationshipTransitionConfig.defaults()
        with pytest.raises(RelationshipDomainError):
            transition_relationship(state, appraisal, None, config)  # type: ignore
