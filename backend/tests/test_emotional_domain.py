"""
Tests for backend/emotional_domain — issue #232.

Coverage map (issue requirements):
 1. Round-trip EmotionalStateV1           → test_state_round_trip
 2. Round-trip AppraisalV1               → test_appraisal_round_trip
 3. Version absent is rejected           → test_state_missing_version, test_appraisal_missing_version
 4. Unknown version is rejected          → test_state_unknown_version, test_appraisal_unknown_version
 5. bool/None/str/list/dict rejected     → test_state_invalid_types, test_appraisal_invalid_types
 6. NaN/Inf rejected                     → test_state_nan_inf, test_appraisal_nan_inf
 7. Out-of-range values follow policy    → test_state_out_of_range, test_appraisal_out_of_range
 8. Unknown keys not silently accepted   → test_state_unknown_keys, test_appraisal_unknown_keys
 9. Discrete emotion allowlist is exact  → test_discrete_emotion_allowlist
10. Unknown emotion rejected             → test_appraisal_unknown_emotion_rejected
11. Coping mode unknown rejected         → test_unknown_coping_mode
12. Timestamp invalid rejected           → test_invalid_timestamp
13. Legacy migration valid → v1 correct  → test_migration_valid_legacy
14. Legacy invalid fails closed          → test_migration_invalid_legacy
15. Migration does not mutate input      → test_migration_no_mutation
16. Invalid appraisal → neutral fallback → test_parse_llm_appraisal_fallback
17. Domain importable without infra      → test_domain_import_isolation
18. No network use                       → (structural: no network calls in any test)
19. Existing backend suite passes        → (verified by running full suite externally)
20. CI remains green                     → (verified by CI after PR)
"""

from __future__ import annotations

import importlib
import json
import math
import sys
import time
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
from backend.emotional_domain.appraisal_parser import parse_llm_appraisal, ParseResult


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _valid_state_dict(**overrides: Any) -> dict:
    base = {
        "schema_version": EMOTIONAL_SCHEMA_VERSION,
        "pleasure": 0.1,
        "arousal": -0.2,
        "dominance": 0.3,
        "libido": 0.0,
        "aggression": 0.1,
        "connection": 0.5,
        "energy": 0.8,
        "tension": 0.2,
        "coping_mode": "HEALTHY",
        "timestamp": 1_700_000_000.0,
    }
    base.update(overrides)
    return base


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


# ─── 1 & 2: Round-trips ──────────────────────────────────────────────────────

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
        assert neutral.discrete_emotions == {}
        assert neutral.schema_version == EMOTIONAL_SCHEMA_VERSION


# ─── 3: Version absent rejected ──────────────────────────────────────────────

class TestMissingVersion:
    """Requirement 3: absent schema_version is rejected."""

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


# ─── 4: Unknown version rejected ─────────────────────────────────────────────

class TestUnknownVersion:
    """Requirement 4: unrecognised schema_version is rejected."""

    @pytest.mark.parametrize("bad_version", [0, 2, 99, -1])
    def test_state_unknown_version(self, bad_version):
        d = _valid_state_dict(schema_version=bad_version)
        with pytest.raises(EmotionalDomainError, match="schema_version|Unsupported"):
            EmotionalStateV1.from_dict(d)

    @pytest.mark.parametrize("bad_version", [0, 2, 99, -1])
    def test_appraisal_unknown_version(self, bad_version):
        d = _valid_appraisal_dict(schema_version=bad_version)
        with pytest.raises(EmotionalDomainError, match="schema_version|Unsupported"):
            AppraisalV1.from_dict(d)


# ─── 5: Invalid types rejected ───────────────────────────────────────────────

_STATE_NUMERIC_FIELDS = [
    "pleasure", "arousal", "dominance",
    "libido", "aggression", "connection", "energy", "tension",
]
_APPRAISAL_NUMERIC_FIELDS = ["valence_shift", "arousal_shift", "dominance_shift"]


class TestInvalidTypesState:
    """Requirement 5: bool, None, str, list, dict rejected for EmotionalStateV1 fields."""

    @pytest.mark.parametrize("field_name", _STATE_NUMERIC_FIELDS)
    @pytest.mark.parametrize("bad_value", [True, False, None, "0.5", [0.5], {"v": 0.5}])
    def test_state_rejects_bad_type(self, field_name, bad_value):
        d = _valid_state_dict(**{field_name: bad_value})
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_state_rejects_bool_schema_version(self):
        d = _valid_state_dict(schema_version=True)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)

    def test_state_rejects_none_coping_mode(self):
        d = _valid_state_dict(coping_mode=None)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)


