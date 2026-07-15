"""
Public emotion presentation — typed, versioned DTO for external API consumers.

This module is the **only** place where the public emotion contract is defined.
It produces ``EmotionStateResponse`` which is safe to send to the browser.

Design rules
============
- Pure: no I/O, no FastAPI, no Supabase, no Groq, no network, no env vars.
- Receives only validated ``EmotionalStateV1`` and ``AppraisalV1``.
- Does NOT access persistence, relationship, memory, meta-cognition.
- Does NOT execute transition, coping, or appraisal.
- ``classify_pad_mood`` is the shared mood classification used by the public DTO
  AND by the internal prompt builder (``AffectiveEngine.get_emotional_label``
  delegates to this function). There is only one classifier.
"""

from __future__ import annotations

import math
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .emotional_domain.models import (
    EmotionalStateV1,
    AppraisalV1,
    EmotionalDomainError,
    DISCRETE_EMOTIONS,
)


# ─── Schema version ──────────────────────────────────────────────────────────

PUBLIC_EMOTION_SCHEMA_VERSION: int = 1


# ─── Shared mood classification (single classifier) ──────────────────────────

def classify_pad_mood(pleasure: float, arousal: float, dominance: float) -> str:
    """Classify PAD coordinates into a human-readable mood label.

    This is the single shared classifier used by both:
    - The public DTO (``EmotionStateResponse.mood_label``)
    - The internal prompt builder (``AffectiveEngine.get_emotional_label``)
    """
    if arousal > 0.5:
        if pleasure > 0.5:
            if dominance > 0.3:
                return "EXTASE/DOMINANTE"
            if dominance < -0.3:
                return "ENCANTADA"
            return "ALEGRE/EXCITADA"
        elif pleasure < -0.5:
            if dominance > 0.3:
                return "FURIA/ODIO"
            if dominance < -0.3:
                return "TERROR/PANICO"
            return "ESTRESSE/AGONIA"
    else:
        if pleasure > 0.5:
            return "RELAXADA/SATISFEITA"
        elif pleasure < -0.5:
            if dominance > 0.3:
                return "DESPREZO/FRIO"
            if dominance < -0.3:
                return "DEPRESSAO/TRISTEZA"
            return "TEDIO"

    return "NEUTRA"


# ─── Public DTO models ───────────────────────────────────────────────────────

class PublicPAD(BaseModel):
    """Pleasure-Arousal-Dominance in bipolar [-1.0, 1.0] scale."""

    model_config = ConfigDict(extra="forbid")

    pleasure: float = Field(..., ge=-1.0, le=1.0)
    arousal: float = Field(..., ge=-1.0, le=1.0)
    dominance: float = Field(..., ge=-1.0, le=1.0)

    @field_validator("pleasure", "arousal", "dominance", mode="before")
    @classmethod
    def _reject_non_finite(cls, value: object) -> float:
        if isinstance(value, bool):
            raise ValueError("PAD fields must be finite floats, got bool.")
        if not isinstance(value, (int, float)):
            raise ValueError(f"PAD fields must be finite floats, got {type(value).__name__}.")
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("PAD fields must be finite floats, got non-finite value.")
        return f


