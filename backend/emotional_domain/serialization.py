"""
Stable JSON serialization and deserialization for domain models.

Guarantees
==========
- Output always includes ``schema_version``.
- Output contains only public domain fields (no prompt, metacognition, etc.).
- Format is deterministic (sorted keys).
- Round-trip: deserialise(serialise(obj)) produces an equivalent object.
"""

from __future__ import annotations

import json

from .models import EmotionalStateV1, AppraisalV1, EmotionalDomainError


def serialize_state(state: EmotionalStateV1) -> str:
    """
    Serialise an ``EmotionalStateV1`` to a deterministic JSON string.

    Parameters
    ----------
    state:
        A valid ``EmotionalStateV1`` instance.

    Returns
    -------
    str
        JSON-encoded string with sorted keys.
    """
    if not isinstance(state, EmotionalStateV1):
        raise EmotionalDomainError(
            f"serialize_state: expected EmotionalStateV1, got {type(state).__name__}."
        )
    return json.dumps(state.to_dict(), sort_keys=True)


def deserialize_state(payload: str) -> EmotionalStateV1:
    """
    Deserialise a JSON string produced by ``serialize_state`` back to
    ``EmotionalStateV1``.

    Raises
    ------
    EmotionalDomainError
        If the JSON is malformed or the payload violates any invariant.
    """
    if not isinstance(payload, str):
        raise EmotionalDomainError(
            f"deserialize_state: expected a str, got {type(payload).__name__}."
        )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EmotionalDomainError(
            f"deserialize_state: invalid JSON — {exc}."
        ) from exc

    return EmotionalStateV1.from_dict(data)


def serialize_appraisal(appraisal: AppraisalV1) -> str:
    """
    Serialise an ``AppraisalV1`` to a deterministic JSON string.
    """
    if not isinstance(appraisal, AppraisalV1):
        raise EmotionalDomainError(
            f"serialize_appraisal: expected AppraisalV1, got {type(appraisal).__name__}."
        )
    return json.dumps(appraisal.to_dict(), sort_keys=True)


def deserialize_appraisal(payload: str) -> AppraisalV1:
    """
    Deserialise a JSON string produced by ``serialize_appraisal`` back to
    ``AppraisalV1``.

    Raises
    ------
    EmotionalDomainError
        If the JSON is malformed or the payload violates any invariant.
    """
    if not isinstance(payload, str):
        raise EmotionalDomainError(
            f"deserialize_appraisal: expected a str, got {type(payload).__name__}."
        )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EmotionalDomainError(
            f"deserialize_appraisal: invalid JSON — {exc}."
        ) from exc

    return AppraisalV1.from_dict(data)