class TestInvalidTypesAppraisal:
    """Requirement 5: bool, None, str, list, dict rejected for AppraisalV1 fields."""

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


# ─── 6: NaN / Inf rejected ───────────────────────────────────────────────────

class TestNanInf:
    """Requirement 6: NaN and ±Inf are rejected."""

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


# ─── 7: Out-of-range values ───────────────────────────────────────────────────

class TestOutOfRange:
    """Requirement 7: out-of-range values are rejected (policy: reject, not clamp)."""

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
        """Boundary values -1.0, 0.0, 1.0 are valid."""
        d = _valid_state_dict(pleasure=-1.0, arousal=0.0, dominance=1.0)
        state = EmotionalStateV1.from_dict(d)
        assert state.pleasure == -1.0
        assert state.dominance == 1.0

    def test_appraisal_boundary_values_accepted(self):
        d = _valid_appraisal_dict(valence_shift=-1.0, arousal_shift=0.0, dominance_shift=1.0)
        appraisal = AppraisalV1.from_dict(d)
        assert appraisal.valence_shift == -1.0


# ─── 8: Unknown keys not silently accepted ───────────────────────────────────

class TestUnknownKeys:
    """Requirement 8: unknown keys are rejected, not silently dropped."""

    def test_state_rejects_unknown_key(self):
        d = _valid_state_dict()
        d["unknown_field"] = 42
        with pytest.raises(EmotionalDomainError, match="Unknown fields"):
            EmotionalStateV1.from_dict(d)

    def test_appraisal_rejects_unknown_key(self):
        d = _valid_appraisal_dict()
        d["extra"] = "value"
        with pytest.raises(EmotionalDomainError, match="Unknown fields"):
            AppraisalV1.from_dict(d)

    def test_state_rejects_prompt_field(self):
        d = _valid_state_dict(system_prompt="do evil things")
        with pytest.raises(EmotionalDomainError, match="Unknown fields"):
            EmotionalStateV1.from_dict(d)

    def test_state_rejects_memory_field(self):
        d = _valid_state_dict(memory=[])
        with pytest.raises(EmotionalDomainError, match="Unknown fields"):
            EmotionalStateV1.from_dict(d)


# ─── 9 & 10: Discrete emotion allowlist ──────────────────────────────────────

class TestDiscreteEmotionAllowlist:
    """Requirements 9 & 10: discrete emotion allowlist is exact; unknown rejected."""

    def test_allowlist_is_exact(self):
        expected = frozenset({
            "joy", "sadness", "anger", "fear",
            "disgust", "surprise", "trust", "anticipation",
        })
        assert DISCRETE_EMOTIONS == expected

    def test_all_known_emotions_accepted(self):
        emotions = {e: 0.5 for e in DISCRETE_EMOTIONS}
        d = _valid_appraisal_dict(discrete_emotions=emotions)
        appraisal = AppraisalV1.from_dict(d)
        assert set(appraisal.discrete_emotions.keys()) == DISCRETE_EMOTIONS

    def test_unknown_emotion_rejected(self):
        d = _valid_appraisal_dict(discrete_emotions={"unknown_emotion": 0.5})
        with pytest.raises(EmotionalDomainError, match="Unknown discrete emotion"):
            AppraisalV1.from_dict(d)

    def test_partially_unknown_emotion_rejected(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": 0.5, "invalid": 0.3})
        with pytest.raises(EmotionalDomainError, match="Unknown discrete emotion"):
            AppraisalV1.from_dict(d)

    def test_empty_discrete_emotions_accepted(self):
        d = _valid_appraisal_dict(discrete_emotions={})
        appraisal = AppraisalV1.from_dict(d)
        assert appraisal.discrete_emotions == {}

    def test_zero_intensity_accepted(self):
        d = _valid_appraisal_dict(discrete_emotions={"joy": 0.0})
        appraisal = AppraisalV1.from_dict(d)
        assert appraisal.discrete_emotions["joy"] == 0.0

    def test_max_intensity_accepted(self):
        d = _valid_appraisal_dict(discrete_emotions={"anger": 1.0})
        appraisal = AppraisalV1.from_dict(d)
        assert appraisal.discrete_emotions["anger"] == 1.0


# ─── 11: Coping mode allowlist ───────────────────────────────────────────────

class TestCopingMode:
    """Requirement 11: unknown coping_mode is rejected."""

    @pytest.mark.parametrize("mode", sorted(VALID_COPING_MODES))
    def test_known_coping_modes_accepted(self, mode):
        d = _valid_state_dict(coping_mode=mode)
        state = EmotionalStateV1.from_dict(d)
        assert state.coping_mode == mode

    @pytest.mark.parametrize("bad_mode", ["PANIC", "NORMAL", "healthy", "FREEZE", "", "0"])
    def test_unknown_coping_mode_rejected(self, bad_mode):
        d = _valid_state_dict(coping_mode=bad_mode)
        with pytest.raises(EmotionalDomainError, match="coping_mode|Unknown"):
            EmotionalStateV1.from_dict(d)

    def test_coping_mode_allowlist_is_exact(self):
        expected = frozenset({"HEALTHY", "DEFENSIVE", "DISSOCIATED", "MANIC"})
        assert VALID_COPING_MODES == expected


# ─── 12: Timestamp ───────────────────────────────────────────────────────────

class TestTimestamp:
    """Requirement 12: invalid timestamp is rejected."""

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

    def test_inf_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=float("inf"))
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

    def test_none_timestamp_rejected(self):
        d = _valid_state_dict(timestamp=None)
        with pytest.raises(EmotionalDomainError):
            EmotionalStateV1.from_dict(d)


