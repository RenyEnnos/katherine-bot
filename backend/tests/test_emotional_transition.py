"""
Tests for backend/emotional_domain/transition — issue #233.

Coverage map (42 requirements):
─────────────────────────────────────────────────────────────────────────────
 1. Same arguments produce exactly the same result (determinism)
 2. previous_state remains identical
 3. appraisal remains identical
 4. config remains identical
 5. Invalid config fails closed
 6. current_time invalid is rejected
 7. Elapsed zero does not apply decay
 8. At one half-life, deviation from baseline halves
 9. Two half-life steps with neutral appraisal equal one full half-life step
10. Continuous decay over seconds, minutes, hours is monotonic
11. Clock regression uses elapsed zero
12. Output timestamp never decreases
13. Positive shift respects cap of 0.25
14. Negative shift respects cap of 0.25
15. Saturation keeps PAD in [-1.0, 1.0]
16. Neutral appraisal produces no turn shifts beyond decay and regulation
17. Different discrete emotions with same shifts produce same snapshot
18. libido does not increase automatically
19. aggression does not increase automatically
20. connection remains unchanged
21. energy remains unchanged
22. Tension increases when pleasure < -0.3
23. Tension decreases when pleasure > 0.3
24. Tension unchanged in neutral pleasure range
25. Tension stays in [0.0, 1.0]
26. Activation threshold 0.8 is inclusive
27. Recovery threshold 0.3 is inclusive
28. Intermediate range preserves coping mode (hysteresis)
29. Positive dominance at activation triggers DEFENSIVE
30. DEFENSIVE does not increase aggression
31. Zero dominance at activation triggers DISSOCIATED
32. Negative dominance at activation triggers DISSOCIATED
33. DISSOCIATED reduces arousal by configured factor
34. Recovery triggers HEALTHY
35. MANIC follows documented policy
36. RegulationResult reports correct mode, change, and reason
37. No RegulationResult contains prompt text or user content
38. Module imports without FastAPI, Groq, Supabase, embeddings, network
39. No tests use real clock, sleep, randomness, or external services
40. All existing backend tests still pass
41. Frontend audit, tests, lint, and build stay green
42. Full CI passes
"""

from __future__ import annotations

import copy
import math
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from backend.emotional_domain.models import (
    EMOTIONAL_SCHEMA_VERSION,
    AppraisalV1,
    EmotionalDomainError,
    EmotionalStateV1,
)
from backend.emotional_domain.transition import (
    RegulationReason,
    RegulationResult,
    TransitionConfig,
    TransitionResult,
    _clamp,
    _clamp_shift,
    _determine_coping_mode,
    _exponential_decay,
    _validate_current_time,
    transition,
)
from backend.emotional_domain import (
    RegulationResult as PkgRegulationResult,
    RegulationReason as PkgRegulationReason,
    TransitionConfig as PkgTransitionConfig,
    TransitionResult as PkgTransitionResult,
    transition as pkg_transition,
)


# ─── Constants ───────────────────────────────────────────────────────────────

_T0 = 1_700_000_000.0  # Base timestamp
_T1 = _T0 + 3600.0  # One hour later
_HALF_PAD = 3600.0
_HALF_TENSION = 7200.0


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _neutral_state(timestamp: float = _T0) -> EmotionalStateV1:
    return EmotionalStateV1.neutral(timestamp=timestamp)


def _state(
    pleasure: float = 0.0,
    arousal: float = 0.0,
    dominance: float = 0.0,
    libido: float = 0.0,
    aggression: float = 0.0,
    connection: float = 0.5,
    energy: float = 0.8,
    tension: float = 0.0,
    coping_mode: str = "HEALTHY",
    timestamp: float = _T0,
) -> EmotionalStateV1:
    return EmotionalStateV1.create(
        pleasure=pleasure,
        arousal=arousal,
        dominance=dominance,
        libido=libido,
        aggression=aggression,
        connection=connection,
        energy=energy,
        tension=tension,
        coping_mode=coping_mode,
        timestamp=timestamp,
    )


def _appraisal(
    valence_shift: float = 0.0,
    arousal_shift: float = 0.0,
    dominance_shift: float = 0.0,
    discrete_emotions: dict[str, float] | None = None,
) -> AppraisalV1:
    return AppraisalV1.create(
        valence_shift=valence_shift,
        arousal_shift=arousal_shift,
        dominance_shift=dominance_shift,
        discrete_emotions=discrete_emotions or {},
    )


def _default_config() -> TransitionConfig:
    return TransitionConfig.defaults()


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 1: Determinism — same inputs → same outputs
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeterminism:
    """Same arguments produce exactly the same result."""

    def test_deterministic_repeated_call(self):
        state = _state(pleasure=0.3, arousal=0.2, dominance=0.1, tension=0.5)
        ap = _appraisal(valence_shift=0.1, arousal_shift=-0.05, dominance_shift=0.02)
        cfg = _default_config()
        result1 = transition(state, ap, _T1, cfg)
        result2 = transition(state, ap, _T1, cfg)
        assert result1 == result2
        assert result1.state == result2.state
        assert result1.regulation == result2.regulation

    def test_deterministic_three_calls(self):
        state = _neutral_state()
        ap = _appraisal()
        cfg = _default_config()
        results = [transition(state, ap, _T0 + 1, cfg) for _ in range(3)]
        assert all(r == results[0] for r in results)


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 2-4: Input immutability
# ═══════════════════════════════════════════════════════════════════════════════

