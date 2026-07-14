"""
LLM appraisal parser: converts unvalidated LLM output to AppraisalV1 or
returns the neutral fallback.

Design
======
LLM output is untrusted. This module provides a single public function
``parse_llm_appraisal`` that:

1. Accepts any object (the raw LLM-produced dict).
2. Validates structure against an explicit top-level allowlist.
3. Translates legacy production keys to v1 keys.
4. Requires all three shift fields to be present and valid.
5. On ANY validation failure, returns ``AppraisalV1.neutral()`` with an
   observable, sanitised error code — never raw LLM/user text.

Fallback codes
==============
``ParseErrorCode`` is an enum of stable codes:

- ``invalid_structure``       — not a dict, or structurally malformed
- ``unknown_top_level_key``   — dict contains key not in the allowlist
- ``missing_required_field``  — a shift field is absent
- ``conflicting_aliases``     — both alias and canonical name present with different values
- ``invalid_numeric_value``   — bad type, NaN/Inf, or out-of-range shift/intensity
- ``unsupported_emotion``     — discrete_emotions present but not a mapping
- ``unexpected_parser_failure`` — anything not covered by the above

Legacy key translation (explicit, tested)
==========================================
The current production format uses:
  ``valence``            → ``valence_shift``
  ``arousal_shift``      → ``arousal_shift``  (unchanged)
  ``dominance_shift``    → ``dominance_shift`` (unchanged)
  ``triggered_emotions`` → ``discrete_emotions``

If both alias and canonical name are present with *the same* value, the
canonical is used. If they are present with *different* values, the parser
produces ``conflicting_aliases`` fallback.

Top-level key allowlist
=======================
Only the following keys are accepted at the top level of the raw dict::

  valence, valence_shift, arousal_shift, dominance_shift,
  triggered_emotions, discrete_emotions

Any other key triggers ``unknown_top_level_key`` fallback.

Empty-dict policy
=================
An empty dict ``{}`` is NOT a valid appraisal. It produces a fallback with
code ``missing_required_field`` because the shift fields are absent.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    DISCRETE_EMOTIONS,
    AppraisalV1,
    EmotionalDomainError,
    _require_finite_float_in_range,
)


# ─── Fallback error codes ────────────────────────────────────────────────────

class ParseErrorCode(str, enum.Enum):
    """
    Stable, sanitised error codes for ``ParseResult.error_code``.

    These codes are safe to log and expose to callers. They contain no
    raw LLM output, no user content, and no exception text.
    """
    invalid_structure = "invalid_structure"
    unknown_top_level_key = "unknown_top_level_key"
    missing_required_field = "missing_required_field"
    conflicting_aliases = "conflicting_aliases"
    invalid_numeric_value = "invalid_numeric_value"
    unsupported_emotion = "unsupported_emotion"
    unexpected_parser_failure = "unexpected_parser_failure"


# ─── ParseResult ─────────────────────────────────────────────────────────────

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
    error_code:
        A ``ParseErrorCode`` value when ``is_fallback`` is ``True``; ``None``
        otherwise. Never contains raw LLM text, user content, or exception repr.
    """
    appraisal: AppraisalV1
    is_fallback: bool
    error_code: Optional[ParseErrorCode]


# ─── Top-level key allowlist ─────────────────────────────────────────────────

_ALLOWED_TOP_LEVEL_KEYS = frozenset({
    # Canonical v1 names
    "valence_shift",
    "arousal_shift",
    "dominance_shift",
    "discrete_emotions",
    # Legacy production aliases
    "valence",
    "triggered_emotions",
})

# Required shift keys (canonical names, post-translation).
_REQUIRED_SHIFTS = frozenset({"valence_shift", "arousal_shift", "dominance_shift"})


# ─── Public API ──────────────────────────────────────────────────────────────

def parse_llm_appraisal(raw: Any) -> ParseResult:
    """
    Parse untrusted LLM output into an ``AppraisalV1``.

    On any error, returns a ``ParseResult`` with ``is_fallback=True`` and a
    stable ``ParseErrorCode`` in ``error_code``. Never raises.
    """
    try:
        return _do_parse(raw)
    except _ParserFailure as exc:
        return ParseResult(
            appraisal=AppraisalV1.neutral(),
            is_fallback=True,
            error_code=exc.code,
        )
    except EmotionalDomainError:
        # Domain validation errors — map to a known code.
        return ParseResult(
            appraisal=AppraisalV1.neutral(),
            is_fallback=True,
            error_code=ParseErrorCode.invalid_numeric_value,
        )
    except Exception:  # noqa: BLE001
        return ParseResult(
            appraisal=AppraisalV1.neutral(),
            is_fallback=True,
            error_code=ParseErrorCode.unexpected_parser_failure,
        )


# ─── Internal helpers ────────────────────────────────────────────────────────

_ABSENT = object()  # Sentinel: discrete_emotions key was not in the dict.

