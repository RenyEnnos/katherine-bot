"""
Pure, deterministic emotional transition v1.

Applies temporal decay, appraisal shifts, tension update, and coping
regulation in a fixed order to produce a new ``EmotionalStateV1``
and a ``RegulationResult``.

Design principles
=================
- **Pure**: no I/O, no randomness, no global state, no ``time.time()``.
- **Deterministic**: same inputs always produce the same outputs.
- **Immutable**: never mutates inputs.
- **Infrastructure-free**: no FastAPI, Groq, Supabase, embeddings, network.
- **No production integration**: this module does **not** integrate with
  ``ConversationEngine``, ``AffectiveEngine``, or any production flow.
  That integration belongs exclusively to issue #234.

Order of operations
===================
1. Validate ``current_time`` (reject invalid types and non-positive values).
2. Compute elapsed seconds (clock regression → elapsed = 0.0).
3. Apply exponential decay to PAD and tension toward their baselines.
4. Apply capped appraisal shifts to PAD.
5. Clamp PAD to [-1.0, +1.0].
6. Update tension based on pleasure level.
7. Clamp tension to [0.0, 1.0].
8. Determine coping mode (with hysteresis for the intermediate range
   and with MANIC handling as documented).
9. Apply regulation effects (DEFENSIVE → no-op beyond mode;
   DISSOCIATED → scale arousal by factor).
10. Build the new ``EmotionalStateV1`` via its validated factory.
11. Return ``TransitionResult``.

Boundary
========
This function belongs to the **transition** layer. It receives exactly
one canonically validated ``AppraisalV1``. It does **not** execute:

- ``OCCAppraisal`` heuristics
- keyword analysis
- implicit combination of heuristic + classifier
- alias or LLM payload parsing
- any textual analysis

Two appraisals with identical scalar shifts but different
``discrete_emotions`` produce the same emotional snapshot.

Parameters and defaults
=======================
All default values are engineering choices with **no claim of clinical
validity**. See also ``TransitionConfig``.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Dict, Final

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    VALID_COPING_MODES,
    AppraisalV1,
    EmotionalDomainError,
    EmotionalStateV1,
    _require_finite_float,
    _require_finite_float_in_range,
)

# ─── Constants ───────────────────────────────────────────────────────────────

# Cap on a single appraisal's shift contribution per axis (engineering default).
_DEFAULT_MAX_SHIFT: Final[float] = 0.25

# PAD decay defaults.
_DEFAULT_PAD_HALF_LIFE: Final[float] = 3600.0  # seconds
_DEFAULT_TENSION_HALF_LIFE: Final[float] = 7200.0  # seconds
_DEFAULT_PAD_BASELINE: Final[float] = 0.0
_DEFAULT_TENSION_BASELINE: Final[float] = 0.0

# Tension update defaults.
_DEFAULT_NEGATIVE_PLEASURE_THRESHOLD: Final[float] = -0.3
_DEFAULT_POSITIVE_PLEASURE_THRESHOLD: Final[float] = 0.3
_DEFAULT_TENSION_INCREASE: Final[float] = 0.05
_DEFAULT_TENSION_RELIEF: Final[float] = 0.05

# Coping thresholds.
_DEFAULT_ACTIVATION_THRESHOLD: Final[float] = 0.8
_DEFAULT_RECOVERY_THRESHOLD: Final[float] = 0.3

# Dissociation factor.
_DEFAULT_DISSOCIATION_AROUSAL_FACTOR: Final[float] = 0.5


# ─── Regulation reason ────────────────────────────────────────────────────────

class RegulationReason(str, enum.Enum):
    """Stable, sanitised reasons for coping mode changes.

    These values contain no user content, no LLM output, and no prompt text.
    """
    NONE = "none"
    HIGH_TENSION_POSITIVE_DOMINANCE = "high_tension_positive_dominance"
    HIGH_TENSION_NONPOSITIVE_DOMINANCE = "high_tension_nonpositive_dominance"
    RECOVERED = "recovered"


# ─── Validation helpers ──────────────────────────────────────────────────────

# Fields accepted by TransitionConfig (used for unknown-key rejection).
_CONFIG_FIELDS = frozenset({
    "pad_half_life",
    "tension_half_life",
    "pad_baseline",
    "tension_baseline",
    "max_pleasure_shift",
    "max_arousal_shift",
    "max_dominance_shift",
    "negative_pleasure_threshold",
    "positive_pleasure_threshold",
    "tension_increase",
    "tension_relief",
    "activation_threshold",
    "recovery_threshold",
    "dissociation_arousal_factor",
})


def _require_positive_finite(value: object, name: str) -> float:
    """Reject bool, None, str, list, dict, NaN, Inf, and non-positive values."""
    f = _require_finite_float(value, name)
    if f <= 0:
        raise EmotionalDomainError(
            f"Field '{name}' must be a positive finite float."
        )
    return f


def _require_nonnegative_finite(value: object, name: str) -> float:
    """Reject bool, None, str, list, dict, NaN, Inf, and negative values."""
    f = _require_finite_float(value, name)
    if f < 0:
        raise EmotionalDomainError(
            f"Field '{name}' must be a non-negative finite float."
        )
    return f


# ─── TransitionConfig ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransitionConfig:
    """Immutable configuration for the emotional transition function.

    All numeric fields are validated on construction. Default values are
    engineering choices with **no claim of clinical validity**.

    Parameters
    ==========
    pad_half_life:
        Half-life in seconds for exponential decay of PAD toward baseline.
        Must be positive and finite. Default: 3600.0 (1 hour).
    tension_half_life:
        Half-life in seconds for exponential decay of tension toward baseline.
        Must be positive and finite. Default: 7200.0 (2 hours).
    pad_baseline:
        Baseline toward which PAD decays. Must be in [-1.0, 1.0]. Default: 0.0.
    tension_baseline:
        Baseline toward which tension decays. Must be in [0.0, 1.0]. Default: 0.0.
    max_pleasure_shift:
        Maximum absolute contribution of a single appraisal's valence_shift.
        Must be positive and <= 1.0. Default: 0.25.
    max_arousal_shift:
        Maximum absolute contribution of a single appraisal's arousal_shift.
        Must be positive and <= 1.0. Default: 0.25.
    max_dominance_shift:
        Maximum absolute contribution of a single appraisal's dominance_shift.
        Must be positive and <= 1.0. Default: 0.25.
    negative_pleasure_threshold:
        Pleasure below this value increases tension. Must be in [-1.0, 1.0].
        Default: -0.3.
    positive_pleasure_threshold:
        Pleasure above this value decreases tension. Must be in [-1.0, 1.0].
        Default: 0.3.
    tension_increase:
        Delta added to tension when pleasure < negative_pleasure_threshold.
        Must be non-negative and finite. Default: 0.05.
    tension_relief:
        Delta subtracted from tension when pleasure > positive_pleasure_threshold.
        Must be non-negative and finite. Default: 0.05.
    activation_threshold:
        Tension at or above this value activates DEFENSIVE or DISSOCIATED coping.
        Must be in [0.0, 1.0]. Default: 0.8.
    recovery_threshold:
        Tension at or below this value activates HEALTHY coping.
        Must be in [0.0, 1.0]. Default: 0.3.
        Invariant: recovery_threshold < activation_threshold.
    dissociation_arousal_factor:
        Factor by which arousal is multiplied in DISSOCIATED mode.
        Must be in [0.0, 1.0]. Default: 0.5.
    """

    # Decay
    pad_half_life: float = _DEFAULT_PAD_HALF_LIFE
    tension_half_life: float = _DEFAULT_TENSION_HALF_LIFE
    pad_baseline: float = _DEFAULT_PAD_BASELINE
    tension_baseline: float = _DEFAULT_TENSION_BASELINE

    # Appraisal caps
    max_pleasure_shift: float = _DEFAULT_MAX_SHIFT
    max_arousal_shift: float = _DEFAULT_MAX_SHIFT
    max_dominance_shift: float = _DEFAULT_MAX_SHIFT

    # Tension pleasure thresholds
    negative_pleasure_threshold: float = _DEFAULT_NEGATIVE_PLEASURE_THRESHOLD
    positive_pleasure_threshold: float = _DEFAULT_POSITIVE_PLEASURE_THRESHOLD
    tension_increase: float = _DEFAULT_TENSION_INCREASE
    tension_relief: float = _DEFAULT_TENSION_RELIEF

    # Coping thresholds
    activation_threshold: float = _DEFAULT_ACTIVATION_THRESHOLD
    recovery_threshold: float = _DEFAULT_RECOVERY_THRESHOLD

    # Dissociation regulation
    dissociation_arousal_factor: float = _DEFAULT_DISSOCIATION_AROUSAL_FACTOR

    def __post_init__(self) -> None:
        """Validate all fields on every construction path."""

        # Decay parameters
        _validate_positive_finite(self.pad_half_life, "pad_half_life")
        _validate_positive_finite(self.tension_half_life, "tension_half_life")
        _validate_range(self.pad_baseline, "pad_baseline", -1.0, 1.0)
        _validate_range(self.tension_baseline, "tension_baseline", 0.0, 1.0)

        # Appraisal caps — positive, <= 1.0
        _validate_shift_cap(self.max_pleasure_shift, "max_pleasure_shift")
        _validate_shift_cap(self.max_arousal_shift, "max_arousal_shift")
        _validate_shift_cap(self.max_dominance_shift, "max_dominance_shift")

        # Pleasure thresholds
        _validate_range(self.negative_pleasure_threshold, "negative_pleasure_threshold", -1.0, 1.0)
        _validate_range(self.positive_pleasure_threshold, "positive_pleasure_threshold", -1.0, 1.0)

        # Tension delta magnitudes — must be non-negative (they are magnitudes)
        _validate_nonnegative(
            self.tension_increase, "tension_increase"
        )
        _validate_nonnegative(self.tension_relief, "tension_relief")

        # Coping thresholds — must be in [0.0, 1.0]
        _validate_range(self.activation_threshold, "activation_threshold", 0.0, 1.0)
        _validate_range(self.recovery_threshold, "recovery_threshold", 0.0, 1.0)

        # recovery_threshold must be strictly less than activation_threshold
        if self.recovery_threshold >= self.activation_threshold:
            raise EmotionalDomainError(
                "TransitionConfig: recovery_threshold must be strictly less than "
                "activation_threshold."
            )

        # Dissociation factor — must be in [0.0, 1.0]
        _validate_range(
            self.dissociation_arousal_factor,
            "dissociation_arousal_factor",
            0.0,
            1.0,
        )

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def create(cls, **kwargs: object) -> "TransitionConfig":
        """Validated factory. Raises ``EmotionalDomainError`` on violation."""
        # Reject unexpected keys
        unexpected = set(kwargs.keys()) - _CONFIG_FIELDS
        if unexpected:
            raise EmotionalDomainError(
                "TransitionConfig: unexpected fields."
            )
        return cls(**{k: v for k, v in kwargs.items()})  # type: ignore[arg-type]

    @classmethod
    def defaults(cls) -> "TransitionConfig":
        """Return a default-configured instance."""
        return cls()


def _validate_positive_finite(raw: object, name: str) -> float:
    _validate_not_bool(raw, name)
    f = _require_positive_finite(raw, name)
    return f


def _validate_range(raw: object, name: str, lo: float, hi: float) -> float:
    _validate_not_bool(raw, name)
    return _require_finite_float_in_range(raw, name, lo, hi)


def _validate_shift_cap(raw: object, name: str) -> None:
    _validate_not_bool(raw, name)
    f = _require_finite_float(raw, name)
    if f <= 0 or f > 1.0:
        raise EmotionalDomainError(
            f"Field '{name}' must be in (0.0, 1.0]."
        )


def _validate_nonnegative(raw: object, name: str) -> float:
    _validate_not_bool(raw, name)
    return _require_nonnegative_finite(raw, name)


def _validate_not_bool(raw: object, name: str) -> None:
    if isinstance(raw, bool):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got bool."
        )


# ─── RegulationResult ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RegulationResult:
    """Structured result of coping regulation.

    Attributes
    ==========
    previous_mode:
        The coping mode before regulation.
    current_mode:
        The coping mode after regulation.
    changed:
        ``True`` when ``previous_mode != current_mode``.
    reason:
        A ``RegulationReason`` enum value indicating why the mode changed.
        Never contains user content, LLM output, prompt text, or instructions.
    """

    previous_mode: str
    current_mode: str
    changed: bool
    reason: RegulationReason

    def to_dict(self) -> Dict[str, object]:
        return {
            "previous_mode": self.previous_mode,
            "current_mode": self.current_mode,
            "changed": self.changed,
            "reason": self.reason.value,
        }


# ─── TransitionResult ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TransitionResult:
    """Result of a complete emotional transition.

    Attributes
    ==========
    state:
        The new ``EmotionalStateV1`` after decay, appraisal, tension update,
        coping determination, and regulation effects.
    regulation:
        The ``RegulationResult`` describing the coping mode transition.
    """

    state: EmotionalStateV1
    regulation: RegulationResult

    def to_dict(self) -> Dict[str, object]:
        return {
            "state": self.state.to_dict(),
            "regulation": self.regulation.to_dict(),
        }


# ─── Core maths ──────────────────────────────────────────────────────────────

def _exponential_decay(
    value: float,
    baseline: float,
    elapsed: float,
    half_life: float,
) -> float:
    """Apply exponential decay toward baseline.

    ``factor = 0.5 ** (elapsed / half_life)``
    ``result = baseline + (value - baseline) * factor``

    When *elapsed* is zero, the result equals *value*.
    As *elapsed* tends to infinity, the result tends to *baseline*.
    """
    if half_life <= 0:
        return value
    factor = 0.5 ** (elapsed / half_life)
    return baseline + (value - baseline) * factor


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _clamp_shift(raw_shift: float, cap: float) -> float:
    """Clamp an appraisal shift to *[-cap, cap]*.

    No single appraisal can move an axis more than *cap*, regardless of
    the original shift magnitude.
    """
    return _clamp(raw_shift, -cap, cap)


# ─── Current-time validation ─────────────────────────────────────────────────

def _validate_current_time(raw_time: object) -> float:
    """Validate and return *raw_time* as a positive finite float.

    Rejects: bool, None, str, list, dict, NaN, Inf, <= 0.

    Raises ``EmotionalDomainError`` on any violation.
    """
    if isinstance(raw_time, bool):
        raise EmotionalDomainError(
            "current_time must be a finite positive float, got bool."
        )
    if raw_time is None:
        raise EmotionalDomainError(
            "current_time must be a finite positive float, got None."
        )
    if not isinstance(raw_time, (int, float)):
        raise EmotionalDomainError(
            f"current_time must be a finite positive float, "
            f"got {type(raw_time).__name__}."
        )
    try:
        f = float(raw_time)
    except (OverflowError, ValueError, TypeError):
        raise EmotionalDomainError(
            "current_time must be a finite positive float, "
            "got non-convertible value."
        )
    if not math.isfinite(f):
        raise EmotionalDomainError(
            "current_time must be finite."
        )
    if f <= 0:
        raise EmotionalDomainError(
            "current_time must be positive."
        )
    return f


# ─── Coping mode determination ───────────────────────────────────────────────

def _determine_coping_mode(
    tension: float,
    dominance: float,
    previous_mode: str,
    config: TransitionConfig,
) -> str:
    """Determine the new coping mode based on tension and dominance.

    Uses a hysteresis policy: the intermediate range preserves the
    previous mode. ``MANIC`` stays ``MANIC`` in the intermediate range,
    transitions to ``HEALTHY`` on recovery, and to ``DEFENSIVE`` or
    ``DISSOCIATED`` on activation.
    """
    # Activation zone
    if tension >= config.activation_threshold:
        if dominance > 0.0:
            return "DEFENSIVE"
        else:
            return "DISSOCIATED"

    # Recovery zone
    if tension <= config.recovery_threshold:
        return "HEALTHY"

    # Intermediate zone — preserve previous mode
    return previous_mode


# ─── Public transition API ───────────────────────────────────────────────────

def transition(
    previous_state: EmotionalStateV1,
    appraisal: AppraisalV1,
    current_time: float,
    config: TransitionConfig,
) -> TransitionResult:
    """Execute a complete emotional transition.

    This function is **pure** and **deterministic**: identical inputs
    always produce identical outputs.

    Parameters
    ----------
    previous_state:
        The emotional state before this transition.
    appraisal:
        The canonical ``AppraisalV1`` for this turn.
    current_time:
        The explicit current time as a positive finite float (Unix epoch
        seconds). Must not be ``bool``, ``None``, ``str``, ``list``,
        ``dict``, ``NaN``, ``Inf``, or <= 0.
    config:
        The ``TransitionConfig`` with validated parameters.

    Returns
    -------
    TransitionResult
        An immutable result containing the new ``EmotionalStateV1`` and
        the ``RegulationResult``.

    Raises
    ------
    EmotionalDomainError
        If *current_time* is invalid or *config* is invalid.
    """
    # ── 1. Validate current_time ────────────────────────────────────────────
    validated_time = _validate_current_time(current_time)

    # ── 2. Handle clock regression ──────────────────────────────────────────
    if validated_time < previous_state.timestamp:
        elapsed_seconds = 0.0
        output_timestamp = previous_state.timestamp
    else:
        elapsed_seconds = validated_time - previous_state.timestamp
        output_timestamp = validated_time

    # ── 3. Apply exponential decay (PAD + tension only) ────────────────────
    post_decay_pleasure = _exponential_decay(
        previous_state.pleasure,
        config.pad_baseline,
        elapsed_seconds,
        config.pad_half_life,
    )
    post_decay_arousal = _exponential_decay(
        previous_state.arousal,
        config.pad_baseline,
        elapsed_seconds,
        config.pad_half_life,
    )
    post_decay_dominance = _exponential_decay(
        previous_state.dominance,
        config.pad_baseline,
        elapsed_seconds,
        config.pad_half_life,
    )
    post_decay_tension = _exponential_decay(
        previous_state.tension,
        config.tension_baseline,
        elapsed_seconds,
        config.tension_half_life,
    )

    # ── 4. Apply capped appraisal shifts ────────────────────────────────────
    effective_valence = _clamp_shift(
        appraisal.valence_shift, config.max_pleasure_shift
    )
    effective_arousal = _clamp_shift(
        appraisal.arousal_shift, config.max_arousal_shift
    )
    effective_dominance = _clamp_shift(
        appraisal.dominance_shift, config.max_dominance_shift
    )

    post_shift_pleasure = post_decay_pleasure + effective_valence
    post_shift_arousal = post_decay_arousal + effective_arousal
    post_shift_dominance = post_decay_dominance + effective_dominance

    # ── 5. Clamp PAD to [-1.0, 1.0] ────────────────────────────────────────
    clamped_pleasure = _clamp(post_shift_pleasure, -1.0, 1.0)
    clamped_arousal = _clamp(post_shift_arousal, -1.0, 1.0)
    clamped_dominance = _clamp(post_shift_dominance, -1.0, 1.0)

    # ── 6. Update tension based on pleasure ────────────────────────────────
    tension_delta = 0.0
    if clamped_pleasure < config.negative_pleasure_threshold:
        tension_delta = config.tension_increase
    elif clamped_pleasure > config.positive_pleasure_threshold:
        tension_delta = -config.tension_relief

    post_tension = post_decay_tension + tension_delta

    # ── 7. Clamp tension to [0.0, 1.0] ────────────────────────────────────
    clamped_tension = _clamp(post_tension, 0.0, 1.0)

    # ── 8. Determine coping mode ────────────────────────────────────────────
    new_coping_mode = _determine_coping_mode(
        clamped_tension,
        clamped_dominance,
        previous_state.coping_mode,
        config,
    )

    # ── 9. Apply regulation effects ─────────────────────────────────────────
    reg_arousal = clamped_arousal
    if new_coping_mode == "DISSOCIATED":
        reg_arousal = _clamp(
            clamped_arousal * config.dissociation_arousal_factor, -1.0, 1.0
        )
    # DEFENSIVE: no additional effects beyond mode change in this version.

    # ── 10. Build RegulationResult ──────────────────────────────────────────
    mode_changed = previous_state.coping_mode != new_coping_mode
    if not mode_changed:
        reason = RegulationReason.NONE
    elif new_coping_mode == "HEALTHY":
        reason = RegulationReason.RECOVERED
    elif new_coping_mode == "DEFENSIVE":
        reason = RegulationReason.HIGH_TENSION_POSITIVE_DOMINANCE
    elif new_coping_mode == "DISSOCIATED":
        reason = RegulationReason.HIGH_TENSION_NONPOSITIVE_DOMINANCE
    else:
        reason = RegulationReason.NONE

    regulation = RegulationResult(
        previous_mode=previous_state.coping_mode,
        current_mode=new_coping_mode,
        changed=mode_changed,
        reason=reason,
    )

    # ── 11. Build new EmotionalStateV1 ──────────────────────────────────────
    new_state = EmotionalStateV1.create(
        pleasure=clamped_pleasure,
        arousal=reg_arousal,
        dominance=clamped_dominance,
        libido=previous_state.libido,
        aggression=previous_state.aggression,
        connection=previous_state.connection,
        energy=previous_state.energy,
        tension=clamped_tension,
        coping_mode=new_coping_mode,
        timestamp=output_timestamp,
        schema_version=EMOTIONAL_SCHEMA_VERSION,
    )

    return TransitionResult(state=new_state, regulation=regulation)