class TestInputImmutability:
    """previous_state, appraisal, and config remain identical."""

    def test_previous_state_unchanged(self):
        state = _state(pleasure=0.5, arousal=0.3, tension=0.4)
        original = copy.deepcopy(state)
        ap = _appraisal(valence_shift=0.1)
        cfg = _default_config()
        transition(state, ap, _T1, cfg)
        assert state == original

    def test_appraisal_unchanged(self):
        state = _state(pleasure=0.5)
        ap = _appraisal(valence_shift=0.1, arousal_shift=-0.2)
        original_dict = ap.to_dict()
        cfg = _default_config()
        transition(state, ap, _T1, cfg)
        assert ap.to_dict() == original_dict

    def test_config_unchanged(self):
        state = _state(pleasure=0.5)
        ap = _appraisal(valence_shift=0.1)
        cfg = _default_config()
        original = copy.deepcopy(cfg)
        transition(state, ap, _T1, cfg)
        assert cfg == original


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 5: Invalid config fails closed
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidConfig:
    """Invalid TransitionConfig is rejected."""

    @pytest.mark.parametrize("kw", [
        {"pad_half_life": -1.0},
        {"pad_half_life": 0.0},
        {"pad_half_life": None},
        {"pad_half_life": True},
        {"pad_half_life": float("nan")},
        {"pad_half_life": float("inf")},
        {"tension_half_life": -1.0},
        {"tension_half_life": 0.0},
        {"pad_baseline": -2.0},
        {"pad_baseline": 2.0},
        {"tension_baseline": -0.1},
        {"tension_baseline": 2.0},
        {"max_pleasure_shift": -0.1},
        {"max_pleasure_shift": 1.5},
        {"max_arousal_shift": True},
        {"max_dominance_shift": None},
        {"negative_pleasure_threshold": -2.0},
        {"positive_pleasure_threshold": 2.0},
        {"tension_increase": -0.1},
        {"tension_relief": -0.1},
        {"tension_increase": 1.5},
        {"tension_relief": 1.5},
        {"activation_threshold": 1.5},
        {"recovery_threshold": -0.1},
        {"recovery_threshold": 0.7, "activation_threshold": 0.5},
        {"dissociation_arousal_factor": -0.1},
        {"dissociation_arousal_factor": 1.5},
        {"dissociation_arousal_factor": True},
        {"negative_pleasure_threshold": 0.0, "positive_pleasure_threshold": 0.0},  # equal
        {"negative_pleasure_threshold": 0.3, "positive_pleasure_threshold": -0.3},  # inverted
    ])
    def test_invalid_config_rejected(self, kw):
        with pytest.raises(EmotionalDomainError):
            TransitionConfig.create(**kw)

    @pytest.mark.parametrize("kw", [
        {"pad_half_life": 1800.0},
        {"tension_half_life": 3600.0},
        {"tension_baseline": 0.1},
        {"max_pleasure_shift": 0.5},
        {"max_pleasure_shift": 0.0},  # zero disables the axis
        {"max_arousal_shift": 0.0},
        {"max_dominance_shift": 0.0},
        {"dissociation_arousal_factor": 0.3},
    ])
    def test_valid_configs_accepted(self, kw):
        cfg = TransitionConfig.create(**kw)
        for k, v in kw.items():
            assert getattr(cfg, k) == v

    def test_defaults_create(self):
        cfg = TransitionConfig.defaults()
        assert cfg.pad_half_life == 3600.0
        assert cfg.tension_half_life == 7200.0
        assert cfg.pad_baseline == 0.0
        assert cfg.tension_baseline == 0.0

    def test_unknown_field_rejected(self):
        with pytest.raises(EmotionalDomainError):
            TransitionConfig.create(unknown_field=42.0)

    # ── New: cap zero blocks the axis ────────────────────────────────────────
    def test_cap_zero_blocks_pleasure_shift(self):
        """A cap of 0.0 prevents appraisal shifts from affecting pleasure."""
        state = _state(pleasure=0.0)
        ap = _appraisal(valence_shift=0.5)  # would normally be capped to 0.25
        cfg = TransitionConfig.create(max_pleasure_shift=0.0)
        result = transition(state, ap, _T0, cfg)
        # pleasure should remain at 0.0 (no shift applied)
        assert result.state.pleasure == pytest.approx(0.0, abs=1e-10)

    def test_cap_zero_blocks_arousal_shift(self):
        state = _state(arousal=0.0)
        ap = _appraisal(arousal_shift=0.5)
        cfg = TransitionConfig.create(max_arousal_shift=0.0)
        result = transition(state, ap, _T0, cfg)
        assert result.state.arousal == pytest.approx(0.0, abs=1e-10)

    def test_cap_zero_blocks_dominance_shift(self):
        state = _state(dominance=0.0)
        ap = _appraisal(dominance_shift=0.5)
        cfg = TransitionConfig.create(max_dominance_shift=0.0)
        result = transition(state, ap, _T0, cfg)
        assert result.state.dominance == pytest.approx(0.0, abs=1e-10)


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 6: current_time invalid is rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidCurrentTime:
    """current_time validation rejects invalid types and non-positive values."""

    @pytest.mark.parametrize("bad_time", [
        True,
        False,
        None,
        "now",
        [1.0],
        {"time": 1.0},
        float("nan"),
        float("inf"),
        float("-inf"),
        0.0,
        -1.0,
        -0.001,
    ])
    def test_invalid_current_time_rejected(self, bad_time):
        state = _neutral_state()
        ap = _appraisal()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(state, ap, bad_time, cfg)

    def test_valid_current_time_accepted(self):
        state = _neutral_state()
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1.0, cfg)
        assert result.state.timestamp == _T0 + 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 7-10: Decay behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecay:
    """Exponential decay toward baseline."""

    def test_elapsed_zero_no_decay(self):
        """Req 7: No elapsed time → no decay applied."""
        state = _state(pleasure=0.5, arousal=-0.3, dominance=0.2, tension=0.7)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        # With NO appraisal shifts (neutral), pleasure stays at 0.5
        assert result.state.pleasure == pytest.approx(0.5, abs=1e-10)

    def test_one_half_life_decay(self):
        """Req 8: At one half-life the deviation from baseline halves."""
        state = _state(pleasure=0.8, arousal=0.0, dominance=0.0, tension=0.0)
        ap = _appraisal()
        cfg = _default_config()
        # One PAD half-life (3600 seconds)
        result = transition(state, ap, _T0 + _HALF_PAD, cfg)
        # Deviation from baseline (0.0): 0.8 → should be ~0.4
        expected = 0.0 + (0.8 - 0.0) * (0.5 ** (3600.0 / 3600.0))
        assert result.state.pleasure == pytest.approx(expected, abs=1e-10)

    def test_two_half_steps_equal_one_full_step_neutral(self):
        """Req 9: Two steps of half a half-life with neutral appraisal equal one full half-life step."""
        cfg = _default_config()
        state = _state(pleasure=0.6, arousal=0.0, dominance=0.0, tension=0.0)
        ap = _appraisal()

        # One step of one half-life
        result_one = transition(state, ap, _T0 + _HALF_PAD, cfg)
        value_after_full = result_one.state.pleasure

        # Two steps of half a half-life each
        half_half = _HALF_PAD / 2.0
        r1 = transition(state, ap, _T0 + half_half, cfg)
        r2 = transition(r1.state, ap, _T0 + _HALF_PAD, cfg)
        value_after_two = r2.state.pleasure

        assert value_after_full == pytest.approx(value_after_two, abs=1e-10)

    def test_continuous_decay_monotonic(self):
        """Req 10: Decay is continuous and monotonic over various time scales."""
        state = _state(pleasure=0.5, arousal=0.0, dominance=0.0, tension=0.0)
        ap = _appraisal()
        cfg = _default_config()

        times = [1.0, 60.0, 300.0, 1800.0, 3600.0, 7200.0, 14400.0]  # seconds to hours
        values = []
        for t in times:
            result = transition(state, ap, _T0 + t, cfg)
            values.append(result.state.pleasure)

        # Values should be monotonically decreasing toward baseline
        for i in range(1, len(values)):
            assert values[i] < values[i - 1], f"Not monotonic at index {i}: {values[i-1]} -> {values[i]}"

        # Final value should be closer to baseline than initial
        assert values[-1] < 0.5

    def test_decay_preserves_drives(self):
        """Drives (libido, aggression, connection, energy) do not decay."""
        state = _state(
            libido=0.3, aggression=0.2, connection=0.7, energy=0.9,
        )
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 7200, cfg)
        assert result.state.libido == 0.3
        assert result.state.aggression == 0.2
        assert result.state.connection == 0.7
        assert result.state.energy == 0.9


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 11-12: Clock regression
# ═══════════════════════════════════════════════════════════════════════════════

