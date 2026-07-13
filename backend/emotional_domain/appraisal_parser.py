"""
LLM appraisal parser: converts unvalidated LLM output to AppraisalV1 or
returns the neutral fallback.

Design
======
LLM output is untrusted. This module provides a single public function
``parse_llm_appraisal`` that:

1. Accepts any object (the raw LLM-produced dict).
2. Attempts to parse it as an AppraisalV1.
3. On ANY validation failure, returns ``AppraisalV1.neutral()`` and
   **does not propagate the exception** (fallback policy).

The fallback is explicit and observable: callers receive a neutral appraisal
rather than a silent empty dict or a bare exception that could be swallowed.

A companion ``ParseResult`` is returned so callers can distinguish
"parsed successfully" from "fell back to neutral" for observability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    DISCRETE_EMOTIONS,
    AppraisalV1,
    EmotionalDomainError,
)


@dataclass(frozen=True)
class ParseResult:
    """
    Result of ``parse_llm_appraisal``.

    Attributes
    ----------
    appraisal:
        The parsed ``AppraisalV1``, or ``AppraisalV1.neutral()`` on failure.
    is_fallback:
        ``True`` when the neutral fallback was used.
    error:
        The error message when ``is_fallback`` is ``True``; ``None`` otherwise.
    """
    appraisal: AppraisalV1
    is_fallback: bool
    error: Optional[str]


def parse_llm_appraisal(raw: Any) -> ParseResult:
    """
    Parse untrusted LLM output into an ``AppraisalV1``.

    The LLM output is expected to be a dict with keys compatible with the
    informal ``perception_override`` format used in ``AffectiveEngine``:
      - ``valence`` or ``valence_shift`` → ``valence_shift``
      - ``arousal_shift``                → ``arousal_shift``
      - ``dominance_shift``              → ``dominance_shift``
      - ``discrete_emotions``            → ``discrete_emotions`` (optional)

    On any error, returns a ``ParseResult`` with ``is_fallback=True`` and
    ``appraisal=AppraisalV1.neutral()``. The error is recorded in
    ``ParseResult.error``.

    This function never raises.
    """
    try:
        return _do_parse(raw)
    except Exception as exc:  # noqa: BLE001  (intentional broad catch for LLM safety)
        return ParseResult(
            appraisal=AppraisalV1.neutral(),
            is_fallback=True,
            error=str(exc),
        )


# ─── Internal helpers ────────────────────────────────────────────────────────

def _do_parse(raw: Any) -> ParseResult:
    if not isinstance(raw, dict):
        raise EmotionalDomainError(
            f"LLM appraisal must be a dict, got {type(raw).__name__}."
        )

    # Support the legacy key name "valence" as well as "valence_shift".
    valence_shift = raw.get("valence_shift", raw.get("valence", 0.0))
    arousal_shift = raw.get("arousal_shift", 0.0)
    dominance_shift = raw.get("dominance_shift", 0.0)

    raw_emotions = raw.get("discrete_emotions", {})

    # Filter discrete_emotions: silently drop unknown keys (LLM output may be
    # verbose), but reject invalid intensity values.
    # Note: this is different from AppraisalV1.create() which REJECTS unknown
    # emotion keys. Here we FILTER them from untrusted LLM output.
    filtered_emotions: Dict[str, float] = {}
    if isinstance(raw_emotions, dict):
        for k, v in raw_emotions.items():
            if not isinstance(k, str):
                raise EmotionalDomainError(
                    f"Emotion key must be a str, got {type(k).__name__}."
                )
            if k not in DISCRETE_EMOTIONS:
                # Silently skip unknown emotions from LLM output.
                continue
            filtered_emotions[k] = v  # will be validated by AppraisalV1.create

    appraisal = AppraisalV1.create(
        valence_shift=valence_shift,
        arousal_shift=arousal_shift,
        dominance_shift=dominance_shift,
        discrete_emotions=filtered_emotions,
        schema_version=EMOTIONAL_SCHEMA_VERSION,
    )

    return ParseResult(appraisal=appraisal, is_fallback=False, error=None)
