"""
Core typed models for the emotional domain.

Invariants enforced on ALL public construction paths (including direct __init__):
- All numeric fields are finite floats (not bool, not None, not NaN, not inf).
- PAD fields (pleasure, arousal, dominance): float in [-1.0, 1.0].
- Drive fields (libido, aggression, connection, energy, tension): float in [0.0, 1.0].
- coping_mode: one of VALID_COPING_MODES.
- timestamp: finite positive float (Unix epoch seconds).
- schema_version: must equal EMOTIONAL_SCHEMA_VERSION; must be int, not bool/float/str/None.
- No extra keys accepted via from_dict (unknown fields are rejected).

AppraisalV1 additional invariants:
- valence_shift, arousal_shift, dominance_shift: finite float in [-1.0, 1.0].
- discrete_emotions: deeply immutable mapping of known emotion → intensity in [0.0, 1.0].
  Unknown emotion keys are REJECTED (strict allowlist policy).
  The stored mapping cannot be mutated by the caller after construction.
- schema_version: same rules as above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, FrozenSet, Mapping

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
    # Core emotions
    "joy",
    "sadness",
    "anger",
    "fear",
    "disgust",
    "surprise",
    # Extended emotions (from v1 model)
    "trust",
    "anticipation",
    # Production emotions (consumed by RelationshipManager via _perceive)
    "tenderness",
    "guilt",
    "pride",
    "jealousy",
    "gratitude",
})

# ─── Domain error ────────────────────────────────────────────────────────────

class EmotionalDomainError(ValueError):
    """Raised when an emotional domain invariant is violated."""


# ─── Validation helpers ──────────────────────────────────────────────────────

def _require_schema_version(value: object) -> int:
    """
    Accepts only ``int`` (not bool) equal to ``EMOTIONAL_SCHEMA_VERSION``.
    Raises ``EmotionalDomainError`` for bool, float, str, None, wrong version.
    """
    if value is None or isinstance(value, bool):
        raise EmotionalDomainError(
            f"schema_version must be an int equal to {EMOTIONAL_SCHEMA_VERSION}, "
            f"got {type(value).__name__}."
        )
    if not isinstance(value, int):
        raise EmotionalDomainError(
            f"schema_version must be an int, got {type(value).__name__}."
        )
    if value != EMOTIONAL_SCHEMA_VERSION:
        raise EmotionalDomainError(
            f"Unsupported schema_version {value!r}. "
            f"Expected {EMOTIONAL_SCHEMA_VERSION}."
        )
    return value


def _require_finite_float(value: object, name: str) -> float:
    """
    Returns ``float(value)`` when *value* is a finite real number.

    Rejects: bool, None, str, list, dict, NaN, ±Inf.
    Also catches ``OverflowError`` for integers too large to represent as float
    and converts it to a sanitised ``EmotionalDomainError`` (no raw value leaked).
    """
    if isinstance(value, bool):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got bool."
        )
    if not isinstance(value, (int, float)):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got {type(value).__name__}."
        )
    try:
        f = float(value)
    except (OverflowError, ValueError, TypeError):
        raise EmotionalDomainError(
            f"Field '{name}' must be a finite float, got non-convertible value."
        )
    if not math.isfinite(f):
        raise EmotionalDomainError(
            f"Field '{name}' must be finite, got non-finite value."
        )
    return f


def _require_range(value: float, name: str, lo: float, hi: float) -> float:
    """Raises if *value* is outside [lo, hi]."""
    if value < lo or value > hi:
        raise EmotionalDomainError(
            f"Field '{name}' must be in [{lo}, {hi}], got out-of-range value."
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
            f"Field '{name}' must be a positive finite float (Unix epoch)."
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


def _validate_state_fields(
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
    schema_version: object,
) -> tuple:
    """
    Validate all EmotionalStateV1 fields and return a tuple of validated values
    in order: (schema_version, pleasure, arousal, dominance, libido, aggression,
               connection, energy, tension, coping_mode, timestamp).
    Raises EmotionalDomainError on any violation.
    """
    sv = _require_schema_version(schema_version)

    p = _require_finite_float_in_range(pleasure, "pleasure", -1.0, 1.0)
    a = _require_finite_float_in_range(arousal, "arousal", -1.0, 1.0)
    d = _require_finite_float_in_range(dominance, "dominance", -1.0, 1.0)

    lib = _require_finite_float_in_range(libido, "libido", 0.0, 1.0)
    agg = _require_finite_float_in_range(aggression, "aggression", 0.0, 1.0)
    con = _require_finite_float_in_range(connection, "connection", 0.0, 1.0)
    eng = _require_finite_float_in_range(energy, "energy", 0.0, 1.0)
    ten = _require_finite_float_in_range(tension, "tension", 0.0, 1.0)

    if not isinstance(coping_mode, str):
        raise EmotionalDomainError(
            f"coping_mode must be a str, got {type(coping_mode).__name__}."
        )
    if coping_mode not in VALID_COPING_MODES:
        raise EmotionalDomainError(
            f"Unknown coping_mode. Allowed: {sorted(VALID_COPING_MODES)}."
        )

    ts = _require_positive_float(timestamp, "timestamp")

    return (sv, p, a, d, lib, agg, con, eng, ten, coping_mode, ts)


@dataclass(frozen=True)
class EmotionalStateV1:
    """
    Versioned, typed snapshot of the emotional state.

    All public construction paths validate invariants:
    - Direct ``EmotionalStateV1(...)`` calls ``__post_init__`` which validates.
    - ``EmotionalStateV1.create(...)`` validates then delegates to ``__init__``.
    - ``EmotionalStateV1.from_dict(...)`` validates structure then delegates to create.
    - ``EmotionalStateV1.neutral(...)`` delegates to create.

    There is no way to produce an invalid instance.

    Fields
    ======
    PAD (Pleasure–Arousal–Dominance): float in [-1.0, 1.0]
    Drives/System (libido…tension):   float in [0.0, 1.0]
    coping_mode:                       one of VALID_COPING_MODES
    timestamp:                         positive finite float (Unix epoch s)
    schema_version:                    must equal EMOTIONAL_SCHEMA_VERSION
    """

    # PAD — bipolar [-1.0, +1.0]
    pleasure: float
    arousal: float
    dominance: float

    # Drives / system — unipolar [0.0, 1.0]
    libido: float
    aggression: float
    connection: float
    energy: float
    tension: float

    # Categorical
    coping_mode: str

    # Metadata
    timestamp: float
    schema_version: int

    def __post_init__(self) -> None:
        """
        Validate all fields on every construction path (including direct __init__)
        AND normalize values (e.g. int → float) to ensure type-stable representation.
        Because the dataclass is frozen, we must use object.__setattr__ during
        __post_init__.
        """
        sv, p, a, d, lib, agg, con, eng, ten, cm, ts = _validate_state_fields(
            schema_version=self.schema_version,
            pleasure=self.pleasure,
            arousal=self.arousal,
            dominance=self.dominance,
            libido=self.libido,
            aggression=self.aggression,
            connection=self.connection,
            energy=self.energy,
            tension=self.tension,
            coping_mode=self.coping_mode,
            timestamp=self.timestamp,
        )
        # Assign normalized values back (int → float, etc.)
        object.__setattr__(self, "pleasure", p)
        object.__setattr__(self, "arousal", a)
        object.__setattr__(self, "dominance", d)
        object.__setattr__(self, "libido", lib)
        object.__setattr__(self, "aggression", agg)
        object.__setattr__(self, "connection", con)
        object.__setattr__(self, "energy", eng)
        object.__setattr__(self, "tension", ten)
        object.__setattr__(self, "timestamp", ts)
        object.__setattr__(self, "schema_version", sv)

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
        ``__post_init__`` will also run and validate, providing defence-in-depth.
        """
        sv, p, a, d, lib, agg, con, eng, ten, cm, ts = _validate_state_fields(
            schema_version=schema_version,
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
        return cls(
            pleasure=p,
            arousal=a,
            dominance=d,
            libido=lib,
            aggression=agg,
            connection=con,
            energy=eng,
            tension=ten,
            coping_mode=cm,
            timestamp=ts,
            schema_version=sv,
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
                "Unknown fields in EmotionalStateV1 payload."
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
                "Missing required fields in EmotionalStateV1 payload."
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


# ─── Sentinel for "argument omitted" vs "None" distinction ──────────────────────

_UNSET = object()


# ─── AppraisalV1 ─────────────────────────────────────────────────────────────

_APPRAISAL_SCALAR_FIELDS: FrozenSet[str] = frozenset({
    "valence_shift",
    "arousal_shift",
    "dominance_shift",
    "schema_version",
})

_APPRAISAL_ALL_FIELDS: FrozenSet[str] = _APPRAISAL_SCALAR_FIELDS | {"discrete_emotions"}


def _validate_discrete_emotions(raw: object) -> Dict[str, float]:
    """
    Validate a discrete_emotions mapping. Returns a new plain dict.
    Accepts: dict (including empty). Rejects: None, str, list, number, bool.
    Unknown emotion keys are rejected (strict policy).
    """
    if raw is None or isinstance(raw, bool):
        raise EmotionalDomainError(
            f"discrete_emotions must be a dict, got {type(raw).__name__}."
        )
    if not isinstance(raw, dict):
        raise EmotionalDomainError(
            f"discrete_emotions must be a dict, got {type(raw).__name__}."
        )
    result: Dict[str, float] = {}
    for emotion, intensity in raw.items():
        if not isinstance(emotion, str):
            raise EmotionalDomainError(
                "Emotion key must be a str."
            )
        if emotion not in DISCRETE_EMOTIONS:
            raise EmotionalDomainError(
                f"Unknown discrete emotion. Allowed: {sorted(DISCRETE_EMOTIONS)}."
            )
        result[emotion] = _require_finite_float_in_range(
            intensity, f"discrete_emotions['{emotion}']", 0.0, 1.0
        )
    return result


@dataclass(frozen=True)
class AppraisalV1:
    """
    Versioned appraisal produced by cognitive evaluation of a message or event.

    Deep immutability
    =================
    ``discrete_emotions`` is stored as a ``MappingProxyType`` — it cannot be
    mutated after construction, and the original dict provided by the caller
    is copied defensively, so caller modifications have no effect.

    ``to_dict()`` returns a fresh mutable copy of the mapping for serialisation,
    but that copy does not share state with the stored proxy.

    All public construction paths validate invariants:
    - Direct ``AppraisalV1(...)`` calls ``__post_init__`` which validates.
    - ``AppraisalV1.create(...)`` validates then delegates to ``__init__``.
    - ``AppraisalV1.neutral()`` delegates to create.

    Fields
    ======
    valence_shift:   float in [-1.0, 1.0] — desired pleasure shift
    arousal_shift:   float in [-1.0, 1.0] — desired arousal shift
    dominance_shift: float in [-1.0, 1.0] — desired dominance shift
    discrete_emotions: immutable mapping from DISCRETE_EMOTIONS names to [0.0, 1.0]
                       Unknown keys are REJECTED.
    schema_version:  must equal EMOTIONAL_SCHEMA_VERSION

    Neutral appraisal
    =================
    All shifts are 0.0 and discrete_emotions is empty. Use ``AppraisalV1.neutral()``.
    """

    valence_shift: float
    arousal_shift: float
    dominance_shift: float
    # Stored as MappingProxyType for deep immutability.
    discrete_emotions: Mapping[str, float]
    schema_version: int

    def __post_init__(self) -> None:
        """
        Validate all fields, normalize values (int → float), and enforce deep
        immutability on every construction path.
        Converts a plain dict input into a MappingProxyType.
        """
        # schema_version
        sv = _require_schema_version(self.schema_version)
        object.__setattr__(self, "schema_version", sv)

        # Scalar shifts — validate AND normalize
        vs = _require_finite_float_in_range(self.valence_shift, "valence_shift", -1.0, 1.0)
        ar = _require_finite_float_in_range(self.arousal_shift, "arousal_shift", -1.0, 1.0)
        ds = _require_finite_float_in_range(self.dominance_shift, "dominance_shift", -1.0, 1.0)
        object.__setattr__(self, "valence_shift", vs)
        object.__setattr__(self, "arousal_shift", ar)
        object.__setattr__(self, "dominance_shift", ds)

        # Validate and convert discrete_emotions to an immutable proxy.
        # We always make a fresh copy to prevent the caller's dict from being
        # aliased inside the model.
        de = self.discrete_emotions
        if isinstance(de, MappingProxyType):
            # Already a proxy — validate its contents but keep it as-is.
            validated = _validate_discrete_emotions(dict(de))
        else:
            validated = _validate_discrete_emotions(de)

        # Replace discrete_emotions with an immutable proxy (works even on frozen
        # dataclasses because __post_init__ runs before the object is "sealed").
        object.__setattr__(self, "discrete_emotions", MappingProxyType(validated))

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
        discrete_emotions: object = _UNSET,
        schema_version: object = EMOTIONAL_SCHEMA_VERSION,
    ) -> "AppraisalV1":
        """
        Validated factory. Raises EmotionalDomainError on any invariant violation.
        ``__post_init__`` will also run and validate, providing defence-in-depth.

        - Omitted ``discrete_emotions`` (default) → empty mapping.
        - Explicit ``discrete_emotions=None`` → raises EmotionalDomainError.
        - ``discrete_emotions={}`` → valid empty mapping.
        - Any other non-dict type raises EmotionalDomainError.
        """
        sv = _require_schema_version(schema_version)

        vs = _require_finite_float_in_range(valence_shift, "valence_shift", -1.0, 1.0)
        as_ = _require_finite_float_in_range(arousal_shift, "arousal_shift", -1.0, 1.0)
        ds = _require_finite_float_in_range(dominance_shift, "dominance_shift", -1.0, 1.0)

        # Sentinel: omitted → empty dict. Explicit None → rejected.
        if discrete_emotions is None:
            raise EmotionalDomainError(
                "discrete_emotions must be a dict, got None."
            )
        de_raw: object = {} if discrete_emotions is _UNSET else discrete_emotions
        de = _validate_discrete_emotions(de_raw)

        return cls(
            valence_shift=vs,
            arousal_shift=as_,
            dominance_shift=ds,
            discrete_emotions=de,
            schema_version=sv,
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
                "Unknown fields in AppraisalV1 payload."
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
                "Missing required fields in AppraisalV1 payload."
            )

        # discrete_emotions is optional in serialised form.
        # If the key is absent → empty mapping.
        # If the key is present with None → reject (fail-closed).
        if "discrete_emotions" not in data:
            de_input: object = _UNSET  # will resolve to empty in create()
        else:
            de_raw = data["discrete_emotions"]
            if de_raw is None:
                raise EmotionalDomainError(
                    "discrete_emotions must be a dict, got None."
                )
            de_input = de_raw  # will be validated in create()
        

        return cls.create(
            valence_shift=data["valence_shift"],
            arousal_shift=data["arousal_shift"],
            dominance_shift=data["dominance_shift"],
            discrete_emotions=de_input,
            schema_version=data["schema_version"],
        )

    def to_dict(self) -> Dict[str, object]:
        """
        Serialise to a plain dict suitable for JSON encoding.
        The returned dict is a fresh copy — modifying it has no effect on this object.
        """
        return {
            "schema_version": self.schema_version,
            "valence_shift": self.valence_shift,
            "arousal_shift": self.arousal_shift,
            "dominance_shift": self.dominance_shift,
            "discrete_emotions": dict(self.discrete_emotions),
        }