class TestClockRegression:
    """Clock regression uses elapsed zero and preserves previous timestamp."""

    def test_regression_uses_elapsed_zero(self):
        """Req 11: When current_time < previous_state.timestamp, elapsed = 0."""
        state = _state(pleasure=0.7, timestamp=_T0 + 3600)
        ap = _appraisal()
        cfg = _default_config()
        # current_time is BEFORE the previous state's timestamp
        result = transition(state, ap, _T0, cfg)
        # No decay should happen due to elapsed=0
        assert result.state.pleasure == pytest.approx(0.7, abs=1e-10)

    def test_output_timestamp_never_decreases(self):
        """Req 12: Output timestamp never decreases below previous timestamp."""
        state = _state(timestamp=_T0)
        ap = _appraisal()
        cfg = _default_config()

        # Normal forward time
        r1 = transition(state, ap, _T0 + 100, cfg)
        assert r1.state.timestamp == _T0 + 100

        # Regression
        r2 = transition(state, ap, _T0 - 100, cfg)
        assert r2.state.timestamp == _T0  # previous timestamp preserved

    def test_regression_with_appraisal(self):
        """Clock regression: appraisal shifts apply but decay does not."""
        state = _state(pleasure=0.0, timestamp=_T0 + 100)
        ap = _appraisal(valence_shift=0.2)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        # Shift applies but no decay
        assert result.state.pleasure == pytest.approx(0.2, abs=1e-10)
        assert result.state.timestamp == _T0 + 100


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 13-16: Appraisal shifts and caps
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppraisalShifts:
    """Appraisal shifts are capped and PAD is clamped."""

    def test_positive_shift_capped(self):
        """Req 13: Positive shift respects cap of 0.25."""
        state = _state(pleasure=0.0, arousal=0.0, dominance=0.0)
        # Huge positive shift should be capped
        ap = _appraisal(valence_shift=1.0, arousal_shift=1.0, dominance_shift=1.0)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.pleasure == pytest.approx(0.25, abs=1e-10)
        assert result.state.arousal == pytest.approx(0.25, abs=1e-10)
        assert result.state.dominance == pytest.approx(0.25, abs=1e-10)

    def test_negative_shift_capped(self):
        """Req 14: Negative shift respects cap of 0.25."""
        state = _state(pleasure=0.0, arousal=0.0, dominance=0.0)
        ap = _appraisal(valence_shift=-1.0, arousal_shift=-1.0, dominance_shift=-1.0)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.pleasure == pytest.approx(-0.25, abs=1e-10)
        assert result.state.arousal == pytest.approx(-0.25, abs=1e-10)
        assert result.state.dominance == pytest.approx(-0.25, abs=1e-10)

    def test_saturation_keeps_pad_in_range(self):
        """Req 15: Saturation keeps PAD in [-1.0, 1.0]."""
        state = _state(pleasure=0.9, arousal=0.9, dominance=0.9)
        ap = _appraisal(valence_shift=0.2, arousal_shift=0.2, dominance_shift=0.2)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert -1.0 <= result.state.pleasure <= 1.0
        assert -1.0 <= result.state.arousal <= 1.0
        assert -1.0 <= result.state.dominance <= 1.0

    def test_saturation_from_underflow(self):
        state = _state(pleasure=-0.9, arousal=-0.9, dominance=-0.9)
        ap = _appraisal(valence_shift=-0.2, arousal_shift=-0.2, dominance_shift=-0.2)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert -1.0 <= result.state.pleasure <= 1.0
        assert -1.0 <= result.state.arousal <= 1.0
        assert -1.0 <= result.state.dominance <= 1.0

    def test_neutral_appraisal_no_turn_changes(self):
        """Req 16: Neutral appraisal with no elapsed time produces no changes beyond regulation."""
        state = _state(pleasure=0.0, arousal=0.0, dominance=0.0, tension=0.0)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.pleasure == pytest.approx(0.0, abs=1e-10)
        assert result.state.tension == pytest.approx(0.0, abs=1e-10)

    def test_different_discrete_emotions_same_shifts_same_snapshot(self):
        """Req 17: Different discrete_emotions with same shifts produce same snapshot."""
        state = _state(pleasure=0.0)
        ap1 = _appraisal(valence_shift=0.1, discrete_emotions={"joy": 0.8})
        ap2 = _appraisal(valence_shift=0.1, discrete_emotions={"sadness": 0.9})
        cfg = _default_config()
        r1 = transition(state, ap1, _T0, cfg)
        r2 = transition(state, ap2, _T0, cfg)
        # Both should have same pleasure (discrete_emotions don't affect PAD)
        assert r1.state.pleasure == r2.state.pleasure
        assert r1.state.arousal == r2.state.arousal
        assert r1.state.dominance == r2.state.dominance


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 18-21: Drives not automatically changed
# ═══════════════════════════════════════════════════════════════════════════════

