"""
Core typed models for the emotional domain.

Invariants enforced at construction:
- All numeric fields are finite floats (not bool, not None, not NaN, not inf).
- PAD fields (pleasure, arousal, dominance): float in [-1.0, 1.0].
- Drive fields (libido, aggression, connection, energy, tension): float in [0.0, 1.0].
- coping_mode: one of VALID_COPING_MODES.
- timestamp: finite positive float (Unix epoch seconds).
- schema_version: must equal EMOTIONAL_SCHEMA_VERSION.
- No extra keys accepted (unknown fields are rejected).

Appraisal invariants:
- valence_shift, arousal_shift, dominance_shift: finite float in [-1.0, 1.0].
- discrete_emotions: dict mapping known emotion names to float intensities in [0.0, 1.0].
- Unknown emotion keys are REJECTED (strict allowlist policy).
- schema_version: must equal EMOTIONAL_SCHEMA_VERSION.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet

# ─── Schema version ─────────────────────────────────────────────────────────

EMOTIONAL_SCHEMA_VERSION: int = 1

# ─── Allowlists ─────────────────────────────────────────────────────────────

VALID_COPING_MODES: FrozenSet[str] = frozenset({
    "HEALTHY",
    "DEFENSIVE",
    "DISSOCIATED",
    "MANIC",
})

DISCRETE_EMOTIONS: FrozenSet[str] = frozenset({
    "joy",
    "sadness",
    "anger",
    "fear",
    "disgust",
    "surprise",
    "trust",
    "anticipation",
})

# ─── Domain error ────────────────────────────────────────────────────────────

class EmotionalDomainError(ValueError):
    """Raised when an emotional domain invariant is violated."""


# ─── Validation helpers ──────────────────────────────────────────────────────

def _require_finite_float(value: object, name: str) -> float:
    """
    Returns ``float(value)`` when *value* is a finite real number.

    Rejects: bool, None, str, list, dict, NaN, ±Inf.
    """
    if isinstance(value, bool):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got bool ({value!r})."
        )
    if not isinstance(value, (int, float)):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got {type(value).__name__} ({value!r})."
        )
    f = float(value)
    if not math.isfinite(f):
        raise EmotionalDomainError(
            f"Field '{name}' must be finite, got {f!r}."
        )
    return f


def _require_range(value: float, name: str, lo: float, hi: float) -> float:
    """Raises if *value* is outside [lo, hi]."""
    if value < lo or value > hi:
        raise EmotionalDomainError(
            f"Field '{name}' must be in [{lo}, {hi}], got {value!r}."
        )
    return value


def _require_finite_float_in_range(value: object, name: str, lo: float, hi: float) -> float:
    f = _require_finite_float(value, name)
    return _require_range(f, name, lo, hi)


def _require_positive_float(value: object, name: str) -> float:
    """Used for timestamp: must be finite and positive."""
    f = _require_finite_float(value, name)
    if f <= 0:
        raise EmotionalDomainError(
            f"Field '{name}' must be a positive finite float (Unix epoch), got {f!r}."
        )
    return f


# ─── EmotionalStateV1 ────────────────────────────────────────────────────────

# Fields accepted by EmotionalStateV1 (used to detect unknown keys).
_STATE_FIELDS: FrozenSet[str] = frozenset({
    "pleasure",
    "arousal",
    "dominance",
    "libido",
    "aggression",
    "connection",
    "energy",
    "tension",
    "coping_mode",
    "timestamp",
    "schema_version",
})


@dataclass(frozen=True)
class EmotionalStateV1:
    """
    Versioned, typed snapshot of the emotional state.

    Construction
    ============
    Use ``EmotionalStateV1.create(...)`` or ``EmotionalStateV1.neutral()`` —
    do NOT construct directly via ``EmotionalStateV1(...)`` unless you are
    sure all arguments already satisfy invariants (e.g. in tests).

    Fields
    ======
    PAD (Pleasure–Arousal–Dominance): float in [-1.0, 1.0]
    Drives/System (libido…tension):   float in [0.0, 1.0]
    coping_mode:                       one of VALID_COPING_MODES
    timestamp:                         positive finite float (Unix epoch s)
    schema_version:                    must equal EMOTIONAL_SCHEMA_VERSION
    """

    # PAD — bipolar [-1.0, +1.0]
    pleasure: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0

    # Drives / system — unipolar [0.0, 1.0]
    libido: float = 0.0
    aggression: float = 0.0
    connection: float = 0.5
    energy: float = 0.8
    tension: float = 0.0

    # Categorical
    coping_mode: str = "HEALTHY"

    # Metadata
    timestamp: float = field(default=0.0)
    schema_version: int = EMOTIONAL_SCHEMA_VERSION

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def neutral(cls, timestamp: float = 1.0) -> "EmotionalStateV1":
        """Return a valid neutral snapshot with all numeric fields at defaults."""
        return cls.create(
            pleasure=0.0,
            arousal=0.0,
            dominance=0.0,
            libido=0.0,
            aggression=0.0,
            connection=0.5,
            energy=0.8,
            tension=0.0,
            coping_mode="HEALTHY",
            timestamp=timestamp,
        )

    @classmethod
    def create(
        cls,
        *,
        pleasure: object,
        arousal: object,
        dominance: object,
        libido: object,
        aggression: object,
        connection: object,
        energy: object,
        tension: object,
        coping_mode: object,
        timestamp: object,
        schema_version: object = EMOTIONAL_SCHEMA_VERSION,
    ) -> "EmotionalStateV1":
        """
        Validated factory. Raises EmotionalDomainError on any invariant violation.
        """
        # schema_version
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise EmotionalDomainError(
                f"schema_version must be an int, got {type(schema_version).__name__}."
            )
        if schema_version != EMOTIONAL_SCHEMA_VERSION:
            raise EmotionalDomainError(
                f"Unsupported schema_version {schema_version!r}. "
                f"Expected {EMOTIONAL_SCHEMA_VERSION}."
            )

        # PAD [-1, 1]
        p = _require_finite_float_in_range(pleasure, "pleasure", -1.0, 1.0)
        a = _require_finite_float_in_range(arousal, "arousal", -1.0, 1.0)
        d = _require_finite_float_in_range(dominance, "dominance", -1.0, 1.0)

        # Drives [0, 1]
        lib = _require_finite_float_in_range(libido, "libido", 0.0, 1.0)
        agg = _require_finite_float_in_range(aggression, "aggression", 0.0, 1.0)
        con = _require_finite_float_in_range(connection, "connection", 0.0, 1.0)
        eng = _require_finite_float_in_range(energy, "energy", 0.0, 1.0)
        ten = _require_finite_float_in_range(tension, "tension", 0.0, 1.0)

        # coping_mode
        if not isinstance(coping_mode, str):
            raise EmotionalDomainError(
                f"coping_mode must be a str, got {type(coping_mode).__name__}."
            )
        if coping_mode not in VALID_COPING_MODES:
            raise EmotionalDomainError(
                f"Unknown coping_mode {coping_mode!r}. "
                f"Allowed: {sorted(VALID_COPING_MODES)}."
            )

        # timestamp
        ts = _require_positive_float(timestamp, "timestamp")

        return cls(
            pleasure=p,
            arousal=a,
            dominance=d,
            libido=lib,
            aggression=agg,
            connection=con,
            energy=eng,
            tension=ten,
            coping_mode=coping_mode,
            timestamp=ts,
            schema_version=schema_version,
        )

    @classmethod
    def from_dict(cls, data: object) -> "EmotionalStateV1":
        """
        Deserialise from a plain dict. Rejects unknown keys and missing
        required fields, then delegates to ``create``.
        """
        if not isinstance(data, dict):
            raise EmotionalDomainError(
                f"Expected a dict, got {type(data).__name__}."
            )

        # Reject unknown keys
        unknown = set(data.keys()) - _STATE_FIELDS
        if unknown:
            raise EmotionalDomainError(
                f"Unknown fields in EmotionalStateV1 payload: {sorted(unknown)}."
            )

        # Require schema_version present
        if "schema_version" not in data:
            raise EmotionalDomainError(
                "Field 'schema_version' is missing from EmotionalStateV1 payload."
            )

        required = _STATE_FIELDS - {"schema_version"}
        missing = required - set(data.keys())
        if missing:
            raise EmotionalDomainError(
                f"Missing required fields in EmotionalStateV1 payload: {sorted(missing)}."
            )

        return cls.create(
            pleasure=data["pleasure"],
            arousal=data["arousal"],
            dominance=data["dominance"],
            libido=data["libido"],
            aggression=data["aggression"],
            connection=data["connection"],
            energy=data["energy"],
            tension=data["tension"],
            coping_mode=data["coping_mode"],
            timestamp=data["timestamp"],
            schema_version=data["schema_version"],
        )

    def to_dict(self) -> Dict[str, object]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return {
            "schema_version": self.schema_version,
            "pleasure": self.pleasure,
            "arousal": self.arousal,
            "dominance": self.dominance,
            "libido": self.libido,
            "aggression": self.aggression,
            "connection": self.connection,
            "energy": self.energy,
            "tension": self.tension,
            "coping_mode": self.coping_mode,
            "timestamp": self.timestamp,
        }


# ─── AppraisalV1 ─────────────────────────────────────────────────────────────

_APPRAISAL_SCALAR_FIELDS: FrozenSet[str] = frozenset({
    "valence_shift",
    "arousal_shift",
    "dominance_shift",
    "schema_version",
})

_APPRAISAL_ALL_FIELDS: FrozenSet[str] = _APPRAISAL_SCALAR_FIELDS | {"discrete_emotions"}


@dataclass(frozen=True)
class AppraisalV1:
    """
    Versioned appraisal produced by cognitive evaluation of a message or event.

    Fields
    ======
    valence_shift:   float in [-1.0, 1.0] — desired pleasure shift
    arousal_shift:   float in [-1.0, 1.0] — desired arousal shift
    dominance_shift: float in [-1.0, 1.0] — desired dominance shift
    discrete_emotions: mapping from DISCRETE_EMOTIONS names to intensity [0.0, 1.0]
                       Unknown keys are REJECTED.
    schema_version:  must equal EMOTIONAL_SCHEMA_VERSION

    Neutral appraisal
    =================
    All shifts are 0.0 and discrete_emotions is empty. Use ``AppraisalV1.neutral()``.
    """

    valence_shift: float = 0.0
    arousal_shift: float = 0.0
    dominance_shift: float = 0.0
    discrete_emotions: Dict[str, float] = field(default_factory=dict)
    schema_version: int = EMOTIONAL_SCHEMA_VERSION

    # ── Factory methods ───────────────────────────────────────────────────────

    @classmethod
    def neutral(cls) -> "AppraisalV1":
        """Return an explicitly neutral appraisal (all zeros, no emotions)."""
        return cls(
            valence_shift=0.0,
            arousal_shift=0.0,
            dominance_shift=0.0,
            discrete_emotions={},
            schema_version=EMOTIONAL_SCHEMA_VERSION,
        )

    @classmethod
    def create(
        cls,
        *,
        valence_shift: object,
        arousal_shift: object,
        dominance_shift: object,
        discrete_emotions: object = None,
        schema_version: object = EMOTIONAL_SCHEMA_VERSION,
    ) -> "AppraisalV1":
        """
        Validated factory. Raises EmotionalDomainError on any invariant violation.
        """
        # schema_version
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise EmotionalDomainError(
                f"schema_version must be an int, got {type(schema_version).__name__}."
            )
        if schema_version != EMOTIONAL_SCHEMA_VERSION:
            raise EmotionalDomainError(
                f"Unsupported schema_version {schema_version!r}. "
                f"Expected {EMOTIONAL_SCHEMA_VERSION}."
            )

        # Scalar shifts [-1, 1]
        vs = _require_finite_float_in_range(valence_shift, "valence_shift", -1.0, 1.0)
        as_ = _require_finite_float_in_range(arousal_shift, "arousal_shift", -1.0, 1.0)
        ds = _require_finite_float_in_range(dominance_shift, "dominance_shift", -1.0, 1.0)

        # discrete_emotions
        if discrete_emotions is None:
            de: Dict[str, float] = {}
        elif not isinstance(discrete_emotions, dict):
            raise EmotionalDomainError(
                f"discrete_emotions must be a dict, got {type(discrete_emotions).__name__}."
            )
        else:
            de = {}
            for emotion, intensity in discrete_emotions.items():
                if not isinstance(emotion, str):
                    raise EmotionalDomainError(
                        f"Emotion key must be a str, got {type(emotion).__name__}."
                    )
                if emotion not in DISCRETE_EMOTIONS:
                    raise EmotionalDomainError(
                        f"Unknown discrete emotion {emotion!r}. "
                        f"Allowed: {sorted(DISCRETE_EMOTIONS)}."
                    )
                de[emotion] = _require_finite_float_in_range(
                    intensity, f"discrete_emotions[{emotion!r}]", 0.0, 1.0
                )

        return cls(
            valence_shift=vs,
            arousal_shift=as_,
            dominance_shift=ds,
            discrete_emotions=de,
            schema_version=schema_version,
        )

    @classmethod
    def from_dict(cls, data: object) -> "AppraisalV1":
        """
        Deserialise from a plain dict. Rejects unknown keys, missing required
        fields, and any value that violates invariants.
        """
        if not isinstance(data, dict):
            raise EmotionalDomainError(
                f"Expected a dict, got {type(data).__name__}."
            )

        # Reject unknown keys
        unknown = set(data.keys()) - _APPRAISAL_ALL_FIELDS
        if unknown:
            raise EmotionalDomainError(
                f"Unknown fields in AppraisalV1 payload: {sorted(unknown)}."
            )

        # Require schema_version present
        if "schema_version" not in data:
            raise EmotionalDomainError(
                "Field 'schema_version' is missing from AppraisalV1 payload."
            )

        required_scalars = {"valence_shift", "arousal_shift", "dominance_shift"}
        missing = required_scalars - set(data.keys())
        if missing:
            raise EmotionalDomainError(
                f"Missing required fields in AppraisalV1 payload: {sorted(missing)}."
            )

        return cls.create(
            valence_shift=data["valence_shift"],
            arousal_shift=data["arousal_shift"],
            dominance_shift=data["dominance_shift"],
            discrete_emotions=data.get("discrete_emotions"),
            schema_version=data["schema_version"],
        )

    def to_dict(self) -> Dict[str, object]:
        """Serialise to a plain dict suitable for JSON encoding."""
        return {
            "schema_version": self.schema_version,
            "valence_shift": self.valence_shift,
            "arousal_shift": self.arousal_shift,
            "dominance_shift": self.dominance_shift,
            "discrete_emotions": dict(self.discrete_emotions),
        }
