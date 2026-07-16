"""
Versioned, typed, immutable relationship snapshot v1.

Design principles
=================
- **Pure**: no I/O, no FastAPI, no Supabase, no Groq, no embeddings, no network, no env vars.
- **Immutable**: ``RelationshipStateV1`` is a frozen dataclass. No method modifies an
  instance. Transition produces a new instance.
- **Validated**: ALL public construction paths (direct ``__init__``, ``create``, ``from_dict``)
  enforce the same invariants before the instance is usable.
- **Versioned**: ``schema_version`` is always ``1``. Unknown values are rejected.
- **Identity-free**: ``user_id`` does NOT belong to the snapshot. Identity comes from the
  authenticated context (``ConversationEngine``, ``MemoryManager``).
- **Bond-label-free**: ``bond_label`` is always derived from the validated state via
  ``compute_bond_label()``. It is never stored in the snapshot.

Fields persisted (JSONB)
========================
  trust, affection, tension, triggers, timestamp, schema_version

Never persisted
===============
  user_id, bond_label

Invariants
==========
- ``schema_version`` must be int (not bool) and exactly ``1``.
- ``trust``, ``affection``, ``tension`` must be finite floats in ``[0.0, 1.0]``.
- Reject ``bool``, ``None``, ``str``, ``list``, ``dict``, ``NaN``, ``inf``.
- Values outside ``[0.0, 1.0]`` are rejected (no silent clamp).
- ``timestamp`` must be a finite positive float.
- ``triggers`` must be a list or tuple of trimmed, non-empty, deduplicated strings,
  max 32 items, each max 128 chars.
- Unknown keys are rejected by ``from_dict``.
- Missing required fields are rejected by ``from_dict``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Sequence, Tuple

from .emotional_domain.models import AppraisalV1

# ─── Schema version ─────────────────────────────────────────────────────────

RELATIONSHIP_SCHEMA_VERSION: int = 1


# ─── Domain error ────────────────────────────────────────────────────────────

class RelationshipDomainError(ValueError):
    """Raised when a relationship domain invariant is violated."""


# ─── Validated fields set ────────────────────────────────────────────────────

_RELATIONSHIP_FIELDS: FrozenSet[str] = frozenset({
    "trust",
    "affection",
    "tension",
    "triggers",
    "timestamp",
    "schema_version",
})

# Legacy fields that are accepted during migration but not stored.
_LEGACY_ALLOWED_FIELDS: FrozenSet[str] = frozenset({
    "user_id",
    "bond_label",
    "trust",
    "affection",
    "tension",
    "triggers",
    "last_interaction",
})

# ─── Validation helpers ──────────────────────────────────────────────────────


def _require_schema_version(value: object) -> int:
    """Accept only ``int`` (not bool) equal to ``RELATIONSHIP_SCHEMA_VERSION``."""
    if value is None or isinstance(value, bool):
        raise RelationshipDomainError(
            f"schema_version must be an int equal to {RELATIONSHIP_SCHEMA_VERSION}, "
            f"got {type(value).__name__}."
        )
    if not isinstance(value, int):
        raise RelationshipDomainError(
            f"schema_version must be an int, got {type(value).__name__}."
        )
    if value != RELATIONSHIP_SCHEMA_VERSION:
        raise RelationshipDomainError(
            f"Unsupported schema_version {value!r}. "
            f"Expected {RELATIONSHIP_SCHEMA_VERSION}."
        )
    return value


def _require_finite_float(value: object, name: str) -> float:
    """Return float(value) when value is a finite real number.

    Rejects: bool, None, str, list, dict, NaN, ±Inf.
    """
    if isinstance(value, bool):
        raise RelationshipDomainError(
            f"Field '{name}' must be a finite float, got bool."
        )
    if not isinstance(value, (int, float)):
        raise RelationshipDomainError(
            f"Field '{name}' must be a finite float, got {type(value).__name__}."
        )
    try:
        f = float(value)
    except (OverflowError, ValueError, TypeError):
        raise RelationshipDomainError(
            f"Field '{name}' must be a finite float, got non-convertible value."
        )
    if not math.isfinite(f):
        raise RelationshipDomainError(
            f"Field '{name}' must be finite, got non-finite value."
        )
    return f


def _require_range(value: float, name: str, lo: float, hi: float) -> float:
    if value < lo or value > hi:
        raise RelationshipDomainError(
            f"Field '{name}' must be in [{lo}, {hi}], got out-of-range value."
        )
    return value


def _require_finite_float_in_range(
    value: object, name: str, lo: float, hi: float,
) -> float:
    f = _require_finite_float(value, name)
    return _require_range(f, name, lo, hi)


def _require_positive_float(value: object, name: str) -> float:
    f = _require_finite_float(value, name)
    if f <= 0:
        raise RelationshipDomainError(
            f"Field '{name}' must be a positive finite float."
        )
    return f


def _require_current_time(value: object) -> float:
    """Validate a current_time argument: finite positive float.

    Rejects: bool, None, str, list, dict, NaN, inf, <= 0.
    """
    if isinstance(value, bool):
        raise RelationshipDomainError(
            "current_time must be a finite positive float, got bool."
        )
    if value is None:
        raise RelationshipDomainError(
            "current_time must be a finite positive float, got None."
        )
    if not isinstance(value, (int, float)):
        raise RelationshipDomainError(
            f"current_time must be a finite positive float, "
            f"got {type(value).__name__}."
        )
    try:
        f = float(value)
    except (OverflowError, ValueError, TypeError):
        raise RelationshipDomainError(
            "current_time must be a finite positive float, "
            "got non-convertible value."
        )
    if not math.isfinite(f):
        raise RelationshipDomainError(
            "current_time must be finite."
        )
    if f <= 0:
        raise RelationshipDomainError(
            "current_time must be positive."
        )
    return f


def _validate_triggers(raw: object) -> Tuple[str, ...]:
    """Validate and normalise triggers.

    Rules:
    - Accept only list or tuple.
    - Max 32 items (applied to the input collection BEFORE dedup).
    - Each item must be a string; apply .strip().
    - Reject empty after strip.
    - Max 128 characters per item.
    - Deduplicate preserving first occurrence and order.
    - Return an immutable tuple.
    """
    if not isinstance(raw, (list, tuple)):
        raise RelationshipDomainError(
            f"triggers must be a list or tuple, got {type(raw).__name__}."
        )

    # Apply limit to the input collection BEFORE deduplication
    if len(raw) > 32:
        raise RelationshipDomainError(
            f"triggers must have at most 32 items, got {len(raw)}."
        )

    seen: set = set()
    result: List[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, str):
            raise RelationshipDomainError(
                f"Each trigger must be a string, got {type(item).__name__} at index {i}."
            )
        stripped = item.strip()
        if not stripped:
            raise RelationshipDomainError(
                f"Trigger at index {i} is empty after trimming."
            )
        if len(stripped) > 128:
            raise RelationshipDomainError(
                f"Trigger at index {i} exceeds 128 characters."
            )
        if stripped not in seen:
            seen.add(stripped)
            result.append(stripped)

    return tuple(result)


# ─── RelationshipStateV1 ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class RelationshipStateV1:
    """Versioned, typed, immutable relationship snapshot.

    All public construction paths validate the same invariants:
    - Direct ``RelationshipStateV1(...)`` validates via ``__post_init__``.
    - ``RelationshipStateV1.create(...)`` validates then delegates to ``__init__``.
    - ``RelationshipStateV1.from_dict(...)`` validates structure then delegates to ``create``.
    - ``RelationshipStateV1.neutral(...)`` delegates to ``create``.
    """

    # Metadata — MUST come before fields with defaults
    timestamp: float
    schema_version: int = RELATIONSHIP_SCHEMA_VERSION

    # Relationship metrics — unipolar [0.0, 1.0]
    trust: float = 0.5
    affection: float = 0.3
    tension: float = 0.0

    # Emotional triggers — deeply immutable tuple of unique strings
    triggers: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate all fields on every construction path."""
        sv = _require_schema_version(self.schema_version)

        tr = _require_finite_float_in_range(self.trust, "trust", 0.0, 1.0)
        af = _require_finite_float_in_range(self.affection, "affection", 0.0, 1.0)
        te = _require_finite_float_in_range(self.tension, "tension", 0.0, 1.0)

        ts = _require_positive_float(self.timestamp, "timestamp")

        # triggers — validate and normalise
        tgs = _validate_triggers(self.triggers)

        # Assign normalised values back
        object.__setattr__(self, "trust", tr)
        object.__setattr__(self, "affection", af)
        object.__setattr__(self, "tension", te)
        object.__setattr__(self, "timestamp", ts)
        object.__setattr__(self, "triggers", tgs)
        object.__setattr__(self, "schema_version", sv)

    # ── Factory methods ──────────────────────────────────────────────────────

    @classmethod
    def neutral(cls, timestamp: float) -> "RelationshipStateV1":
        """Return a valid neutral snapshot with default metrics."""
        return cls.create(
            trust=0.5,
            affection=0.3,
            tension=0.0,
            triggers=(),
            timestamp=timestamp,
        )

    @classmethod
    def create(
        cls,
        *,
        trust: object,
        affection: object,
        tension: object,
        triggers: object,
        timestamp: object,
        schema_version: object = RELATIONSHIP_SCHEMA_VERSION,
    ) -> "RelationshipStateV1":
        """Validated factory. Raises ``RelationshipDomainError`` on violation."""
        sv = _require_schema_version(schema_version)
        tr = _require_finite_float_in_range(trust, "trust", 0.0, 1.0)
        af = _require_finite_float_in_range(affection, "affection", 0.0, 1.0)
        te = _require_finite_float_in_range(tension, "tension", 0.0, 1.0)
        ts = _require_positive_float(timestamp, "timestamp")
        tgs = _validate_triggers(triggers)
        return cls(
            trust=tr,
            affection=af,
            tension=te,
            triggers=tgs,
            timestamp=ts,
            schema_version=sv,
        )

    @classmethod
    def from_dict(cls, data: object) -> "RelationshipStateV1":
        """Deserialise from a plain dict (v1 format).

        Rejects unknown keys and missing required fields.
        Does NOT accept legacy fields (use ``migrate_legacy_relationship_snapshot``).
        """
        if not isinstance(data, dict):
            raise RelationshipDomainError(
                f"Expected a dict, got {type(data).__name__}."
            )

        # Reject unknown keys
        unknown = set(data.keys()) - _RELATIONSHIP_FIELDS
        if unknown:
            raise RelationshipDomainError(
                "Unknown fields in RelationshipStateV1 payload."
            )

        # Require schema_version present
        if "schema_version" not in data:
            raise RelationshipDomainError(
                "Field 'schema_version' is missing from RelationshipStateV1 payload."
            )

        required = _RELATIONSHIP_FIELDS - {"schema_version"}
        missing = required - set(data.keys())
        if missing:
            raise RelationshipDomainError(
                "Missing required fields in RelationshipStateV1 payload."
            )

        return cls.create(
            trust=data["trust"],
            affection=data["affection"],
            tension=data["tension"],
            triggers=data["triggers"],
            timestamp=data["timestamp"],
            schema_version=data["schema_version"],
        )

    def to_dict(self) -> Dict[str, object]:
        """Serialise to a plain dict suitable for JSON encoding.

        Contains exactly the v1 fields. Does NOT include ``user_id`` or ``bond_label``.
        Converts immutable triggers tuple to a list for JSON compatibility.
        """
        return {
            "schema_version": self.schema_version,
            "trust": self.trust,
            "affection": self.affection,
            "tension": self.tension,
            "triggers": list(self.triggers),
            "timestamp": self.timestamp,
        }


