"""
Migration utilities: legacy snapshot → EmotionalStateV1.

The legacy snapshot is the dict produced by the current ``EmotionalState.to_dict()``
which uses the field ``last_update`` (a float Unix epoch) instead of ``timestamp``,
and has no ``schema_version``.

Migration policy
================
- Accepts a dict with the legacy structure (no ``schema_version`` key OR
  ``schema_version`` absent entirely).
- Rejects: non-dict, missing required legacy fields, incompatible types.
- Returns a new ``EmotionalStateV1`` with ``schema_version=1``.
- Does NOT modify the input dict.
- Idempotent when given a v1 snapshot (re-validates and returns equivalent object).

Legacy required fields
======================
  pleasure, arousal, dominance, libido, aggression, connection,
  energy, tension, coping_mode, last_update
"""

from __future__ import annotations

import copy
from typing import Dict

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    EmotionalStateV1,
    EmotionalDomainError,
)

# Fields that must exist in a legacy snapshot (no schema_version).
_LEGACY_REQUIRED_FIELDS = frozenset({
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
        The raw dict as loaded from persistent storage. Must be a dict;
        must contain the legacy fields; must NOT already be v1 (or if it is,
        it is re-validated and returned as-is).

    Returns
    -------
    EmotionalStateV1
        A fully validated v1 snapshot.

    Raises
    ------
    EmotionalDomainError
        If the payload is incompatible, missing required fields, or contains
        structurally invalid values.
    """
    if not isinstance(raw, dict):
        raise EmotionalDomainError(
            f"migrate_legacy_snapshot: expected a dict, got {type(raw).__name__}."
        )

    # Work on a shallow copy to guarantee we do not mutate the input.
    data: Dict[str, object] = dict(raw)

    schema_version = data.get("schema_version")

    # ── Already v1: re-validate and return ───────────────────────────────────
    if schema_version is not None:
        if schema_version != EMOTIONAL_SCHEMA_VERSION:
            raise EmotionalDomainError(
                f"migrate_legacy_snapshot: snapshot has schema_version "
                f"{schema_version!r}, which is not supported. "
                f"Expected {EMOTIONAL_SCHEMA_VERSION} or absent (legacy)."
            )
        # Re-validate via from_dict (which rejects unknown keys, etc.).
        return EmotionalStateV1.from_dict(data)

    # ── Legacy snapshot (no schema_version) ──────────────────────────────────
    missing = _LEGACY_REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise EmotionalDomainError(
            f"migrate_legacy_snapshot: legacy snapshot missing required fields: "
            f"{sorted(missing)}."
        )

    # Map last_update → timestamp
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