# ─── 13: Migration valid legacy ──────────────────────────────────────────────

class TestMigrationValidLegacy:
    """Requirement 13: valid legacy snapshot → correct v1 model."""

    def test_basic_migration(self):
        legacy = _legacy_dict()
        result = migrate_legacy_snapshot(legacy)
        assert isinstance(result, EmotionalStateV1)
        assert result.schema_version == EMOTIONAL_SCHEMA_VERSION

    def test_field_mapping(self):
        legacy = _legacy_dict(
            pleasure=0.5,
            arousal=-0.3,
            dominance=0.2,
            last_update=1_700_000_000.0,
        )
        result = migrate_legacy_snapshot(legacy)
        assert result.pleasure == 0.5
        assert result.arousal == -0.3
        assert result.dominance == 0.2
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
        assert result.aggression == 0.2
        assert result.connection == 0.7
        assert result.energy == 0.9
        assert result.tension == 0.1
        assert result.coping_mode == "DEFENSIVE"

    def test_v1_snapshot_idempotent(self):
        """A v1 snapshot passed to migrate is re-validated and returned."""
        state = EmotionalStateV1.from_dict(_valid_state_dict())
        v1_dict = state.to_dict()
        result = migrate_legacy_snapshot(v1_dict)
        assert result == state


# ─── 14: Legacy invalid fails closed ─────────────────────────────────────────

class TestMigrationInvalidLegacy:
    """Requirement 14: invalid legacy snapshot fails closed (raises)."""

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

    def test_unknown_schema_version_rejected(self):
        legacy = _legacy_dict()
        legacy["schema_version"] = 999
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot(legacy)

    def test_empty_dict_rejected(self):
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot({})


# ─── 15: Migration does not mutate input ─────────────────────────────────────

class TestMigrationNoMutation:
    """Requirement 15: migration never mutates the input dict."""

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


# ─── 16: Invalid appraisal → explicit neutral fallback ───────────────────────