# ─── Bond label derivation (pure function) ───────────────────────────────────

def compute_bond_label(state: RelationshipStateV1) -> str:
    """Derive the human-readable bond label from validated relationship metrics.

    Preserves the exact labels and thresholds from the legacy implementation:
    - ``tension > 0.7`` → ``Em Conflito``
    - ``tension > 0.4`` → ``Tenso``
    - ``trust > 0.8`` and ``affection > 0.8`` → ``Alma Gêmea``
    - ``trust > 0.7`` and ``affection > 0.6`` → ``Íntimos``
    - ``trust > 0.5`` and ``affection > 0.4`` → ``Amigos``
    - ``trust < 0.3`` → ``Desconfiada``
    - otherwise → ``Conhecidos``

    This function is pure: no I/O, no global state, no mutation of the input.
    ``bond_label`` is never persisted and never accepted in ``from_dict`` / ``to_dict``.
    """
    if state.tension > 0.7:
        return "Em Conflito"
    if state.tension > 0.4:
        return "Tenso"

    if state.trust > 0.8 and state.affection > 0.8:
        return "Alma Gêmea"
    if state.trust > 0.7 and state.affection > 0.6:
        return "Íntimos"
    if state.trust > 0.5 and state.affection > 0.4:
        return "Amigos"
    if state.trust < 0.3:
        return "Desconfiada"

    return "Conhecidos"


