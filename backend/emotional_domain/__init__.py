"""
Emotional domain models — pure, typed, versioned, infrastructure-free.

This package defines the typed contracts for:
- EmotionalStateV1: versioned emotional snapshot
- AppraisalV1: versioned appraisal of messages/events
- Migration utilities for legacy snapshots
- Serialization helpers
- LLM appraisal parser with explicit fallback
- Transition (decay, appraisal shift, tension, coping regulation)

No FastAPI, Groq, Supabase, sentence_transformers, or I/O allowed here.
"""

from .models import (
    EMOTIONAL_SCHEMA_VERSION,
    VALID_COPING_MODES,
    DISCRETE_EMOTIONS,
    EmotionalStateV1,
    AppraisalV1,
    EmotionalDomainError,
)
from .migration import migrate_legacy_snapshot
from .serialization import serialize_state, deserialize_state, serialize_appraisal, deserialize_appraisal
from .appraisal_parser import parse_llm_appraisal, ParseResult, ParseErrorCode
from .transition import (
    TransitionConfig,
    RegulationResult,
    RegulationReason,
    TransitionResult,
    transition,
)

__all__ = [
    "EMOTIONAL_SCHEMA_VERSION",
    "VALID_COPING_MODES",
    "DISCRETE_EMOTIONS",
    "EmotionalStateV1",
    "AppraisalV1",
    "EmotionalDomainError",
    "migrate_legacy_snapshot",
    "serialize_state",
    "deserialize_state",
    "serialize_appraisal",
    "deserialize_appraisal",
    "parse_llm_appraisal",
    "ParseResult",
    "ParseErrorCode",
    "TransitionConfig",
    "RegulationResult",
    "RegulationReason",
    "TransitionResult",
    "transition",
]