class _ParserFailure(Exception):
    """Internal exception carrying a ParseErrorCode. Never surfaces to callers."""
    def __init__(self, code: ParseErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def _do_parse(raw: Any) -> ParseResult:
    # 1. Must be a dict.
    if not isinstance(raw, dict):
        raise _ParserFailure(ParseErrorCode.invalid_structure)

    # 2. Reject unknown top-level keys.
    unknown_keys = set(raw.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown_keys:
        raise _ParserFailure(ParseErrorCode.unknown_top_level_key)

    # 3. Translate legacy aliases → canonical names, checking for conflicts.
    translated = _translate_aliases(raw)

    # 4. All three shift fields must be present.
    missing = _REQUIRED_SHIFTS - set(translated.keys())
    if missing:
        raise _ParserFailure(ParseErrorCode.missing_required_field)

    # 5. Validate and extract shift values.
    try:
        valence_shift = _require_finite_float_in_range(
            translated["valence_shift"], "valence_shift", -1.0, 1.0
        )
        arousal_shift = _require_finite_float_in_range(
            translated["arousal_shift"], "arousal_shift", -1.0, 1.0
        )
        dominance_shift = _require_finite_float_in_range(
            translated["dominance_shift"], "dominance_shift", -1.0, 1.0
        )
    except EmotionalDomainError:
        raise _ParserFailure(ParseErrorCode.invalid_numeric_value)

    # 6. Process discrete_emotions.
    # Use sentinel to distinguish key-absent from key-present-but-None.
    de_raw = translated.get("discrete_emotions", _ABSENT)
    filtered_emotions = _parse_discrete_emotions(de_raw)

    # 7. Construct the validated AppraisalV1.
    appraisal = AppraisalV1.create(
        valence_shift=valence_shift,
        arousal_shift=arousal_shift,
        dominance_shift=dominance_shift,
        discrete_emotions=filtered_emotions,
        schema_version=EMOTIONAL_SCHEMA_VERSION,
    )

    return ParseResult(appraisal=appraisal, is_fallback=False, error_code=None)


def _translate_aliases(raw: dict) -> dict:
    """
    Translate legacy production keys to canonical v1 keys.

    Alias pairs handled:
      ``valence``            ↔ ``valence_shift``
      ``triggered_emotions`` ↔ ``discrete_emotions``

    Conflict policy:
      If both alias and canonical key are present AND their values differ,
      raise ``_ParserFailure(conflicting_aliases)``.
      If they are the same value (or only one is present), use the canonical.
    """
    result = dict(raw)

    # valence / valence_shift
    has_alias = "valence" in raw
    has_canonical = "valence_shift" in raw
    if has_alias and has_canonical:
        if raw["valence"] != raw["valence_shift"]:
            raise _ParserFailure(ParseErrorCode.conflicting_aliases)
        # Same value — drop alias, keep canonical
        result.pop("valence", None)
    elif has_alias:
        result["valence_shift"] = result.pop("valence")

    # triggered_emotions / discrete_emotions
    has_alias_te = "triggered_emotions" in raw
    has_canonical_de = "discrete_emotions" in raw
    if has_alias_te and has_canonical_de:
        if raw["triggered_emotions"] != raw["discrete_emotions"]:
            raise _ParserFailure(ParseErrorCode.conflicting_aliases)
        result.pop("triggered_emotions", None)
    elif has_alias_te:
        result["discrete_emotions"] = result.pop("triggered_emotions")

    return result


def _parse_discrete_emotions(de_raw: Any) -> Dict[str, float]:
    """
    Parse and filter the discrete_emotions mapping from LLM output.

    - If absent (sentinel _ABSENT): return empty dict (key was not in the payload).
    - If explicitly None, str, list, number, bool, or any non-mapping type:
      raise _ParserFailure(unsupported_emotion).
    - If a mapping: filter unknown emotion keys silently (LLM may produce extras),
      validate intensities strictly.
    """
    if de_raw is _ABSENT:
        # Key was entirely absent from the raw dict — treat as empty.
        return {}

    # Explicitly reject non-mapping types, including None.
    if isinstance(de_raw, bool) or not isinstance(de_raw, dict):
        raise _ParserFailure(ParseErrorCode.unsupported_emotion)

    # Filter: keep only known emotions; validate intensities.
    result: Dict[str, float] = {}
    for k, v in de_raw.items():
        if not isinstance(k, str):
            raise _ParserFailure(ParseErrorCode.unsupported_emotion)
        if k not in DISCRETE_EMOTIONS:
            # Unknown emotions from LLM are silently filtered.
            continue
        try:
            result[k] = _require_finite_float_in_range(
                v, f"discrete_emotions['{k}']", 0.0, 1.0
            )
        except EmotionalDomainError:
            raise _ParserFailure(ParseErrorCode.invalid_numeric_value)

    return result