# ─── Migration: legacy snapshot → RelationshipStateV1 ───────────────────────

def migrate_legacy_relationship_snapshot(payload: object) -> RelationshipStateV1:
    """Convert a legacy ``UserRelationship.to_dict()`` payload to ``RelationshipStateV1``.

    Accepts:
    - Legacy format with keys: ``user_id``, ``bond_label``, ``trust``, ``affection``,
      ``tension``, ``triggers``, ``last_interaction``.
    - V1 format with ``schema_version`` == ``RELATIONSHIP_SCHEMA_VERSION`` (idempotent).

    Rules:
    - ``last_interaction`` is mapped to ``timestamp``.
    - ``user_id`` and ``bond_label`` are allowed but NEVER used for identity or classification.
    - Unknown legacy keys are rejected.
    - ``{}`` (empty dict) is NOT accepted as a valid legacy snapshot.
    - The input dict is NOT mutated.
    - Pure function: no I/O, no ``time.time()``.

    Raises
    ------
    RelationshipDomainError
        For any invariant violation.
    """
    if not isinstance(payload, dict):
        raise RelationshipDomainError(
            "migrate_legacy_relationship_snapshot: expected a dict."
        )

    if not payload:
        raise RelationshipDomainError(
            "migrate_legacy_relationship_snapshot: empty dict is not a valid snapshot."
        )

    # Work on a shallow copy to guarantee we do not mutate the input.
    data: Dict[str, object] = dict(payload)

    # ── Check for conflicting timestamp/last_interaction ─────────────────────
    if "last_interaction" in data and "timestamp" in data:
        raise RelationshipDomainError(
            "migrate_legacy_relationship_snapshot: payload contains both "
            "'last_interaction' and 'timestamp'; these are mutually exclusive."
        )

    # ── Determine format from schema_version presence ────────────────────────
    has_schema_version_key = "schema_version" in data

    if has_schema_version_key:
        # Key is present: validate its value strictly.
        sv = data["schema_version"]

        # Reject None explicitly (distinct from "key absent").
        if sv is None:
            raise RelationshipDomainError(
                "migrate_legacy_relationship_snapshot: 'schema_version' is None. "
                "Only absent (legacy) or 1 (v1) are accepted."
            )

        # Reject bool, float, str before int check.
        if isinstance(sv, bool) or not isinstance(sv, int):
            raise RelationshipDomainError(
                "migrate_legacy_relationship_snapshot: 'schema_version' must be an int."
            )

        if sv != RELATIONSHIP_SCHEMA_VERSION:
            raise RelationshipDomainError(
                "migrate_legacy_relationship_snapshot: unsupported schema_version. "
                f"Expected {RELATIONSHIP_SCHEMA_VERSION}."
            )

        # ── Already v1: require exact v1 field set ────────────────────────────
        unknown = set(data.keys()) - _RELATIONSHIP_FIELDS
        if unknown:
            raise RelationshipDomainError(
                "migrate_legacy_relationship_snapshot: v1 snapshot contains unknown fields."
            )
        # 'last_interaction' must not be present in a v1 snapshot.
        if "last_interaction" in data:
            raise RelationshipDomainError(
                "migrate_legacy_relationship_snapshot: v1 snapshot must not "
                "contain 'last_interaction'."
            )
        return RelationshipStateV1.from_dict(data)

    # ── Legacy snapshot: schema_version key is entirely absent ──────────────
    # Reject any field not in the legacy allowlist.
    extra = set(data.keys()) - _LEGACY_ALLOWED_FIELDS
    if extra:
        raise RelationshipDomainError(
            "migrate_legacy_relationship_snapshot: legacy snapshot contains "
            "unexpected fields."
        )

    missing = {"trust", "affection", "tension", "triggers", "last_interaction"} - set(data.keys())
    if missing:
        raise RelationshipDomainError(
            "migrate_legacy_relationship_snapshot: legacy snapshot missing "
            "required fields."
        )

    # Map last_interaction → timestamp.
    # user_id and bond_label are present in the dict but never used for identity.
    timestamp = data["last_interaction"]

    return RelationshipStateV1.create(
        trust=data["trust"],
        affection=data["affection"],
        tension=data["tension"],
        triggers=data["triggers"],
        timestamp=timestamp,
        schema_version=RELATIONSHIP_SCHEMA_VERSION,
    )