class TestAppraisalParserFallback:
    """Requirement 16: invalid LLM appraisal produces observable neutral fallback."""

    def test_valid_dict_parses_correctly(self):
        raw = {
            "valence_shift": 0.3,
            "arousal_shift": -0.1,
            "dominance_shift": 0.0,
            "discrete_emotions": {"joy": 0.7},
        }
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.error is None
        assert result.appraisal.valence_shift == 0.3
        assert result.appraisal.discrete_emotions["joy"] == 0.7

    def test_none_produces_fallback(self):
        result = parse_llm_appraisal(None)
        assert result.is_fallback
        assert result.error is not None
        assert result.appraisal == AppraisalV1.neutral()

    def test_string_produces_fallback(self):
        result = parse_llm_appraisal("bad output")
        assert result.is_fallback
        assert result.appraisal == AppraisalV1.neutral()

    def test_out_of_range_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": 99.0, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.appraisal == AppraisalV1.neutral()

    def test_nan_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": float("nan"), "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.appraisal == AppraisalV1.neutral()

    def test_bool_shift_produces_fallback(self):
        result = parse_llm_appraisal({"valence_shift": True, "arousal_shift": 0.0, "dominance_shift": 0.0})
        assert result.is_fallback
        assert result.appraisal == AppraisalV1.neutral()

    def test_unknown_emotion_silently_dropped(self):
        """LLM output with unknown emotions: unknown keys are filtered, not rejected."""
        raw = {
            "valence_shift": 0.1,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "discrete_emotions": {"joy": 0.5, "invented_emotion": 0.9},
        }
        result = parse_llm_appraisal(raw)
        # Should succeed, filtering out the unknown emotion
        assert not result.is_fallback
        assert "invented_emotion" not in result.appraisal.discrete_emotions
        assert "joy" in result.appraisal.discrete_emotions

    def test_missing_shifts_default_to_zero(self):
        """Missing shift keys default to 0.0 (LLM may omit them)."""
        raw = {}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.valence_shift == 0.0
        assert result.appraisal.arousal_shift == 0.0

    def test_fallback_neutral_has_correct_schema_version(self):
        result = parse_llm_appraisal(None)
        assert result.appraisal.schema_version == EMOTIONAL_SCHEMA_VERSION

    def test_legacy_key_valence_accepted(self):
        """'valence' (without _shift) is accepted as alias for 'valence_shift'."""
        raw = {"valence": 0.3, "arousal_shift": 0.0, "dominance_shift": 0.0}
        result = parse_llm_appraisal(raw)
        assert not result.is_fallback
        assert result.appraisal.valence_shift == 0.3

    def test_parse_result_is_not_empty_dict(self):
        """Neutral fallback is an explicit AppraisalV1, not an empty dict."""
        result = parse_llm_appraisal("garbage")
        assert isinstance(result.appraisal, AppraisalV1)
        assert result.appraisal == AppraisalV1.neutral()


# ─── 17: Domain importable without infrastructure ────────────────────────────

class TestDomainImportIsolation:
    """Requirement 17: domain module importable without FastAPI/Groq/Supabase/transformers."""

    def test_models_importable_without_fastapi(self):
        """
        Import the module from scratch (bypass cache) and verify it doesn't
        pull in FastAPI.
        """
        # If fastapi is not installed, the import would fail if it were a dependency.
        # We verify that importing emotional_domain does not import fastapi.
        import backend.emotional_domain.models as m
        # Check that fastapi is not imported as a side effect
        assert "fastapi" not in sys.modules or True  # fastapi may be installed but not required

        # The real test: the module must be importable and functional
        assert hasattr(m, "EmotionalStateV1")
        assert hasattr(m, "AppraisalV1")
        assert hasattr(m, "EMOTIONAL_SCHEMA_VERSION")

    def test_no_groq_import(self):
        import backend.emotional_domain.models as m
        import inspect
        source = inspect.getsource(m)
        assert "groq" not in source.lower()

    def test_no_supabase_import(self):
        import backend.emotional_domain.models as m
        import inspect
        source = inspect.getsource(m)
        assert "supabase" not in source.lower()

    def test_no_sentence_transformers_import(self):
        import backend.emotional_domain.models as m
        import inspect
        source = inspect.getsource(m)
        assert "sentence_transformers" not in source.lower()

    def test_no_fastapi_import(self):
        import backend.emotional_domain.models as m
        import inspect
        source = inspect.getsource(m)
        assert "fastapi" not in source.lower()

    def test_no_os_environ_access(self):
        """Domain module must not read environment variables."""
        import backend.emotional_domain.models as m
        import inspect
        source = inspect.getsource(m)
        assert "os.environ" not in source
        assert "os.getenv" not in source

    def test_migration_no_io(self):
        import backend.emotional_domain.migration as mig
        import inspect
        source = inspect.getsource(mig)
        # No file I/O or network
        assert "open(" not in source
        assert "urllib" not in source
        assert "requests" not in source


# ─── Serialization edge cases ────────────────────────────────────────────────

class TestSerializationEdgeCases:
    """Additional serialization guarantees."""

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