class TestDrivesUnchanged:
    """libido, aggression, connection, energy do not change automatically."""

    def test_libido_does_not_increase(self):
        """Req 18."""
        state = _state(libido=0.0, arousal=0.6, pleasure=0.3)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1, cfg)
        assert result.state.libido == 0.0

    def test_aggression_does_not_increase(self):
        """Req 19."""
        state = _state(aggression=0.0, tension=0.9, dominance=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1, cfg)
        assert result.state.aggression == 0.0

    def test_connection_unchanged(self):
        """Req 20."""
        state = _state(connection=0.3)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1, cfg)
        assert result.state.connection == 0.3

    def test_energy_unchanged(self):
        """Req 21."""
        state = _state(energy=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1, cfg)
        assert result.state.energy == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 22-25: Tension update
# ═══════════════════════════════════════════════════════════════════════════════

class TestTensionUpdate:
    """Tension responds to pleasure thresholds."""

    def test_tension_increases_when_pleasure_below_negative(self):
        """Req 22: pleasure < -0.3 → tension delta +0.05."""
        state = _state(pleasure=-0.5, tension=0.0)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.tension == pytest.approx(0.05, abs=1e-10)

    def test_tension_decreases_when_pleasure_above_positive(self):
        """Req 23: pleasure > 0.3 → tension delta -0.05."""
        state = _state(pleasure=0.5, tension=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.tension == pytest.approx(0.45, abs=1e-10)

    def test_tension_unchanged_in_neutral_pleasure(self):
        """Req 24: Tension unchanged in neutral range -0.3 <= pleasure <= 0.3."""
        state = _state(pleasure=0.0, tension=0.4)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.tension == pytest.approx(0.4, abs=1e-10)

    @pytest.mark.parametrize("pleasure,initial_tension,expected_tension", [
        (-0.301, 0.0, 0.05),  # below negative threshold → +0.05
        (-0.3, 0.0, 0.0),     # exactly at negative threshold (NOT below)
        (0.3, 0.0, 0.0),      # exactly at positive threshold (NOT above)
        (0.301, 0.1, 0.05),   # above positive threshold → -0.05 from 0.1
    ])
    def test_tension_threshold_boundaries(self, pleasure, initial_tension, expected_tension):
        """Test exact boundary behaviour of pleasure thresholds."""
        state = _state(pleasure=pleasure, tension=initial_tension)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.tension == pytest.approx(expected_tension, abs=1e-10)

    def test_tension_stays_in_range(self):
        """Req 25: Tension stays in [0.0, 1.0]."""
        state = _state(pleasure=-1.0, tension=0.98)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert 0.0 <= result.state.tension <= 1.0

        state2 = _state(pleasure=1.0, tension=0.02)
        result2 = transition(state2, ap, _T0, cfg)
        assert 0.0 <= result2.state.tension <= 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 26-28: Coping thresholds and hysteresis
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopingThresholds:
    """Activation and recovery thresholds."""

    def test_activation_inclusive(self):
        """Req 26: Activation threshold 0.8 is inclusive."""
        state = _state(tension=0.8, dominance=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.current_mode in ("DEFENSIVE", "DISSOCIATED")

    def test_recovery_inclusive(self):
        """Req 27: Recovery threshold 0.3 is inclusive."""
        state = _state(tension=0.3, coping_mode="DEFENSIVE")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.current_mode == "HEALTHY"

    def test_intermediate_preserves_coping(self):
        """Req 28: Intermediate range (0.3 < tension < 0.8) preserves coping mode."""
        for mode in ("HEALTHY", "DEFENSIVE", "DISSOCIATED", "MANIC"):
            state = _state(tension=0.5, coping_mode=mode)
            ap = _appraisal()
            cfg = _default_config()
            result = transition(state, ap, _T0, cfg)
            assert result.state.coping_mode == mode


# ═══════════════════════════════════════════════════════════════════════════════
# Requirements 29-33: Coping mode activation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopingActivation:
    """DEFENSIVE and DISSOCIATED activation."""

    def test_positive_dominance_activates_defensive(self):
        """Req 29: Positive dominance at activation triggers DEFENSIVE."""
        state = _state(tension=0.9, dominance=0.1)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DEFENSIVE"
        assert result.regulation.current_mode == "DEFENSIVE"

    def test_defensive_does_not_increase_aggression(self):
        """Req 30: DEFENSIVE does not increase aggression."""
        state = _state(tension=0.9, dominance=0.1, aggression=0.0)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DEFENSIVE"
        assert result.state.aggression == 0.0  # unchanged

    def test_zero_dominance_activates_dissociated(self):
        """Req 31: Zero dominance at activation triggers DISSOCIATED."""
        state = _state(tension=0.9, dominance=0.0)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DISSOCIATED"

    def test_negative_dominance_activates_dissociated(self):
        """Req 32: Negative dominance at activation triggers DISSOCIATED."""
        state = _state(tension=0.9, dominance=-0.3)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DISSOCIATED"

    def test_dissociated_reduces_arousal(self):
        """Req 33: DISSOCIATED reduces arousal by configured factor (0.5)."""
        state = _state(tension=0.9, dominance=-0.3, arousal=0.8)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DISSOCIATED"
        expected_arousal = 0.8 * cfg.dissociation_arousal_factor
        assert result.state.arousal == pytest.approx(expected_arousal, abs=1e-10)


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 34: Recovery triggers HEALTHY
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecovery:
    """Recovery activates HEALTHY."""

    def test_recovery_from_defensive(self):
        state = _state(tension=0.2, coping_mode="DEFENSIVE")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "HEALTHY"

    def test_recovery_from_dissociated(self):
        state = _state(tension=0.0, coping_mode="DISSOCIATED")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "HEALTHY"

    def test_recovery_from_manic(self):
        state = _state(tension=0.0, coping_mode="MANIC")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "HEALTHY"


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 35: MANIC follows documented policy
# ═══════════════════════════════════════════════════════════════════════════════

class TestManicPolicy:
    """MANIC stays MANIC in intermediate range, changes at boundaries."""

    def test_manic_stays_manic_in_intermediate(self):
        state = _state(tension=0.5, coping_mode="MANIC")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "MANIC"

    def test_manic_recovers_to_healthy(self):
        state = _state(tension=0.2, coping_mode="MANIC")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "HEALTHY"

    def test_manic_activates_defensive_with_positive_dominance(self):
        state = _state(tension=0.9, dominance=0.5, coping_mode="MANIC")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DEFENSIVE"

    def test_manic_activates_dissociated_with_nonpositive_dominance(self):
        state = _state(tension=0.9, dominance=-0.2, coping_mode="MANIC")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DISSOCIATED"


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 36: RegulationResult structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegulationResultValidation:
    """Validation of RegulationResult construction."""

    def test_invalid_previous_mode_rejected(self):
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="INVALID",
                current_mode="HEALTHY",
                changed=True,
                reason=RegulationReason.RECOVERED,
            )

    def test_invalid_current_mode_rejected(self):
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="INVALID",
                changed=True,
                reason=RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE,
            )

    def test_changed_not_bool_rejected(self):
        for bad in (0, 1, "True", None, [True], {"c": True}):
            with pytest.raises(EmotionalDomainError):
                RegulationResult(
                    previous_mode="HEALTHY",
                    current_mode="DEFENSIVE",
                    changed=bad,  # type: ignore[arg-type]
                    reason=RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE,
                )

    def test_changed_inconsistent_with_modes_rejected(self):
        # changed=True but modes are equal
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="HEALTHY",
                changed=True,
                reason=RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE,
            )
        # changed=False but modes differ
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="DEFENSIVE",
                changed=False,
                reason=RegulationReason.NONE,
            )

    def test_reason_as_string_rejected(self):
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="HEALTHY",
                changed=False,
                reason="none",  # type: ignore[arg-type]
            )

    def test_reason_none_with_change_rejected(self):
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="DEFENSIVE",
                changed=True,
                reason=RegulationReason.NONE,
            )

    def test_reason_incompatible_with_current_mode_rejected(self):
        # RECOVERED requires HEALTHY
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="DEFENSIVE",
                changed=True,
                reason=RegulationReason.RECOVERED,
            )
        # HIGH_TENSION_POSITIVE_DOMINANCE requires DEFENSIVE
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="DISSOCIATED",
                changed=True,
                reason=RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE,
            )
        # HIGH_TENSION_NONPOSITIVE_DOMINANCE requires DISSOCIATED
        with pytest.raises(EmotionalDomainError):
            RegulationResult(
                previous_mode="HEALTHY",
                current_mode="DEFENSIVE",
                changed=True,
                reason=RegulationReason.HIGH_TENSION_NONPOSITIVE_DOMINANCE,
            )