# ─── Relationship transition config ──────────────────────────────────────────

@dataclass(frozen=True)
class RelationshipTransitionConfig:
    """Immutable configuration for the relationship transition function.

    Preserves the exact weights and thresholds from the legacy
    ``RelationshipManager.update_relationship()``.

    All numeric fields are validated on construction.
    """

    # Trust thresholds and deltas
    trust_positive_threshold: float = 0.2
    trust_positive_delta: float = 0.02
    trust_negative_threshold: float = -0.3
    trust_negative_delta: float = -0.05

    # Affection thresholds and deltas
    tenderness_threshold: float = 0.3
    tenderness_boost: float = 0.03
    joy_threshold: float = 0.3
    joy_boost: float = 0.01
    gratitude_threshold: float = 0.3
    gratitude_boost: float = 0.02

    # Tension thresholds and deltas
    anger_threshold: float = 0.3
    anger_spike: float = 0.1
    disgust_threshold: float = 0.3
    disgust_spike: float = 0.1
    tension_valence_threshold: float = -0.5
    tension_valence_spike: float = 0.05

    # Reconciliation (positive valence reduces tension)
    reconciliation_valence_threshold: float = 0.3
    reconciliation_delta: float = 0.1  # subtracted from tension

    def __post_init__(self) -> None:
        """Validate all numeric fields."""
        _validate_config_float(self.trust_positive_threshold, "trust_positive_threshold", -1.0, 1.0)
        _validate_config_float(self.trust_positive_delta, "trust_positive_delta", 0.0, 1.0)
        _validate_config_float(self.trust_negative_threshold, "trust_negative_threshold", -1.0, 1.0)
        _validate_config_float(self.trust_negative_delta, "trust_negative_delta", -1.0, 0.0)

        _validate_config_float(self.tenderness_threshold, "tenderness_threshold", 0.0, 1.0)
        _validate_config_float(self.tenderness_boost, "tenderness_boost", 0.0, 1.0)
        _validate_config_float(self.joy_threshold, "joy_threshold", 0.0, 1.0)
        _validate_config_float(self.joy_boost, "joy_boost", 0.0, 1.0)
        _validate_config_float(self.gratitude_threshold, "gratitude_threshold", 0.0, 1.0)
        _validate_config_float(self.gratitude_boost, "gratitude_boost", 0.0, 1.0)

        _validate_config_float(self.anger_threshold, "anger_threshold", 0.0, 1.0)
        _validate_config_float(self.anger_spike, "anger_spike", 0.0, 1.0)
        _validate_config_float(self.disgust_threshold, "disgust_threshold", 0.0, 1.0)
        _validate_config_float(self.disgust_spike, "disgust_spike", 0.0, 1.0)
        _validate_config_float(self.tension_valence_threshold, "tension_valence_threshold", -1.0, 1.0)
        _validate_config_float(self.tension_valence_spike, "tension_valence_spike", 0.0, 1.0)

        _validate_config_float(
            self.reconciliation_valence_threshold,
            "reconciliation_valence_threshold",
            -1.0, 1.0,
        )
        _validate_config_float(
            self.reconciliation_delta,
            "reconciliation_delta",
            0.0, 1.0,
        )

    @classmethod
    def defaults(cls) -> "RelationshipTransitionConfig":
        """Return a default-configured instance."""
        return cls()