class PublicDominantEmotion(BaseModel):
    """A single discrete emotion with its intensity.

    ``name`` must be a canonical emotion from ``DISCRETE_EMOTIONS`` allowlist.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    intensity: float = Field(..., ge=0.0, le=1.0)

    @field_validator("name", mode="before")
    @classmethod
    def _validate_emotion_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError(f"Emotion name must be a string, got {type(value).__name__}.")
        if value not in DISCRETE_EMOTIONS:
            raise ValueError(
                f"Emotion name must be one of {sorted(DISCRETE_EMOTIONS)}, got {value!r}."
            )
        return value

    @field_validator("intensity", mode="before")
    @classmethod
    def _reject_non_finite(cls, value: object) -> float:
        if isinstance(value, bool):
            raise ValueError("Intensity must be a finite float, got bool.")
        if not isinstance(value, (int, float)):
            raise ValueError(f"Intensity must be a finite float, got {type(value).__name__}.")
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("Intensity must be finite.")
        return f


class EmotionStateResponse(BaseModel):
    """Public emotion state sent to the frontend.

    This is the **only** emotion payload the browser should see. It contains
    no internal state, no coping mode, no acting instruction, no drives, and
    no relationship data.

    All fields are required at construction time. Validators enforce:
    - ``schema_version`` must be 1 (int, not bool/float/str).
    - ``dominant_emotions`` limited to 3 elements.
    - Each emotion name must be in ``DISCRETE_EMOTIONS`` allowlist.
    - ``timestamp`` must be a finite positive float.
    - ``extra`` fields are forbidden on all nested models.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        ..., ge=1, le=1, description="Must be 1. Only version 1 is accepted."
    )
    mood_label: str = Field(..., min_length=1)
    pad: PublicPAD
    dominant_emotions: List[PublicDominantEmotion] = Field(
        ..., description="At most 3 emotions, sorted by intensity desc then name asc."
    )
    timestamp: float = Field(
        ..., description="Unix epoch seconds from EmotionalStateV1.timestamp."
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def _validate_schema_version(cls, value: object) -> int:
        if value is None or isinstance(value, bool):
            raise ValueError("schema_version must be int 1.")
        if not isinstance(value, int):
            raise ValueError(f"schema_version must be int, got {type(value).__name__}.")
        if value != 1:
            raise ValueError(f"schema_version must be 1, got {value}.")
        return value

    @field_validator("dominant_emotions", mode="after")
    @classmethod
    def _limit_to_three(cls, value: List[PublicDominantEmotion]) -> List[PublicDominantEmotion]:
        if len(value) > 3:
            raise ValueError("At most 3 dominant emotions are allowed per the public contract.")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def _reject_non_finite_timestamp(cls, value: object) -> float:
        if isinstance(value, bool):
            raise ValueError("Timestamp must be a finite positive float, got bool.")
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"Timestamp must be a finite positive float, got {type(value).__name__}."
            )
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("Timestamp must be finite.")
        if f <= 0:
            raise ValueError("Timestamp must be positive (Unix epoch seconds).")
        return f


# ─── Public projection ───────────────────────────────────────────────────────

def project_public_emotion(
    state: EmotionalStateV1,
    appraisal: AppraisalV1,
) -> EmotionStateResponse:
    """Project an ``EmotionalStateV1`` and ``AppraisalV1`` into the public DTO.

    This function:
    - Derives ``mood_label`` from PAD via ``classify_pad_mood``.
    - Extracts ``dominant_emotions`` from the validated appraisal.
    - Filters zero-intensity emotions.
    - Sorts by intensity descending, then name ascending for ties.
    - Limits to at most 3 items.
    - Preserves timestamp from the state's timestamp.

    It does NOT mutate either input.
    """
    # 1. Mood label from PAD
    mood_label = classify_pad_mood(state.pleasure, state.arousal, state.dominance)

    # 2. Build PublicPAD
    pad = PublicPAD(
        pleasure=state.pleasure,
        arousal=state.arousal,
        dominance=state.dominance,
    )

    # 3. Build dominant_emotions from appraisal
    raw_emotions = []
    for name, intensity in appraisal.discrete_emotions.items():
        if intensity > 0.0:
            raw_emotions.append((name, intensity))

    # Sort: intensity descending, then name ascending for ties
    raw_emotions.sort(key=lambda x: (-x[1], x[0]))

    # Limit to at most 3
    raw_emotions = raw_emotions[:3]

    dominant_emotions = [
        PublicDominantEmotion(name=name, intensity=intensity)
        for name, intensity in raw_emotions
    ]

    # 4. Build response
    return EmotionStateResponse(
        schema_version=PUBLIC_EMOTION_SCHEMA_VERSION,
        mood_label=mood_label,
        pad=pad,
        dominant_emotions=dominant_emotions,
        timestamp=state.timestamp,
    )
