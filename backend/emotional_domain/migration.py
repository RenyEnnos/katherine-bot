"""
Migration utilities: legacy snapshot → EmotionalStateV1.

The legacy snapshot is the dict produced by the current ``EmotionalState.to_dict()``
which uses the field ``last_update`` (a float Unix epoch) instead of ``timestamp``,
and has no ``schema_version`` key.

Migration policy
================
- Accepts EXACTLY the legacy structure: no extra keys, no ``schema_version`` key.
- Rejects: non-dict, missing required legacy fields, any extra/unknown field.
- Rejects: ``schema_version=None`` (None is treated as an explicitly invalid version,
  not as "absent"; absent means the key is not in the dict at all).
- Rejects: payload containing both ``last_update`` and ``timestamp`` simultaneously.
- Rejects: fields from other layers (prompt, memory, relationship, presentation).
- Returns a new ``EmotionalStateV1`` with ``schema_version=1``.
- Does NOT modify the input dict.

V1 idempotent path
==================
If ``schema_version`` is present and equals ``EMOTIONAL_SCHEMA_VERSION``:
- Requires exactly the v1 field set (no legacy-only fields, no extras).
- Delegates to ``EmotionalStateV1.from_dict`` for strict validation.

Any other ``schema_version`` value (including None) is rejected.

Legacy required fields (exactly)
=================================
  pleasure, arousal, dominance, libido, aggression, connection,
  energy, tension, coping_mode, last_update
"""

from __future__ import annotations

from typing import Dict

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    _STATE_FIELDS,
    EmotionalStateV1,
    EmotionalDomainError,
)

# Exactly the fields a legacy snapshot may contain (no schema_version, uses last_update).
_LEGACY_EXACT_FIELDS = frozenset({
    "pleasure",
    "arousal",
    "dominance",
    "libido",
    "aggression",
    "connection",
    "energy",
    "tension",
    "coping_mode",
    "last_update",
})


def migrate_legacy_snapshot(raw: object) -> EmotionalStateV1:
    """
    Convert a legacy ``EmotionalState.to_dict()`` payload to ``EmotionalStateV1``.

    Parameters
    ----------
    raw:
        The raw dict as loaded from persistent storage.

    Returns
    -------
    EmotionalStateV1
        A fully validated v1 snapshot.

    Raises
    ------
    EmotionalDomainError
        For any of the following:
        - Not a dict.
        - ``schema_version`` key is present but its value is ``None``.
        - ``schema_version`` key is present with an unsupported version.
        - Both ``last_update`` and ``timestamp`` present simultaneously.
        - Missing required fields for the detected format.
        - Extra/unknown keys beyond the allowed set for the detected format.
        - Any field value that violates an invariant.
    """
    if not isinstance(raw, dict):
        raise EmotionalDomainError(
            "migrate_legacy_snapshot: expected a dict."
        )

    # Work on a shallow copy to guarantee we do not mutate the input.
    data: Dict[str, object] = dict(raw)

    # ── Check for conflicting timestamp/last_update ───────────────────────────
    if "last_update" in data and "timestamp" in data:
        raise EmotionalDomainError(
            "migrate_legacy_snapshot: payload contains both 'last_update' and "
            "'timestamp'; these are mutually exclusive."
        )

    # ── Determine format from schema_version presence ─────────────────────────
    has_schema_version_key = "schema_version" in data

    if has_schema_version_key:
        # Key is present: validate its value strictly.
        sv = data["schema_version"]

        # Reject None explicitly (distinct from "key absent").
        if sv is None:
            raise EmotionalDomainError(
                "migrate_legacy_snapshot: 'schema_version' is None. "
                "Only absent (legacy) or 1 (v1) are accepted."
            )

        # Reject bool, float, str before int check.
        if isinstance(sv, bool) or not isinstance(sv, int):
            raise EmotionalDomainError(
                "migrate_legacy_snapshot: 'schema_version' must be an int."
            )

        if sv != EMOTIONAL_SCHEMA_VERSION:
            raise EmotionalDomainError(
                "migrate_legacy_snapshot: unsupported schema_version. "
                f"Expected {EMOTIONAL_SCHEMA_VERSION}."
            )

        # ── Already v1: require exact v1 field set ────────────────────────────
        unknown = set(data.keys()) - _STATE_FIELDS
        if unknown:
            raise EmotionalDomainError(
                "migrate_legacy_snapshot: v1 snapshot contains unknown fields."
            )
        # 'last_update' must not be present in a v1 snapshot.
        if "last_update" in data:
            raise EmotionalDomainError(
                "migrate_legacy_snapshot: v1 snapshot must not contain 'last_update'."
            )
        return EmotionalStateV1.from_dict(data)

    # ── Legacy snapshot: schema_version key is entirely absent ────────────────
    # Reject any field not in the legacy allowlist.
    extra = set(data.keys()) - _LEGACY_EXACT_FIELDS
    if extra:
        raise EmotionalDomainError(
            "migrate_legacy_snapshot: legacy snapshot contains unexpected fields."
        )

    missing = _LEGACY_EXACT_FIELDS - set(data.keys())
    if missing:
        raise EmotionalDomainError(
            "migrate_legacy_snapshot: legacy snapshot missing required fields."
        )

    # Map last_update → timestamp.
    timestamp = data["last_update"]

    return EmotionalStateV1.create(
        pleasure=data["pleasure"],
        arousal=data["arousal"],
        dominance=data["dominance"],
        libido=data["libido"],
        aggression=data["aggression"],
        connection=data["connection"],
        energy=data["energy"],
        tension=data["tension"],
        coping_mode=data["coping_mode"],
        timestamp=timestamp,
        schema_version=EMOTIONAL_SCHEMA_VERSION,
    )