def _validate_config_float(raw: object, name: str, lo: float, hi: float) -> None:
    """Validate a config field: must be finite float in [lo, hi].

    Rejects: bool, None, str, list, dict, NaN, Inf, and integers too large
    to convert to float. All failures produce ``RelationshipDomainError``.
    """
    if isinstance(raw, bool):
        raise RelationshipDomainError(
            f"RelationshipTransitionConfig: '{name}' must be a finite float, got bool."
        )
    if not isinstance(raw, (int, float)):
        raise RelationshipDomainError(
            f"RelationshipTransitionConfig: '{name}' must be a finite float, "
            f"got {type(raw).__name__}."
        )
    try:
        f = float(raw)
    except (OverflowError, ValueError, TypeError):
        raise RelationshipDomainError(
            f"RelationshipTransitionConfig: '{name}' is not a finite float value."
        )
    if not math.isfinite(f):
        raise RelationshipDomainError(
            f"RelationshipTransitionConfig: '{name}' must be finite."
        )
    if f < lo or f > hi:
        raise RelationshipDomainError(
            f"RelationshipTransitionConfig: '{name}' must be in [{lo}, {hi}]."
        )


# ─── Clamp helper ────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


# ─── Pure relationship transition ────────────────────────────────────────────

def transition_relationship(
    previous_state: RelationshipStateV1,
    appraisal: AppraisalV1,
    current_time: float,
    config: RelationshipTransitionConfig,
) -> RelationshipStateV1:
    """Pure, deterministic relationship transition.

    Produces a new ``RelationshipStateV1`` based on the given appraisal, without
    modifying the previous state.

    Parameters
    ----------
    previous_state:
        The relationship state before this turn. Never modified.
    appraisal:
        The validated ``AppraisalV1`` for this turn.
    current_time:
        Explicit current time as a finite positive float (Unix epoch seconds).
        Must be >= ``previous_state.timestamp``.
    config:
        ``RelationshipTransitionConfig`` with validated weights and thresholds.

    Returns
    -------
    RelationshipStateV1
        A new immutable snapshot with the updated metrics.

    Raises
    ------
    RelationshipDomainError
        If argument types are wrong, ``current_time`` is invalid, or clock regression
        is detected.
    """
    # ── 0. Validate argument types ──────────────────────────────────────────
    if not isinstance(previous_state, RelationshipStateV1):
        raise RelationshipDomainError(
            "transition_relationship: previous_state must be a RelationshipStateV1 instance."
        )
    if not isinstance(appraisal, AppraisalV1):
        raise RelationshipDomainError(
            "transition_relationship: appraisal must be an AppraisalV1 instance."
        )
    if not isinstance(config, RelationshipTransitionConfig):
        raise RelationshipDomainError(
            "transition_relationship: config must be a RelationshipTransitionConfig instance."
        )

    # ── 1. Validate current_time ────────────────────────────────────────────
    validated_time = _require_current_time(current_time)

    # ── 2. Reject clock regression ──────────────────────────────────────────
    if validated_time < previous_state.timestamp:
        raise RelationshipDomainError(
            "transition_relationship: clock regression detected — current_time is "
            "earlier than previous_state.timestamp."
        )

    # ── 3. Extract appraisal values ─────────────────────────────────────────
    valence = appraisal.valence_shift
    emotions = dict(appraisal.discrete_emotions)

    def get_emo(key: str, default: float = 0.0) -> float:
        return emotions.get(key, default)

    # ── 4. Compute relationship deltas ──────────────────────────────────────

    # Trust
    trust_delta = 0.0
    if valence > config.trust_positive_threshold:
        trust_delta = config.trust_positive_delta
    elif valence < config.trust_negative_threshold:
        trust_delta = config.trust_negative_delta

    new_trust = _clamp(previous_state.trust + trust_delta)

    # Affection
    affection_boost = 0.0
    if get_emo("tenderness") > config.tenderness_threshold:
        affection_boost += config.tenderness_boost
    if get_emo("joy") > config.joy_threshold:
        affection_boost += config.joy_boost
    if get_emo("gratitude") > config.gratitude_threshold:
        affection_boost += config.gratitude_boost

    new_affection = _clamp(previous_state.affection + affection_boost)

    # Tension
    tension_spike = 0.0
    if get_emo("anger") > config.anger_threshold:
        tension_spike += config.anger_spike
    if get_emo("disgust") > config.disgust_threshold:
        tension_spike += config.disgust_spike
    if valence < config.tension_valence_threshold:
        tension_spike += config.tension_valence_spike

    new_tension = _clamp(previous_state.tension + tension_spike)

    # Decay Tension if interaction was positive (Reconciliation)
    if (
        valence > config.reconciliation_valence_threshold
        and new_tension > 0
    ):
        new_tension = _clamp(new_tension - config.reconciliation_delta)

    # ── 5. Build new state — preserve triggers ──────────────────────────────
    return RelationshipStateV1.create(
        trust=new_trust,
        affection=new_affection,
        tension=new_tension,
        triggers=previous_state.triggers,
        timestamp=validated_time,
        schema_version=RELATIONSHIP_SCHEMA_VERSION,
    )