class TestRegulationResult:
    """RegulationResult reports correct previous_mode, current_mode, changed, reason."""

    def test_no_change_when_no_regulation(self):
        state = _state(tension=0.5, coping_mode="HEALTHY")
        ap = _appraisal(valence_shift=0.1)
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.changed is False
        assert result.regulation.reason == RegulationReason.NONE
        assert result.regulation.previous_mode == "HEALTHY"
        assert result.regulation.current_mode == "HEALTHY"

    def test_defensive_reason(self):
        state = _state(tension=0.9, dominance=0.1, coping_mode="HEALTHY")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.changed is True
        assert result.regulation.reason == RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE
        assert result.regulation.previous_mode == "HEALTHY"
        assert result.regulation.current_mode == "DEFENSIVE"

    def test_dissociated_reason(self):
        state = _state(tension=0.9, dominance=-0.1, coping_mode="HEALTHY")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.changed is True
        assert result.regulation.reason == RegulationReason.HIGH_TENSION_NONPOSITIVE_DOMINANCE
        assert result.regulation.current_mode == "DISSOCIATED"

    def test_recovered_reason(self):
        state = _state(tension=0.2, coping_mode="DEFENSIVE")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.regulation.changed is True
        assert result.regulation.reason == RegulationReason.RECOVERED
        assert result.regulation.current_mode == "HEALTHY"


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 37: No prompt/user content in results
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoPromptInResults:
    """No RegulationResult contains prompt text or user content."""

    def test_regulation_result_no_prompt_text(self):
        state = _state(tension=0.9, dominance=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        reg = result.regulation
        assert isinstance(reg.reason, RegulationReason)
        assert reg.reason.value not in ("", "prompt", "instruction")
        assert "prompt" not in reg.reason.value
        assert "user" not in reg.reason.value

    def test_regulation_result_no_instruction_field(self):
        state = _state(tension=0.9, dominance=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        d = result.regulation.to_dict()
        assert "instruction" not in d
        assert "prompt" not in d
        assert "acting_instruction" not in d

    def test_transition_result_no_prompt(self):
        state = _state(tension=0.9, dominance=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        d = result.to_dict()
        assert "prompt" not in d
        assert "instruction" not in str(d)


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 38: Module imports without infrastructure
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsolatedImport:
    """Module imports without FastAPI, Groq, Supabase, embeddings, network."""

    def _run_script(self, script: str) -> subprocess.CompletedProcess:
        import os
        env = {
            **os.environ,
            "PYTHONPATH": str(
                __import__("pathlib").Path(__file__).parent.parent.parent
            ),
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

    def test_transition_import_no_fastapi(self):
        proc = self._run_script("""
            import sys
            from backend.emotional_domain.transition import transition, TransitionConfig
            for mod in sys.modules:
                assert 'fastapi' not in mod, f'fastapi loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_transition_import_no_groq(self):
        proc = self._run_script("""
            import sys
            from backend.emotional_domain.transition import TransitionResult
            for mod in sys.modules:
                assert 'groq' not in mod, f'groq loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_transition_import_no_supabase(self):
        proc = self._run_script("""
            import sys
            from backend.emotional_domain import transition
            for mod in sys.modules:
                assert 'supabase' not in mod, f'supabase loaded: {mod}'
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout

    def test_transition_works_in_isolation(self):
        proc = self._run_script("""
            from backend.emotional_domain import (
                EmotionalStateV1, AppraisalV1,
                TransitionConfig, transition, TransitionResult, RegulationResult,
            )
            state = EmotionalStateV1.neutral(timestamp=1_700_000_000.0)
            ap = AppraisalV1.neutral()
            cfg = TransitionConfig.defaults()
            result = transition(state, ap, 1_700_001_000.0, cfg)
            assert isinstance(result, TransitionResult)
            assert isinstance(result.regulation, RegulationResult)
            print('OK')
        """)
        assert proc.returncode == 0, proc.stderr
        assert "OK" in proc.stdout


# ═══════════════════════════════════════════════════════════════════════════════
# Requirement 39: No real clock, sleep, randomness, or external services
# ═══════════════════════════════════════════════════════════════════════════════

# (This requirement is satisfied by the design of all tests above — none use
# time.time(), time.sleep(), random, or external services. This annotation
# serves as documentation.)


# ═══════════════════════════════════════════════════════════════════════════════
# Additional structural tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransitionResultValidation:
    """Validation of TransitionResult construction."""

    def test_state_none_rejected(self):
        with pytest.raises(EmotionalDomainError):
            TransitionResult(
                state=None,  # type: ignore[arg-type]
                regulation=RegulationResult(
                    previous_mode="HEALTHY",
                    current_mode="HEALTHY",
                    changed=False,
                    reason=RegulationReason.NONE,
                ),
            )

    def test_state_wrong_type_rejected(self):
        with pytest.raises(EmotionalDomainError):
            TransitionResult(
                state={"pleasure": 0.5},  # type: ignore[arg-type]
                regulation=RegulationResult(
                    previous_mode="HEALTHY",
                    current_mode="HEALTHY",
                    changed=False,
                    reason=RegulationReason.NONE,
                ),
            )

    def test_regulation_none_rejected(self):
        with pytest.raises(EmotionalDomainError):
            TransitionResult(
                state=_neutral_state(),
                regulation=None,  # type: ignore[arg-type]
            )

    def test_regulation_wrong_type_rejected(self):
        with pytest.raises(EmotionalDomainError):
            TransitionResult(
                state=_neutral_state(),
                regulation={"previous_mode": "HEALTHY"},  # type: ignore[arg-type]
            )


class TestTransitionResultStructure:
    """TransitionResult and RegulationResult serialisation."""

    def test_transition_result_to_dict(self):
        state = _state(tension=0.5)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0 + 1, cfg)
        d = result.to_dict()
        assert "state" in d
        assert "regulation" in d
        assert "pleasure" in d["state"]
        assert "coping_mode" in d["state"]

    def test_regulation_result_to_dict(self):
        reg = RegulationResult(
            previous_mode="HEALTHY",
            current_mode="DEFENSIVE",
            changed=True,
            reason=RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE,
        )
        d = reg.to_dict()
        assert d["previous_mode"] == "HEALTHY"
        assert d["current_mode"] == "DEFENSIVE"
        assert d["changed"] is True
        assert d["reason"] == "high_tension_positive_dominance"

    def test_regulation_reason_values(self):
        assert RegulationReason.NONE.value == "none"
        assert RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE.value == "high_tension_positive_dominance"
        assert RegulationReason.HIGH_TENSION_NONPOSITIVE_DOMINANCE.value == "high_tension_nonpositive_dominance"
        assert RegulationReason.RECOVERED.value == "recovered"


class TestMathematicalHelpers:
    """Unit tests for internal maths helpers."""

    def test_exponential_decay_no_elapsed(self):
        result = _exponential_decay(0.8, 0.0, 0.0, 3600.0)
        assert result == pytest.approx(0.8, abs=1e-10)

    def test_exponential_decay_half_life(self):
        result = _exponential_decay(0.8, 0.0, 3600.0, 3600.0)
        assert result == pytest.approx(0.4, abs=1e-10)

    def test_exponential_decay_to_baseline(self):
        result = _exponential_decay(0.8, 0.5, 3600.0, 3600.0)
        expected = 0.5 + (0.8 - 0.5) * 0.5
        assert result == pytest.approx(expected, abs=1e-10)

    def test_clamp_within_range(self):
        assert _clamp(0.5, -1.0, 1.0) == 0.5

    def test_clamp_below_range(self):
        assert _clamp(-2.0, -1.0, 1.0) == -1.0

    def test_clamp_above_range(self):
        assert _clamp(2.0, -1.0, 1.0) == 1.0

    def test_clamp_shift_within_cap(self):
        assert _clamp_shift(0.1, 0.25) == 0.1

    def test_clamp_shift_above_cap(self):
        assert _clamp_shift(0.5, 0.25) == 0.25

    def test_clamp_shift_below_cap(self):
        assert _clamp_shift(-0.5, 0.25) == -0.25


class TestValidateCurrentTime:
    """Unit tests for current_time validation."""

    @pytest.mark.parametrize("good_time", [1.0, 0.001, 1_700_000_000.0, 1e100])
    def test_valid_times(self, good_time):
        result = _validate_current_time(good_time)
        assert result == pytest.approx(float(good_time))

    @pytest.mark.parametrize("bad_time", [
        True,
        False,
        None,
        "string",
        [1.0],
        {"t": 1.0},
        float("nan"),
        float("inf"),
        float("-inf"),
        0.0,
        -1.0,
    ])
    def test_invalid_times(self, bad_time):
        with pytest.raises(EmotionalDomainError):
            _validate_current_time(bad_time)


class TestTransitionArgumentValidation:
    """Validation of transition() argument types."""

    def test_state_none_rejected(self):
        ap = _appraisal()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(None, ap, _T0, cfg)  # type: ignore[arg-type]

    def test_state_dict_rejected(self):
        ap = _appraisal()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition({"pleasure": 0.5}, ap, _T0, cfg)  # type: ignore[arg-type]

    def test_state_string_rejected(self):
        ap = _appraisal()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition("not_a_state", ap, _T0, cfg)  # type: ignore[arg-type]

    def test_appraisal_none_rejected(self):
        state = _neutral_state()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(state, None, _T0, cfg)  # type: ignore[arg-type]

    def test_appraisal_dict_rejected(self):
        state = _neutral_state()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(state, {"valence_shift": 0.1}, _T0, cfg)  # type: ignore[arg-type]

    def test_appraisal_string_rejected(self):
        state = _neutral_state()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(state, "not_an_appraisal", _T0, cfg)  # type: ignore[arg-type]

    def test_config_none_rejected(self):
        state = _neutral_state()
        ap = _appraisal()
        with pytest.raises(EmotionalDomainError):
            transition(state, ap, _T0, None)  # type: ignore[arg-type]

    def test_config_dict_rejected(self):
        state = _neutral_state()
        ap = _appraisal()
        with pytest.raises(EmotionalDomainError):
            transition(state, ap, _T0, {"pad_half_life": 3600.0})  # type: ignore[arg-type]

    def test_config_string_rejected(self):
        state = _neutral_state()
        ap = _appraisal()
        with pytest.raises(EmotionalDomainError):
            transition(state, ap, _T0, "bad_config")  # type: ignore[arg-type]

    def test_state_appraisal_swapped_rejected(self):
        """Swapping state and appraisal should be rejected."""
        state = _neutral_state()
        ap = _appraisal()
        cfg = _default_config()
        with pytest.raises(EmotionalDomainError):
            transition(ap, state, _T0, cfg)  # type: ignore[arg-type]


class TestDetermineCopingMode:
    """Unit tests for coping mode determination."""

    def test_activation_defensive(self):
        state = _state(tension=0.8, dominance=0.1)
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DEFENSIVE"

    def test_activation_dissociated_zero_dominance(self):
        cfg = _default_config()
        mode = _determine_coping_mode(0.8, 0.0, "HEALTHY", cfg)
        assert mode == "DISSOCIATED"

    def test_activation_dissociated_negative_dominance(self):
        cfg = _default_config()
        mode = _determine_coping_mode(0.8, -0.1, "HEALTHY", cfg)
        assert mode == "DISSOCIATED"

    def test_recovery_healthy(self):
        cfg = _default_config()
        mode = _determine_coping_mode(0.3, 0.5, "DEFENSIVE", cfg)
        assert mode == "HEALTHY"

    def test_intermediate_preserves_mode(self):
        cfg = _default_config()
        mode = _determine_coping_mode(0.5, 0.5, "DEFENSIVE", cfg)
        assert mode == "DEFENSIVE"

    def test_debug_tension_exactly_point_three(self):
        state = _state(tension=0.3, coping_mode="DEFENSIVE")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        # tension=0.3 is recovery threshold (inclusive) → HEALTHY
        assert result.state.coping_mode == "HEALTHY"

    def test_debug_tension_exactly_point_eight(self):
        state = _state(tension=0.8, dominance=0.1, coping_mode="HEALTHY")
        ap = _appraisal()
        cfg = _default_config()
        result = transition(state, ap, _T0, cfg)
        assert result.state.coping_mode == "DEFENSIVE"


# ═══════════════════════════════════════════════════════════════════════════════
# Package exports
# ═══════════════════════════════════════════════════════════════════════════════

class TestPackageExports:
    """Transition types are exported from the package."""

    def test_transition_config_exported(self):
        assert PkgTransitionConfig is TransitionConfig

    def test_regulation_result_exported(self):
        assert PkgRegulationResult is RegulationResult

    def test_regulation_reason_exported(self):
        assert PkgRegulationReason is RegulationReason

    def test_transition_result_exported(self):
        assert PkgTransitionResult is TransitionResult

    def test_package_transition_works(self):
        state = _neutral_state()
        ap = _appraisal()
        cfg = _default_config()
        r = pkg_transition(state, ap, _T0 + 1, cfg)
        assert isinstance(r, TransitionResult)

    def test_appraisal_same_shifts_different_emotions_produce_same_pad(self):
        """Same shift values regardless of discrete emotions produce same PAD."""
        state = _state(pleasure=0.3, arousal=-0.1, dominance=0.2)
        ap_joy = _appraisal(
            valence_shift=0.1, arousal_shift=0.05, dominance_shift=-0.02,
            discrete_emotions={"joy": 0.7},
        )
        ap_anger = _appraisal(
            valence_shift=0.1, arousal_shift=0.05, dominance_shift=-0.02,
            discrete_emotions={"anger": 0.6},
        )
        cfg = _default_config()
        r1 = transition(state, ap_joy, _T0, cfg)
        r2 = transition(state, ap_anger, _T0, cfg)
        assert r1.state.pleasure == r2.state.pleasure
        assert r1.state.arousal == r2.state.arousal
        assert r1.state.dominance == r2.state.dominance
