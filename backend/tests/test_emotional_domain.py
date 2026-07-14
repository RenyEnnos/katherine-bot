"""
Tests for backend/emotional_domain — issue #232 (updated for v1.1 hardening).

Coverage map (original requirements from #232 + new hardening requirements):
─────────────────────────────────────────────────────────────────────────────
Original:
 1. Round-trip EmotionalStateV1
 2. Round-trip AppraisalV1
 3. Version absent is rejected
 4. Unknown version is rejected
 5. bool/None/str/list/dict rejected
 6. NaN/Inf rejected
 7. Out-of-range values follow policy (reject)
 8. Unknown keys not silently accepted
 9. Discrete emotion allowlist is exact
10. Unknown emotion rejected
11. Coping mode unknown rejected
12. Timestamp invalid rejected
13. Legacy migration valid → v1 correct
14. Legacy invalid fails closed
15. Migration does not mutate input
16. Invalid appraisal → neutral fallback
17. Domain importable without infra
18. No network use
19. Existing backend suite passes
20. CI remains green

Hardening (v1.1):
H1.  Direct constructor of EmotionalStateV1 validates invariants
H2.  Direct constructor rejects timestamp=0, invalid schema_version, bool, NaN, ranges
H3.  Direct constructor of AppraisalV1 validates invariants
H4.  Caller's mapping does not affect AppraisalV1 after construction
H5.  discrete_emotions cannot be mutated on the object
H6.  Serialization is valid after attempted mutation
H7.  Empty dict produces observable fallback (missing_required_field)
H8.  Absent shift fields produce fallback
H9.  discrete_emotions=None/str/list/bool/number produces fallback
H10. Unknown top-level key produces fallback (unknown_top_level_key)
H11. triggered_emotions legacy alias converted correctly
H12. valence legacy alias converted correctly
H13. Conflicting aliases rejected (conflicting_aliases)
H14. Unknown emotions filtered (not rejected) from LLM output
H15. Sensitive marker not in error_code or observable result
H16. Migration rejects extra fields
H17. Migration rejects schema_version=None
H18. Migration rejects both last_update and timestamp simultaneously
H19. Migration v1 idempotent
H20. Isolated subprocess import of package — no infra modules loaded

Hardening (v1.2 — second audit):
N1.  Direct constructor normalizes int→float (EmotionalStateV1)
N2.  Direct constructor normalizes int→float (AppraisalV1 shifts)
N3.  create() and direct ctor produce identical types and JSON
N4.  Explicit None discrete_emotions rejected by create()
N5.  Explicit None discrete_emotions rejected by from_dict()
N6.  Omitted discrete_emotions defaults to empty mapping
N7.  Production _perceive() payload passes through parser without loss
N8.  DISCRETE_EMOTIONS includes all production emotions used by RelationshipManager

Hardening (v1.3 — third audit / PR #246 corrections):
O1.  Huge int (10**10000) in PAD field → EmotionalDomainError
O2.  Huge int in drive field → EmotionalDomainError
O3.  Huge int in timestamp → EmotionalDomainError
O4.  Huge int in appraisal shift → EmotionalDomainError
O5.  Huge int in emotion intensity → EmotionalDomainError
O6.  Legacy migration with huge int → EmotionalDomainError
O7.  Parser maps huge int to invalid_numeric_value (not unexpected_parser_failure)
B1.  valence=True vs valence_shift=1 → conflicting_aliases
B2.  valence=False vs valence_shift=0 → conflicting_aliases
B3.  triggered_emotions with bool joy vs discrete_emotions with int joy → conflicting_aliases
B4.  triggered_emotions with bool False vs discrete_emotions with int 0 → conflicting_aliases
B5.  Both aliases equally invalid → predictable fallback (invalid_numeric_value)
B6.  1 vs 1.0 policy: int/float equivalence accepted (not rejected)
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from types import MappingProxyType
from typing import Any

import pytest

from backend.emotional_domain.models import (
    DISCRETE_EMOTIONS,
    EMOTIONAL_SCHEMA_VERSION,
    VALID_COPING_MODES,
    AppraisalV1,
    EmotionalDomainError,
    EmotionalStateV1,
)
from backend.emotional_domain.migration import migrate_legacy_snapshot
from backend.emotional_domain.serialization import (
    deserialize_appraisal,
    deserialize_state,
    serialize_appraisal,
    serialize_state,
)
from backend.emotional_domain.appraisal_parser import (
    parse_llm_appraisal,
    ParseResult,
    ParseErrorCode,
)
# Also test the public package API.
from backend.emotional_domain import (
    ParseResult as PackageParseResult,
    ParseErrorCode as PackageParseErrorCode,
    parse_llm_appraisal as package_parse,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _valid_state_kwargs(**overrides: Any) -> dict:
    base = dict(
        pleasure=0.1,
        arousal=-0.2,
        dominance=0.3,
        libido=0.0,
        aggression=0.1,
        connection=0.5,
        energy=0.8,
        tension=0.2,
        coping_mode="HEALTHY",
        timestamp=1_700_000_000.0,
        schema_version=EMOTIONAL_SCHEMA_VERSION,
    )
    base.update(overrides)
    return base


def _valid_state_dict(**overrides: Any) -> dict:
    return _valid_state_kwargs(**overrides)


def _valid_appraisal_dict(**overrides: Any) -> dict:
    base = {
        "schema_version": EMOTIONAL_SCHEMA_VERSION,
        "valence_shift": 0.2,
        "arousal_shift": -0.1,
        "dominance_shift": 0.0,
        "discrete_emotions": {"joy": 0.5, "trust": 0.3},
    }
    base.update(overrides)
    return base


def _legacy_dict(**overrides: Any) -> dict:
    base = {
        "pleasure": 0.1,
        "arousal": -0.2,
        "dominance": 0.3,
        "libido": 0.0,
        "aggression": 0.1,
        "connection": 0.5,
        "energy": 0.8,
        "tension": 0.2,
        "coping_mode": "HEALTHY",
        "last_update": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


# ─── H1: Direct constructor validates (EmotionalStateV1) ─────────────────────

class TestStateDirectConstructorValidates:
    """H1 — Direct EmotionalStateV1(...) calls __post_init__ which validates."""

    def test_direct_ctor_valid_passes(self):
        s = EmotionalStateV1(**_valid_state_kwargs())
        assert s.pleasure == 0.1

    def test_direct_ctor_rejects_invalid_pleasure(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(pleasure=99.0))

    def test_direct_ctor_rejects_bool_field(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(arousal=True))

    def test_direct_ctor_rejects_none_field(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(dominance=None))

    def test_direct_ctor_rejects_nan(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(pleasure=float("nan")))

    def test_direct_ctor_rejects_inf(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(energy=float("inf")))


# ─── H2: Direct constructor specific cases ───────────────────────────────────

class TestStateDirectConstructorSpecificCases:
    """H2 — Direct ctor rejects timestamp=0, invalid schema_version, etc."""

    def test_direct_ctor_rejects_zero_timestamp(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(timestamp=0.0))

    def test_direct_ctor_rejects_negative_timestamp(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(timestamp=-1.0))

    def test_direct_ctor_rejects_bool_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(schema_version=True))

    def test_direct_ctor_rejects_wrong_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(schema_version=2))

    def test_direct_ctor_rejects_none_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(schema_version=None))

    def test_direct_ctor_rejects_float_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(schema_version=1.0))

    def test_direct_ctor_rejects_string_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(schema_version="1"))

    def test_direct_ctor_rejects_bool_timestamp(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(timestamp=True))

    def test_direct_ctor_rejects_unknown_coping_mode(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(coping_mode="PANIC"))


# ─── H3: Direct constructor validates AppraisalV1 ────────────────────────────

class TestAppraisalDirectConstructorValidates:
    """H3 — Direct AppraisalV1(...) calls __post_init__ which validates."""

    def test_direct_ctor_valid_passes(self):
        a = AppraisalV1(
            valence_shift=0.2, arousal_shift=-0.1, dominance_shift=0.0,
            discrete_emotions={"joy": 0.5}, schema_version=EMOTIONAL_SCHEMA_VERSION,
        )
        assert a.valence_shift == 0.2

    def test_direct_ctor_rejects_invalid_shift(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=99.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={}, schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_direct_ctor_rejects_unknown_emotion(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={"invented": 0.5},
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_direct_ctor_rejects_invalid_intensity(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={"joy": 99.0},
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_direct_ctor_rejects_bool_intensity(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={"joy": True},
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_direct_ctor_rejects_none_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={}, schema_version=None,
            )

    def test_direct_ctor_rejects_bool_schema_version(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={}, schema_version=True,
            )


# ─── H4: Caller mapping does not affect AppraisalV1 after construction ────────

class TestAppraisalCallerMappingIsolation:
    """H4 — Mutations to the caller's dict do not affect the constructed model."""

    def test_create_isolates_from_caller_dict(self):
        src = {"joy": 0.5}
        ap = AppraisalV1.create(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions=src,
        )
        src["joy"] = 99.0
        src["anger"] = 0.8
        assert ap.discrete_emotions["joy"] == 0.5
        assert "anger" not in ap.discrete_emotions

    def test_from_dict_isolates_from_caller_dict(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": 0.5})
        ap = AppraisalV1.from_dict(d)
        d["discrete_emotions"]["joy"] = 99.0
        assert ap.discrete_emotions["joy"] == 0.5

    def test_direct_ctor_isolates_from_caller_dict(self):
        src = {"joy": 0.3}
        ap = AppraisalV1(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions=src, schema_version=EMOTIONAL_SCHEMA_VERSION,
        )
        src["joy"] = 99.0
        assert ap.discrete_emotions["joy"] == 0.3


# ─── H5: discrete_emotions cannot be mutated on the object ───────────────────

class TestAppraisalDeepImmutability:
    """H5 — The stored discrete_emotions is immutable."""

    def test_discrete_emotions_is_mappingproxy(self):
        ap = AppraisalV1.neutral()
        assert isinstance(ap.discrete_emotions, MappingProxyType)

    def test_cannot_set_item_on_neutral(self):
        ap = AppraisalV1.neutral()
        with pytest.raises(TypeError):
            ap.discrete_emotions["joy"] = 0.5

    def test_cannot_set_item_on_created(self):
        ap = AppraisalV1.create(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions={"joy": 0.5},
        )
        with pytest.raises(TypeError):
            ap.discrete_emotions["joy"] = 99.0

    def test_cannot_delete_item(self):
        ap = AppraisalV1.create(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions={"joy": 0.5},
        )
        with pytest.raises(TypeError):
            del ap.discrete_emotions["joy"]

    def test_to_dict_returns_fresh_copy(self):
        ap = AppraisalV1.create(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions={"joy": 0.5},
        )
        d = ap.to_dict()
        d["discrete_emotions"]["joy"] = 99.0
        # Object is unchanged
        assert ap.discrete_emotions["joy"] == 0.5


# ─── N1 & N2: Normalization in direct constructors ──────────────────────────

class TestStateNormalization:
    """N1 — Direct EmotionalStateV1(...) normalizes int → float."""

    def test_direct_ctor_normalizes_int_to_float(self):
        state = EmotionalStateV1(**_valid_state_kwargs(pleasure=1, libido=0))
        assert state.pleasure == 1.0
        assert isinstance(state.pleasure, float)
        assert isinstance(state.libido, float)

    def test_factory_and_direct_ctor_equal(self):
        direct = EmotionalStateV1(**_valid_state_kwargs(pleasure=1, arousal=0, tension=0))
        factory = EmotionalStateV1.create(
            pleasure=1, arousal=0, dominance=0.3,
            libido=0.0, aggression=0.1, connection=0.5,
            energy=0.8, tension=0, coping_mode="HEALTHY",
            timestamp=1_700_000_000.0,
        )
        assert direct == factory
        assert direct.to_dict() == factory.to_dict()

    def test_direct_and_factory_json_identical(self):
        direct = EmotionalStateV1(**_valid_state_kwargs(pleasure=1, arousal=0, tension=0))
        factory = EmotionalStateV1.create(
            pleasure=1, arousal=0, dominance=0.3,
            libido=0.0, aggression=0.1, connection=0.5,
            energy=0.8, tension=0, coping_mode="HEALTHY",
            timestamp=1_700_000_000.0,
        )
        assert serialize_state(direct) == serialize_state(factory)

    def test_normalization_uses_float_in_to_dict(self):
        state = EmotionalStateV1(**_valid_state_kwargs(pleasure=1))
        d = state.to_dict()
        assert d["pleasure"] == 1.0
        assert isinstance(d["pleasure"], float)


class TestAppraisalNormalization:
    """N2 — Direct AppraisalV1(...) normalizes int → float for shifts."""

    def test_direct_ctor_normalizes_int_shifts(self):
        a = AppraisalV1(
            valence_shift=1, arousal_shift=0, dominance_shift=-1,
            discrete_emotions={}, schema_version=EMOTIONAL_SCHEMA_VERSION,
        )
        assert a.valence_shift == 1.0
        assert isinstance(a.valence_shift, float)
        assert isinstance(a.arousal_shift, float)
        assert isinstance(a.dominance_shift, float)

    def test_factory_and_direct_ctor_equal(self):
        direct = AppraisalV1(
            valence_shift=1, arousal_shift=0, dominance_shift=-1,
            discrete_emotions={"joy": 0.5}, schema_version=EMOTIONAL_SCHEMA_VERSION,
        )
        factory = AppraisalV1.create(
            valence_shift=1, arousal_shift=0, dominance_shift=-1,
            discrete_emotions={"joy": 0.5},
        )
        assert direct == factory
        assert direct.to_dict() == factory.to_dict()

    def test_direct_and_factory_json_identical(self):
        direct = AppraisalV1(
            valence_shift=1, arousal_shift=0, dominance_shift=0,
            discrete_emotions={"joy": 0.5}, schema_version=EMOTIONAL_SCHEMA_VERSION,
        )
        factory = AppraisalV1.create(
            valence_shift=1, arousal_shift=0, dominance_shift=0,
            discrete_emotions={"joy": 0.5},
        )
        assert serialize_appraisal(direct) == serialize_appraisal(factory)


# ─── N4 & N5: None rejection in Appraisal API ────────────────────────────────

class TestAppraisalNoneRejection:
    """N4 — Explicit None in discrete_emotions raises EmotionalDomainError."""

    _BASE = dict(valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0)

    def test_create_explicit_none_rejected(self):
        with pytest.raises(EmotionalDomainError, match="discrete_emotions"):
            AppraisalV1.create(**self._BASE, discrete_emotions=None)

    def test_create_omitted_defaults_to_empty(self):
        """Omitting discrete_emotions entirely should produce empty mapping."""
        a = AppraisalV1.create(**self._BASE)
        assert dict(a.discrete_emotions) == {}

    def test_create_explicit_empty_accepted(self):
        a = AppraisalV1.create(**self._BASE, discrete_emotions={})
        assert dict(a.discrete_emotions) == {}

    def test_from_dict_explicit_none_rejected(self):
        d = _valid_appraisal_dict(discrete_emotions=None)
        with pytest.raises(EmotionalDomainError, match="discrete_emotions"):
            AppraisalV1.from_dict(d)

    def test_from_dict_absent_key_defaults_to_empty(self):
        d = {k: v for k, v in _valid_appraisal_dict().items() if k != "discrete_emotions"}
        a = AppraisalV1.from_dict(d)
        assert dict(a.discrete_emotions) == {}

    def test_from_dict_unknown_keys_still_rejected(self):
        d = _valid_appraisal_dict()
        d["extra"] = "value"
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)


# ─── N7: Production _perceive() payload regression test ──────────────────────

class TestParserProductionPayload:
    """N7 — The actual _perceive() payload from engine.py must pass through
    the parser without loss of emotions consumed by RelationshipManager."""

    _PRODUCTION_EMOTIONS = [
        "joy", "sadness", "anger", "fear", "disgust", "surprise",
        "tenderness", "guilt", "pride", "jealousy", "gratitude",
    ]

    def test_parser_preserves_all_production_emotions(self):
        """The full payload from engine.py _perceive() must preserve all 11
        emotions used by RelationshipManager."""
        triggered = {emo: 0.5 for emo in self._PRODUCTION_EMOTIONS}
        raw = {
            "valence": 0.3,
            "arousal_shift": -0.1,
            "dominance_shift": 0.0,
            "triggered_emotions": triggered,
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback, f"Fallback: {result.error_code}"
        parsed_emotions = dict(result.appraisal.discrete_emotions)
        for emo in self._PRODUCTION_EMOTIONS:
            assert emo in parsed_emotions, f"Missing emotion: {emo}"
            assert parsed_emotions[emo] == 0.5

    def test_tenderness_and_gratitude_preserved_for_relationship(self):
        """Specifically test the emotions consumed by RelationshipManager:
        tenderness (affection), joy (affection), gratitude (affection),
        anger (tension), disgust (tension)."""
        triggered = {
            "tenderness": 0.8, "joy": 0.3, "gratitude": 0.6,
            "anger": 0.4, "disgust": 0.0,
        }
        raw = {
            "valence": 0.5,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "triggered_emotions": triggered,
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        de = dict(result.appraisal.discrete_emotions)
        assert de["tenderness"] == 0.8
        assert de["gratitude"] == 0.6
        assert de["anger"] == 0.4

    def test_parser_preserves_all_emotions_from_legacy_triggered(self):
        """Using triggered_emotions alias (as in _perceive output)."""
        triggered = {emo: 0.3 for emo in self._PRODUCTION_EMOTIONS}
        raw = {
            "valence": -0.2,
            "arousal_shift": 0.1,
            "dominance_shift": -0.1,
            "triggered_emotions": triggered,
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        de = dict(result.appraisal.discrete_emotions)
        assert len(de) == len(self._PRODUCTION_EMOTIONS)
        for emo in self._PRODUCTION_EMOTIONS:
            assert de[emo] == 0.3


# ─── H6: Serialization valid after mutation attempt ──────────────────────────

class TestSerializationAfterMutationAttempt:
    """H6 — Serialization output is valid even after to_dict() copy is mutated."""

    def test_serialize_appraisal_valid_after_to_dict_mutation(self):
        ap = AppraisalV1.create(
            valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
            discrete_emotions={"joy": 0.5},
        )
        copy1 = ap.to_dict()
        copy1["discrete_emotions"]["joy"] = 99.0  # mutate the copy

        # Original still produces valid JSON
        json_str = serialize_appraisal(ap)
        restored = deserialize_appraisal(json_str)
        assert restored.discrete_emotions["joy"] == 0.5

    def test_state_to_dict_is_independent(self):
        state = EmotionalStateV1.create(**{k: v for k, v in _valid_state_kwargs().items()
                                           if k != "schema_version"},
                                        schema_version=EMOTIONAL_SCHEMA_VERSION)
        d = state.to_dict()
        d["pleasure"] = 99.0
        assert state.pleasure == 0.1  # frozen, unchanged


# ─── H7 & H8: Parser fallback for empty/incomplete dict ──────────────────────

class TestParserEmptyAndMissingShifts:
    """H7 — empty dict; H8 — missing shifts; both produce fallback."""

    def test_empty_dict_produces_fallback(self):
        result = parse_llm_appraisal({})
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.missing_required_field

    def test_empty_dict_fallback_is_neutral(self):
        result = parse_llm_appraisal({})
        assert result.appraisal == AppraisalV1.neutral()

    def test_missing_valence_produces_fallback(self):
        result = parse_llm_appraisal({"arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.missing_required_field

    def test_missing_arousal_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.missing_required_field

    def test_missing_dominance_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": 0.0, "arousal_shift": 0.0})
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.missing_required_field

    def test_all_three_required_present_succeeds(self):
        result = parse_llm_appraisal({"valence_shift": 0.0, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert not result.is_fallback
        assert result.error_code is None


# ─── H9: discrete_emotions type rejection ────────────────────────────────────

class TestParserDiscreteEmotionsTypeRejection:
    """H9 — Non-mapping discrete_emotions produces fallback."""

    _BASE = {"valence_shift": 0.1, "arousal_shift": 0.0, "dominance_shift": 0.0}

    @pytest.mark.parametrize("bad_de", [
        None,
        "joy",
        ["joy"],
        42,
        0.5,
        True,
        False,
    ])
    def test_explicit_non_mapping_produces_fallback(self, bad_de):
        raw = {**self._BASE, "discrete_emotions": bad_de}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.unsupported_emotion

    def test_explicit_empty_mapping_succeeds(self):
        raw = {**self._BASE, "discrete_emotions": {}}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.discrete_emotions == {}

    def test_valid_mapping_with_known_emotion_succeeds(self):
        raw = {**self._BASE, "discrete_emotions": {"joy": 0.5}}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.discrete_emotions["joy"] == 0.5


# ─── H10: Unknown top-level key produces fallback ────────────────────────────

class TestParserUnknownTopLevelKey:
    """H10 — Unknown top-level keys produce unknown_top_level_key fallback."""

    _BASE = {"valence_shift": 0.1, "arousal_shift": 0.0, "dominance_shift": 0.0}

    @pytest.mark.parametrize("bad_key", [
        "extra_field",
        "schema_version",
        "coping_mode",
        "timestamp",
        "pleasure",
    ])
    def test_unknown_key_produces_fallback(self, bad_key):
        raw = {**self._BASE, bad_key: "whatever"}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.unknown_top_level_key


# ─── H11: triggered_emotions alias ───────────────────────────────────────────

class TestParserTriggeredEmotionsAlias:
    """H11 — triggered_emotions legacy alias is converted to discrete_emotions."""

    _BASE = {"valence_shift": 0.2, "arousal_shift": 0.0, "dominance_shift": 0.0}

    def test_triggered_emotions_converted(self):
        raw = {**self._BASE, "triggered_emotions": {"joy": 0.7}}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.discrete_emotions["joy"] == 0.7

    def test_triggered_emotions_empty_succeeds(self):
        raw = {**self._BASE, "triggered_emotions": {}}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert dict(result.appraisal.discrete_emotions) == {}

    def test_triggered_emotions_with_unknown_emotion_filtered(self):
        raw = {**self._BASE, "triggered_emotions": {"joy": 0.5, "invented": 0.9}}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert "joy" in result.appraisal.discrete_emotions
        assert "invented" not in result.appraisal.discrete_emotions

    def test_triggered_emotions_invalid_value_produces_fallback(self):
        raw = {**self._BASE, "triggered_emotions": {"joy": 99.0}}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    def test_triggered_emotions_none_produces_fallback(self):
        raw = {**self._BASE, "triggered_emotions": None}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.unsupported_emotion


# ─── H12: valence alias ──────────────────────────────────────────────────────

class TestParserValenceAlias:
    """H12 — valence legacy alias is converted to valence_shift."""

    def test_valence_alias_converted(self):
        raw = {"valence": 0.3, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.valence_shift == 0.3

    def test_valence_negative_accepted(self):
        raw = {"valence": -0.5, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.valence_shift == -0.5

    def test_valence_alias_same_as_canonical_accepted(self):
        """Both valence and valence_shift with the same value is accepted."""
        raw = {"valence": 0.3, "valence_shift": 0.3, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.valence_shift == 0.3


# ─── H13: Conflicting aliases rejected ───────────────────────────────────────

class TestParserConflictingAliases:
    """H13 — Conflicting alias+canonical produce conflicting_aliases fallback."""

    def test_valence_conflict_produces_fallback(self):
        raw = {
            "valence": 0.3,
            "valence_shift": 0.5,  # different value!
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    def test_triggered_emotions_conflict_produces_fallback(self):
        raw = {
            "valence_shift": 0.0,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "triggered_emotions": {"joy": 0.5},
            "discrete_emotions": {"anger": 0.3},  # different value!
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    def test_triggered_emotions_same_as_discrete_accepted(self):
        """Same object content in both aliases is accepted."""
        raw = {
            "valence_shift": 0.0,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "triggered_emotions": {"joy": 0.5},
            "discrete_emotions": {"joy": 0.5},
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback


# ─── H14: Unknown emotions filtered from LLM output ─────────────────────────

class TestParserUnknownEmotionsFiltered:
    """H14 — Unknown emotion keys from LLM are filtered, not rejected."""

    def test_unknown_emotions_filtered_not_rejected(self):
        raw = {
            "valence_shift": 0.1,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "discrete_emotions": {"joy": 0.5, "invented_emotion": 0.9, "fake": 1.0},
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert "joy" in result.appraisal.discrete_emotions
        assert "invented_emotion" not in result.appraisal.discrete_emotions
        assert "fake" not in result.appraisal.discrete_emotions

    def test_all_unknown_emotions_filtered_gives_empty(self):
        raw = {
            "valence_shift": 0.1,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "discrete_emotions": {"invented": 0.5},
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert dict(result.appraisal.discrete_emotions) == {}


# ─── H15: Sensitive marker not in observable result ──────────────────────────

class TestParserSensitiveMarkerNotLeaked:
    """H15 — Raw LLM/user text does not appear in error_code or is_fallback."""

    _SENSITIVE = "SUPER_SECRET_TOKEN_abc123"
    _BASE = {"valence_shift": 99.0, "arousal_shift": 0.0, "dominance_shift": 0.0}

    def test_sensitive_marker_not_in_error_code_value(self):
        """When a sensitive value is embedded in a field, it must not appear in error_code."""
        raw = {**self._BASE, self._SENSITIVE: "value"}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        # error_code is an enum value (stable string), not raw input
        code_str = result.error_code.value if result.error_code else ""
        assert self._SENSITIVE not in code_str

    def test_sensitive_value_not_in_error_code(self):
        """Sensitive value in shift must not appear in error_code."""
        raw = {"valence_shift": self._SENSITIVE, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        code_str = result.error_code.value if result.error_code else ""
        assert self._SENSITIVE not in code_str

    def test_parse_result_has_no_error_text_field(self):
        """ParseResult has error_code (enum), not a free-text error field."""
        result = parse_llm_appraisal(None)
        assert hasattr(result, "error_code")
        # Must NOT have a plain 'error' attribute with raw text
        assert not hasattr(result, "error") or getattr(result, "error", None) is None

    def test_parse_error_code_is_stable_enum(self):
        result = parse_llm_appraisal(None)
        assert isinstance(result.error_code, ParseErrorCode)
        assert result.error_code == ParseErrorCode.invalid_structure


# ─── H16: Migration rejects extra fields ─────────────────────────────────────

class TestMigrationRejectsExtraFields:
    """H16 — Legacy migration rejects any field beyond the exact allowed set."""

    def test_extra_field_rejected(self):
        legacy = _legacy_dict(extra_field="value")
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_timestamp_in_legacy_rejected(self):
        """Legacy snapshots must not have 'timestamp' (v1 field)."""
        legacy = _legacy_dict(timestamp=1_700_000_000.0)
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_prompt_field_rejected(self):
        legacy = _legacy_dict(system_prompt="do things")
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_memory_field_rejected(self):
        legacy = _legacy_dict(memory=[])
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_relationship_field_rejected(self):
        legacy = _legacy_dict(relationship_score=0.8)
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_presentation_field_rejected(self):
        legacy = _legacy_dict(acting_label="intense")
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)


# ─── H17: Migration rejects schema_version=None ──────────────────────────────

class TestMigrationRejectsSchemaVersionNone:
    """H17 — schema_version key present with value None is rejected."""

    def test_schema_version_none_rejected(self):
        """Key present but value is None — distinct from absent."""
        d = _legacy_dict()
        d["schema_version"] = None
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(d)

    def test_schema_version_absent_accepted_as_legacy(self):
        """Key entirely absent — treated as legacy format."""
        legacy = _legacy_dict()
        result = migrate_legacy_snapshot(legacy)
        assert isinstance(result, EmotionalStateV1)

    def test_schema_version_bool_rejected(self):
        d = _legacy_dict()
        d["schema_version"] = True
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(d)

    def test_schema_version_string_rejected(self):
        d = _legacy_dict()
        d["schema_version"] = "1"
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(d)


# ─── H18: Migration rejects last_update + timestamp simultaneously ────────────

class TestMigrationRejectsConflictingTimestampFields:
    """H18 — Payload with both last_update and timestamp is rejected."""

    def test_both_last_update_and_timestamp_rejected(self):
        d = _legacy_dict(timestamp=1_700_000_000.0)  # also has last_update
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(d)

    def test_only_last_update_accepted(self):
        d = _legacy_dict()
        assert "timestamp" not in d
        result = migrate_legacy_snapshot(d)
        assert result.timestamp == d["last_update"]

    def test_only_timestamp_in_v1_accepted(self):
        v1 = _valid_state_dict()
        assert "last_update" not in v1
        result = migrate_legacy_snapshot(v1)
        assert isinstance(result, EmotionalStateV1)


# ─── H19: Migration v1 idempotent ────────────────────────────────────────────

class TestMigrationV1Idempotent:
    """H19 — Passing a v1 snapshot to migrate_legacy_snapshot re-validates it."""

    def test_v1_snapshot_idempotent(self):
        state = EmotionalStateV1.create(**{k: v for k, v in _valid_state_kwargs().items()
                                           if k != "schema_version"},
                                        schema_version=EMOTIONAL_SCHEMA_VERSION)
        v1_dict = state.to_dict()
        result = migrate_legacy_snapshot(v1_dict)
        assert result == state

    def test_v1_snapshot_with_extra_field_rejected(self):
        v1 = _valid_state_dict()
        v1["extra"] = "bad"
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(v1)

    def test_v1_snapshot_with_last_update_rejected(self):
        """A v1 snapshot must not contain legacy 'last_update' field."""
        v1 = _valid_state_dict()
        v1["last_update"] = 1_700_000_000.0
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(v1)


# ─── H20: Isolated subprocess import ─────────────────────────────────────────

class TestIsolatedSubprocessImport:
    """H20 — Package import in a clean subprocess does not load infra modules."""

    def _run_isolation_script(self, script: str) -> subprocess.CompletedProcess:
        """Run a Python snippet in a subprocess with PYTHONPATH set."""
        import os
        env = {
            **os.environ,
            "PYTHONPATH": str(
                __import__("pathlib").Path(__file__).parent.parent.parent
            ),
            # Prevent HF/transformers network access
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    def test_import_does_not_load_fastapi(self):
        proc = self._run_isolation_script("""
            import sys
            import backend.emotional_domain
            for mod in sys.modules:
                assert 'fastapi' not in mod, f'fastapi loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_import_does_not_load_groq(self):
        proc = self._run_isolation_script("""
            import sys
            import backend.emotional_domain
            for mod in sys.modules:
                assert 'groq' not in mod, f'groq loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_import_does_not_load_supabase(self):
        proc = self._run_isolation_script("""
            import sys
            import backend.emotional_domain
            for mod in sys.modules:
                assert 'supabase' not in mod, f'supabase loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_import_does_not_load_sentence_transformers(self):
        proc = self._run_isolation_script("""
            import sys
            import backend.emotional_domain
            for mod in sys.modules:
                assert 'sentence_transformers' not in mod, f'loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_import_does_not_require_env_vars(self):
        proc = self._run_isolation_script("""
            import os
            # Unset common env vars
            for k in ['GROQ_API_KEY', 'GROQ_API_KEY_2', 'SUPABASE_URL', 'SUPABASE_KEY']:
                os.environ.pop(k, None)
            import backend.emotional_domain
            from backend.emotional_domain import EmotionalStateV1, AppraisalV1
            s = EmotionalStateV1.neutral(timestamp=1.0)
            a = AppraisalV1.neutral()
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_package_api_usable_in_isolation(self):
        """Full package API works in isolation: create, serialise, migrate."""
        proc = self._run_isolation_script("""
            from backend.emotional_domain import (
                EmotionalStateV1, AppraisalV1,
                serialize_state, deserialize_state,
                serialize_appraisal, deserialize_appraisal,
                migrate_legacy_snapshot, parse_llm_appraisal,
                ParseResult, ParseErrorCode,
            )
            # Create
            state = EmotionalStateV1.neutral(timestamp=1_700_000_000.0)
            ap = AppraisalV1.neutral()
            # Round-trip
            assert deserialize_state(serialize_state(state)) == state
            assert deserialize_appraisal(serialize_appraisal(ap)) == ap
            # Parser
            r = parse_llm_appraisal({'valence_shift': 0.1, 'arousal_shift': 0.0, 'dominance_shift': 0.0})
            assert not r.is_fallback
            # Migration
            legacy = {
                'pleasure': 0.0, 'arousal': 0.0, 'dominance': 0.0,
                'libido': 0.0, 'aggression': 0.0, 'connection': 0.5,
                'energy': 0.8, 'tension': 0.0, 'coping_mode': 'HEALTHY',
                'last_update': 1_700_000_000.0,
            }
            migrated = migrate_legacy_snapshot(legacy)
            assert migrated.schema_version == 1
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout


# ─── Original round-trip tests (1 & 2) ───────────────────────────────────────

class TestStateRoundTrip:
    """Requirement 1: round-trip EmotionalStateV1."""

    def test_to_dict_from_dict(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        reconstructed = EmotionalStateV1.from_dict(state.to_dict())
        assert state == reconstructed

    def test_serialize_deserialize(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        json_str = serialize_state(state)
        reconstructed = deserialize_state(json_str)
        assert state == reconstructed

    def test_json_includes_schema_version(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        data = json.loads(serialize_state(state))
        assert data["schema_version"] == EMOTIONAL_SCHEMA_VERSION

    def test_json_sorted_keys(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        json_str = serialize_state(state)
        keys = list(json.loads(json_str).keys())
        assert keys == sorted(keys)

    def test_json_no_extra_fields(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        data = json.loads(serialize_state(state))
        expected_keys = {
            "schema_version", "pleasure", "arousal", "dominance",
            "libido", "aggression", "connection", "energy", "tension",
            "coping_mode", "timestamp",
        }
        assert set(data.keys()) == expected_keys

    def test_neutral_round_trip(self):
        state = EmotionalStateV1.neutral(timestamp=1.0)
        reconstructed = EmotionalStateV1.from_dict(state.to_dict())
        assert state == reconstructed


class TestAppraisalRoundTrip:
    """Requirement 2: round-trip AppraisalV1."""

    def test_to_dict_from_dict(self):
        appraisal = AppraisalV1.from_dict(_valid_appraisal_dict())
        reconstructed = AppraisalV1.from_dict(appraisal.to_dict())
        assert appraisal == reconstructed

    def test_serialize_deserialize(self):
        appraisal = AppraisalV1.from_dict(_valid_appraisal_dict())
        json_str = serialize_appraisal(appraisal)
        reconstructed = deserialize_appraisal(json_str)
        assert appraisal == reconstructed

    def test_json_includes_schema_version(self):
        appraisal = AppraisalV1.from_dict(_valid_appraisal_dict())
        data = json.loads(serialize_appraisal(appraisal))
        assert data["schema_version"] == EMOTIONAL_SCHEMA_VERSION

    def test_json_no_extra_fields(self):
        appraisal = AppraisalV1.from_dict(_valid_appraisal_dict())
        data = json.loads(serialize_appraisal(appraisal))
        expected_keys = {
            "schema_version", "valence_shift", "arousal_shift",
            "dominance_shift", "discrete_emotions",
        }
        assert set(data.keys()) == expected_keys

    def test_neutral_round_trip(self):
        neutral = AppraisalV1.neutral()
        reconstructed = AppraisalV1.from_dict(neutral.to_dict())
        assert neutral == reconstructed

    def test_neutral_all_zeros(self):
        neutral = AppraisalV1.neutral()
        assert neutral.valence_shift == 0.0
        assert neutral.arousal_shift == 0.0
        assert neutral.dominance_shift == 0.0
        assert dict(neutral.discrete_emotions) == {}
        assert neutral.schema_version == EMOTIONAL_SCHEMA_VERSION


# ─── Version validation (3 & 4) ──────────────────────────────────────────────

class TestMissingVersion:
    def test_state_missing_version(self):
        d = _valid_state_dict()
        del d["schema_version"]
        with pytest.raises(EmotionalDomainError, match="schema_version"):
            EmotionalStateV1.from_dict(d)

    def test_appraisal_missing_version(self):
        d = _valid_appraisal_dict()
        del d["schema_version"]
        with pytest.raises(EmotionalDomainError, match="schema_version"):
            AppraisalV1.from_dict(d)


class TestUnknownVersion:
    @pytest.mark.parametrize("bad_version", [0, 2, 99, -1])
    def test_state_unknown_version(self, bad_version):
        d = _valid_state_dict(schema_version=bad_version)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    @pytest.mark.parametrize("bad_version", [0, 2, 99, -1])
    def test_appraisal_unknown_version(self, bad_version):
        d = _valid_appraisal_dict(schema_version=bad_version)
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)


# ─── Type validation (5) ──────────────────────────────────────────────────────

_STATE_NUMERIC_FIELDS = [
    "pleasure", "arousal", "dominance",
    "libido", "aggression", "connection", "energy", "tension",
]
_APPRAISAL_NUMERIC_FIELDS = ["valence_shift", "arousal_shift", "dominance_shift"]


class TestInvalidTypesState:
    @pytest.mark.parametrize("field_name", _STATE_NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [True, False, None, "0.5", [0.5], {"v": 0.5}])
    def test_state_rejects_bad_type(self, field_name, bad_value):
        d = _valid_state_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)


class TestInvalidTypesAppraisal:
    @pytest.mark.parametrize("field_name", _APPRAISAL_NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [True, False, None, "0.5", [0.5], {"v": 0.5}])
    def test_appraisal_rejects_bad_type(self, field_name, bad_value):
        d = _valid_appraisal_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_appraisal_rejects_bool_intensity(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": True})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_appraisal_rejects_none_intensity(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": None})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_appraisal_rejects_str_intensity(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": "0.5"})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)


# ─── NaN/Inf (6) ─────────────────────────────────────────────────────────────

class TestNanInf:
    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
    @pytest.mark.parametrize("field_name", _STATE_NUMERIC_FIELDS)
    def test_state_nan_inf(self, field_name, bad_value):
        d = _valid_state_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
    @pytest.mark.parametrize("field_name", _APPRAISAL_NUMERIC_FIELDS)
    def test_appraisal_nan_inf(self, field_name, bad_value):
        d = _valid_appraisal_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    @pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
    def test_appraisal_nan_inf_intensity(self, bad_value):
        d = _valid_appraisal_dict(discrete_emotions={"joy": bad_value})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)


# ─── Out-of-range (7) ────────────────────────────────────────────────────────

class TestOutOfRange:
    @pytest.mark.parametrize("field_name,lo,hi", [
        ("pleasure", -1.0, 1.0),
        ("arousal", -1.0, 1.0),
        ("dominance", -1.0, 1.0),
    ])
    @pytest.mark.parametrize("bad_value", [-1.001, 1.001, -2.0, 2.0])
    def test_state_pad_out_of_range(self, field_name, lo, hi, bad_value):
        d = _valid_state_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    @pytest.mark.parametrize("field_name", ["libido", "aggression", "connection", "energy", "tension"])
    @pytest.mark.parametrize("bad_value", [-0.001, 1.001, -1.0, 2.0])
    def test_state_drives_out_of_range(self, field_name, bad_value):
        d = _valid_state_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    @pytest.mark.parametrize("field_name", _APPRAISAL_NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [-1.001, 1.001, -2.0, 2.0])
    def test_appraisal_shifts_out_of_range(self, field_name, bad_value):
        d = _valid_appraisal_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    @pytest.mark.parametrize("bad_value", [-0.001, 1.001])
    def test_appraisal_intensity_out_of_range(self, bad_value):
        d = _valid_appraisal_dict(discrete_emotions={"joy": bad_value})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_state_boundary_values_accepted(self):
        d = _valid_state_dict(pleasure=-1.0, arousal=0.0, dominance=1.0)
        state = EmotionalStateV1.from_dict(d)
        assert state.pleasure == -1.0
        assert state.dominance == 1.0


# ─── Unknown keys (8) ────────────────────────────────────────────────────────

class TestUnknownKeys:
    def test_state_rejects_unknown_key(self):
        d = _valid_state_dict()
        d["unknown_field"] = 42
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_appraisal_rejects_unknown_key(self):
        d = _valid_appraisal_dict()
        d["extra"] = "value"
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_state_rejects_prompt_field(self):
        d = _valid_state_dict(system_prompt="do evil things")
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)


# ─── Discrete emotion allowlist (9 & 10) ─────────────────────────────────────

class TestDiscreteEmotionAllowlist:
    def test_allowlist_includes_production_emotions(self):
        """All emotions used by _perceive() and RelationshipManager must be present."""
        for emo in ["tenderness", "guilt", "pride", "jealousy", "gratitude"]:
            assert emo in DISCRETE_EMOTIONS, f"Missing production emotion: {emo}"

    def test_allowlist_contains_expected_set(self):
        expected = frozenset({
            "joy", "sadness", "anger", "fear",
            "disgust", "surprise", "trust", "anticipation",
            "tenderness", "guilt", "pride", "jealousy", "gratitude",
        })
        assert DISCRETE_EMOTIONS == expected

    def test_all_known_emotions_accepted(self):
        emotions = {e: 0.5 for e in DISCRETE_EMOTIONS}
        d = _valid_appraisal_dict(discrete_emotions=emotions)
        appraisal = AppraisalV1.from_dict(d)
        assert set(appraisal.discrete_emotions.keys()) == DISCRETE_EMOTIONS

    def test_unknown_emotion_rejected(self):
        d = _valid_appraisal_dict(discrete_emotions={"unknown_emotion": 0.5})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_empty_discrete_emotions_accepted(self):
        d = _valid_appraisal_dict(discrete_emotions={})
        appraisal = AppraisalV1.from_dict(d)
        assert dict(appraisal.discrete_emotions) == {}


# ─── Coping mode (11) ────────────────────────────────────────────────────────

class TestCopingMode:
    @pytest.mark.parametrize("mode", sorted(VALID_COPING_MODES))
    def test_known_coping_modes_accepted(self, mode):
        d = _valid_state_dict(coping_mode=mode)
        state = EmotionalStateV1.from_dict(d)
        assert state.coping_mode == mode

    @pytest.mark.parametrize("bad_mode", ["PANIC", "NORMAL", "healthy", "FREEZE", "", "0"])
    def test_unknown_coping_mode_rejected(self, bad_mode):
        d = _valid_state_dict(coping_mode=bad_mode)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_coping_mode_allowlist_is_exact(self):
        expected = frozenset({"HEALTHY", "DEFENSIVE", "DISSOCIATED", "MANIC"})
        assert VALID_COPING_MODES == expected


# ─── Timestamp (12) ──────────────────────────────────────────────────────────

class TestTimestamp:
    def test_valid_timestamp_accepted(self):
        d = _valid_state_dict(timestamp=1_700_000_000.0)
        state = EmotionalStateV1.from_dict(d)
        assert state.timestamp == 1_700_000_000.0

    def test_zero_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=0.0)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_negative_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=-1.0)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_nan_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=float("nan"))
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_string_timestamp_rejected(self):
        d = _valid_state_dict(timestamp="2024-01-01")
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_bool_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=True)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)


# ─── Migration valid legacy (13) ─────────────────────────────────────────────

class TestMigrationValidLegacy:
    def test_basic_migration(self):
        legacy = _legacy_dict()
        result = migrate_legacy_snapshot(legacy)
        assert isinstance(result, EmotionalStateV1)
        assert result.schema_version == EMOTIONAL_SCHEMA_VERSION

    def test_field_mapping(self):
        legacy = _legacy_dict(pleasure=0.5, arousal=-0.3, dominance=0.2, last_update=1_700_000_000.0)
        result = migrate_legacy_snapshot(legacy)
        assert result.pleasure == 0.5
        assert result.arousal == -0.3
        assert result.timestamp == 1_700_000_000.0

    def test_last_update_becomes_timestamp(self):
        ts = 1_700_123_456.789
        legacy = _legacy_dict(last_update=ts)
        result = migrate_legacy_snapshot(legacy)
        assert result.timestamp == ts

    def test_all_fields_preserved(self):
        legacy = _legacy_dict(
            libido=0.4, aggression=0.2, connection=0.7,
            energy=0.9, tension=0.1, coping_mode="DEFENSIVE",
        )
        result = migrate_legacy_snapshot(legacy)
        assert result.libido == 0.4
        assert result.coping_mode == "DEFENSIVE"


# ─── Migration invalid (14) ──────────────────────────────────────────────────

class TestMigrationInvalidLegacy:
    def test_non_dict_rejected(self):
        for bad in [None, "string", 42, [], ()]:
            with pytest.raises(EmotionalDomainError):
                migrate_legacy_snapshot(bad)

    def test_missing_last_update_rejected(self):
        legacy = _legacy_dict()
        del legacy["last_update"]
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_missing_pleasure_rejected(self):
        legacy = _legacy_dict()
        del legacy["pleasure"]
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_invalid_value_rejected(self):
        legacy = _legacy_dict(pleasure="invalid")
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_out_of_range_rejected(self):
        legacy = _legacy_dict(pleasure=99.0)
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_empty_dict_rejected(self):
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot({})


# ─── Migration no mutation (15) ──────────────────────────────────────────────

class TestMigrationNoMutation:
    def test_input_not_mutated(self):
        import copy
        legacy = _legacy_dict()
        original = copy.deepcopy(legacy)
        migrate_legacy_snapshot(legacy)
        assert legacy == original

    def test_input_not_mutated_on_v1(self):
        import copy
        v1 = _valid_state_dict()
        original = copy.deepcopy(v1)
        migrate_legacy_snapshot(v1)
        assert v1 == original


# ─── Parser fallback (16) ────────────────────────────────────────────────────

class TestAppraisalParserFallback:
    def test_valid_dict_parses_correctly(self):
        raw = {
            "valence_shift": 0.3,
            "arousal_shift": -0.1,
            "dominance_shift": 0.0,
            "discrete_emotions": {"joy": 0.7},
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.error_code is None
        assert result.appraisal.valence_shift == 0.3

    def test_none_produces_fallback(self):
        result = parse_llm_appraisal(None)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_structure
        assert result.appraisal == AppraisalV1.neutral()

    def test_string_produces_fallback(self):
        result = parse_llm_appraisal("bad output")
        assert result.is_fallback

    def test_out_of_range_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": 99.0, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    def test_nan_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": float("nan"), "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback

    def test_bool_shift_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": True, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback

    def test_fallback_neutral_has_correct_schema_version(self):
        result = parse_llm_appraisal(None)
        assert result.appraisal.schema_version == EMOTIONAL_SCHEMA_VERSION

    def test_parse_result_is_not_empty_dict(self):
        result = parse_llm_appraisal("garbage")
        assert isinstance(result.appraisal, AppraisalV1)
        assert result.appraisal == AppraisalV1.neutral()

    def test_parse_error_code_is_enum(self):
        result = parse_llm_appraisal(None)
        assert isinstance(result.error_code, ParseErrorCode)


# ─── O1-O7: OverflowError tests ────────────────────────────────────────────

class TestOverflowError:
    """
    O1-O7 — Integers too large to convert to float (e.g. 10**10000) must
    produce EmotionalDomainError, never OverflowError.
    """

    _HUGE = 10 ** 10000

    # -- State PAD fields (O1) --
    @pytest.mark.parametrize("field", ["pleasure", "arousal", "dominance"])
    def test_huge_int_in_pad_rejected(self, field):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(**{field: self._HUGE}))

    def test_huge_int_in_pad_create_rejected(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.create(
                **_valid_state_kwargs(pleasure=self._HUGE, **{k: v for k, v in
                    _valid_state_kwargs().items() if k != "pleasure" and k != "schema_version"},
                    schema_version=EMOTIONAL_SCHEMA_VERSION
                )
            )

    def test_huge_int_in_pad_from_dict_rejected(self):
        d = _valid_state_dict(pleasure=self._HUGE)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    # -- State drive fields (O2) --
    @pytest.mark.parametrize("field", ["libido", "aggression", "connection", "energy", "tension"])
    def test_huge_int_in_drive_rejected(self, field):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(**{field: self._HUGE}))

    def test_huge_int_in_drive_create_rejected(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.create(
                **{k: v for k, v in _valid_state_kwargs(libido=self._HUGE).items()
                   if k != "schema_version"},
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    # -- State timestamp (O3) --
    def test_huge_int_in_timestamp_rejected(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1(**_valid_state_kwargs(timestamp=self._HUGE))

    def test_huge_int_in_timestamp_create_rejected(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.create(
                **{k: v for k, v in _valid_state_kwargs().items()
                   if k != "timestamp" and k != "schema_version"},
                timestamp=self._HUGE,
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_huge_int_in_timestamp_from_dict_rejected(self):
        d = _valid_state_dict(timestamp=self._HUGE)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_huge_int_in_timestamp_neutral_rejected(self):
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.neutral(timestamp=self._HUGE)

    # -- Appraisal shift fields (O4) --
    @pytest.mark.parametrize("field", ["valence_shift", "arousal_shift", "dominance_shift"])
    def test_huge_int_in_shift_rejected(self, field):
        d = _valid_appraisal_dict(**{field: self._HUGE})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_huge_int_in_shift_direct_rejected(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=self._HUGE, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={}, schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_huge_int_in_shift_create_rejected(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.create(
                valence_shift=self._HUGE, arousal_shift=0.0, dominance_shift=0.0,
            )

    # -- Emotion intensity (O5) --
    def test_huge_int_in_emotion_intensity_rejected(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": self._HUGE})
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.from_dict(d)

    def test_huge_int_in_emotion_intensity_direct_rejected(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={"joy": self._HUGE},
                schema_version=EMOTIONAL_SCHEMA_VERSION,
            )

    def test_huge_int_in_emotion_intensity_create_rejected(self):
        with pytest.raises(EmotionalDomainError):
            AppraisalV1.create(
                valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0,
                discrete_emotions={"joy": self._HUGE},
            )

    # -- Legacy migration with huge int (O6) --
    def test_migration_legacy_huge_int_rejected(self):
        legacy = _legacy_dict(pleasure=self._HUGE)
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_migration_v1_huge_int_rejected(self):
        v1 = _valid_state_dict(timestamp=self._HUGE)
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(v1)

    # -- Parser maps huge int to invalid_numeric_value (O7) --
    def test_parser_huge_int_maps_to_invalid_numeric_value(self):
        raw = {"valence_shift": 0.1, "arousal_shift": self._HUGE, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    def test_parser_huge_int_in_emotion_maps_to_invalid_numeric_value(self):
        raw = {
            "valence_shift": 0.0, "arousal_shift": 0.0, "dominance_shift": 0.0,
            "discrete_emotions": {"joy": self._HUGE},
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        # huge int in emotion intensity goes through _parse_discrete_emotions
        # which catches EmotionalDomainError and raises _ParserFailure(invalid_numeric_value)
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    def test_parser_huge_int_in_valence_maps_to_invalid_numeric_value(self):
        raw = {"valence": self._HUGE, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_numeric_value


# ─── B1-B6: Bool vs int alias tests ─────────────────────────────────────────

class TestBoolAliasEquivalence:
    """
    B1-B6 — bool and int must not be treated as equivalent in alias checking.
    True == 1 and False == 0 in Python, which would otherwise allow bypass.
    """

    _BASE = {"arousal_shift": 0.0, "dominance_shift": 0.0}

    # B1: valence=True, valence_shift=1 → conflicting_aliases
    def test_valence_true_vs_int_one(self):
        raw = {"valence": True, "valence_shift": 1, **self._BASE}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    # B2: valence=False, valence_shift=0 → conflicting_aliases
    def test_valence_false_vs_int_zero(self):
        raw = {"valence": False, "valence_shift": 0, **self._BASE}
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    # B3: triggered_emotions with bool values vs discrete_emotions with int
    def test_triggered_bool_vs_discrete_int_joy(self):
        raw = {
            **self._BASE,
            "valence_shift": 0.0,
            "triggered_emotions": {"joy": True},
            "discrete_emotions": {"joy": 1},
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    # B4: triggered_emotions with bool False vs discrete_emotions with int 0
    def test_triggered_bool_false_vs_discrete_int_zero(self):
        raw = {
            **self._BASE,
            "valence_shift": 0.0,
            "triggered_emotions": {"joy": False},
            "discrete_emotions": {"joy": 0},
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.conflicting_aliases

    # B5: Both aliases with equally invalid values → fallback (not success)
    def test_both_aliases_equally_invalid(self):
        """Both alias and canonical have the same string value → they ARE
        equivalent (same value), so no conflict.  The invalid string is caught
        by later validation as invalid_numeric_value."""
        raw = {
            "valence": "invalid",
            "valence_shift": "invalid",
            **self._BASE,
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        # Same (invalid) value → no alias conflict; validation catches it.
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    def test_both_triggered_equally_invalid(self):
        """Both triggered_emotions and discrete_emotions have the same
        invalid intensity string → they ARE equivalent (same values inside).
        No alias conflict; the invalid intensity is caught later."""
        raw = {
            **self._BASE,
            "valence_shift": 0.0,
            "triggered_emotions": {"joy": "high"},
            "discrete_emotions": {"joy": "high"},
        }
        result = parse_llm_appraisal(raw)
        assert result.is_fallback
        assert result.error_code == ParseErrorCode.invalid_numeric_value

    # B6: 1 vs 1.0 is accepted (normal float equivalence)
    def test_one_vs_one_point_zero_accepted(self):
        """1 and 1.0 are both valid floats with the same value."""
        raw = {"valence": 1.0, "valence_shift": 1, **self._BASE}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback, f"Should be accepted, got {result.error_code}"
        assert result.appraisal.valence_shift == 1.0

    def test_int_vs_float_equivalence(self):
        """int and float with same value should be equivalent."""
        raw = {"valence": 0, "valence_shift": 0.0, **self._BASE}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback, f"Should be accepted, got {result.error_code}"
        assert result.appraisal.valence_shift == 0.0


# ─── Package public API exports ───────────────────────────────────────────────

class TestPackageExports:
    """ParseResult and ParseErrorCode are exported from the package."""

    def test_parse_result_exported(self):
        assert PackageParseResult is ParseResult

    def test_parse_error_code_exported(self):
        assert PackageParseErrorCode is ParseErrorCode

    def test_package_parse_works(self):
        r = package_parse({"valence_shift": 0.1, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert not r.is_fallback


# ─── Serialization edge cases ────────────────────────────────────────────────

class TestSerializationEdgeCases:
    def test_deserialize_state_rejects_non_string(self):
        with pytest.raises(EmotionalDomainError):
            deserialize_state(42)

    def test_deserialize_state_rejects_bad_json(self):
        with pytest.raises(EmotionalDomainError):
            deserialize_state("{not json}")

    def test_deserialize_appraisal_rejects_non_string(self):
        with pytest.raises(EmotionalDomainError):
            deserialize_appraisal(None)

    def test_serialize_state_rejects_wrong_type(self):
        with pytest.raises(EmotionalDomainError):
            serialize_state("not a state")

    def test_serialize_appraisal_rejects_wrong_type(self):
        with pytest.raises(EmotionalDomainError):
            serialize_appraisal({"valence": 0.1})

    def test_deterministic_output(self):
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        s1 = serialize_state(state)
        s2 = serialize_state(state)
        assert s1 == s2
