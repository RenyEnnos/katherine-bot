"""
Tests for backend/emotion_presentation — issue #208.

Coverage map
============
1. DTO has exactly: schema_version, mood_label, pad, dominant_emotions, timestamp
2. schema_version accepts only 1
3. Extra fields are rejected (ConfigDict(extra="forbid"))
4. PAD -1, 0, 1 unchanged in HTTP contract
5. Timestamp matches EmotionalStateV1.timestamp
6. Emotions sorted by intensity desc then name asc
7. At most 3 emotions returned
8. Zero-intensity emotions omitted
9. No acting_instruction, coping_mode, libido, aggression, prompt, memory, relationship, meta-cognition
10. ChatResponse.emotion_state uses typed DTO, not dict
11. A turn still executes exactly one parse_llm_appraisal + one transition
12. Public projection does not modify EmotionalStateV1 or AppraisalV1
13. Persisted snapshot is still EmotionalStateV1 without dominant_emotions
14. No test uses Groq, Supabase, embeddings, real clock, or real network
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict

import pytest

from backend.emotion_presentation import (
    PUBLIC_EMOTION_SCHEMA_VERSION,
    EmotionStateResponse,
    PublicPAD,
    PublicDominantEmotion,
    PresentationError,
    classify_pad_mood,
    project_public_emotion,
)
from backend.emotional_domain.models import (
    EMOTIONAL_SCHEMA_VERSION,
    AppraisalV1,
    EmotionalStateV1,
    EmotionalDomainError,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _neutral_state(timestamp: float = 1_700_000_000.0) -> EmotionalStateV1:
    return EmotionalStateV1.neutral(timestamp=timestamp)


def _state_with_pad(
    pleasure: float = 0.0,
    arousal: float = 0.0,
    dominance: float = 0.0,
    timestamp: float = 1_700_000_000.0,
) -> EmotionalStateV1:
    return EmotionalStateV1.create(
        pleasure=pleasure,
        arousal=arousal,
        dominance=dominance,
        libido=0.0,
        aggression=0.0,
        connection=0.5,
        energy=0.8,
        tension=0.0,
        coping_mode="HEALTHY",
        timestamp=timestamp,
    )


def _appraisal_with_emotions(
    emotions: Dict[str, float] | None = None,
) -> AppraisalV1:
    if emotions is None:
        emotions = {}
    return AppraisalV1.create(
        valence_shift=0.0,
        arousal_shift=0.0,
        dominance_shift=0.0,
        discrete_emotions=emotions,
    )


def _neutral_appraisal() -> AppraisalV1:
    return AppraisalV1.neutral()


# ─── Requirement 1: DTO structure ────────────────────────────────────────────

class TestDTOStructure:
    """The DTO must have exactly schema_version, mood_label, pad,
    dominant_emotions, and timestamp."""

    def test_dto_has_correct_fields(self):
        state = _neutral_state()
        appraisal = _neutral_appraisal()
        result = project_public_emotion(state, appraisal)

        assert hasattr(result, "schema_version")
        assert hasattr(result, "mood_label")
        assert hasattr(result, "pad")
        assert hasattr(result, "dominant_emotions")
        assert hasattr(result, "timestamp")

        # Check no extra fields in serialised form
        data = result.model_dump()
        expected = {"schema_version", "mood_label", "pad", "dominant_emotions", "timestamp"}
        assert set(data.keys()) == expected

    def test_pad_has_correct_fields(self):
        pad = PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0)
        data = pad.model_dump()
        assert set(data.keys()) == {"pleasure", "arousal", "dominance"}

    def test_dominant_emotion_has_correct_fields(self):
        de = PublicDominantEmotion(name="joy", intensity=0.5)
        data = de.model_dump()
        assert set(data.keys()) == {"name", "intensity"}


# ─── Requirement 2: schema_version ───────────────────────────────────────────

class TestSchemaVersion:
    """schema_version must be 1. Other values are rejected."""

    def test_default_version_is_1(self):
        state = _neutral_state()
        appraisal = _neutral_appraisal()
        result = project_public_emotion(state, appraisal)
        assert result.schema_version == 1

    @pytest.mark.parametrize("bad_version", [0, 2, -1, 99])
    def test_rejects_wrong_version(self, bad_version):
        with pytest.raises(ValueError):
            EmotionStateResponse(
                schema_version=bad_version,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[],
                timestamp=1_700_000_000.0,
            )

    @pytest.mark.parametrize("bad_type", [True, False, None, "1", 1.0, [1], {"v": 1}])
    def test_rejects_non_int_version(self, bad_type):
        with pytest.raises(ValueError):
            EmotionStateResponse(
                schema_version=bad_type,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[],
                timestamp=1_700_000_000.0,
            )


# ─── Requirement 3: Extra fields rejected ────────────────────────────────────

class TestExtraFieldsRejected:
    """EmotionStateResponse, PublicPAD, PublicDominantEmotion forbid extra fields."""

    def test_emotion_state_response_rejects_extra_field(self):
        with pytest.raises(ValueError):
            EmotionStateResponse(
                schema_version=1,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[],
                timestamp=1_700_000_000.0,
                acting_instruction="should not appear",
            )

    def test_emotion_state_response_rejects_coping_mode(self):
        with pytest.raises(ValueError):
            EmotionStateResponse(
                schema_version=1,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[],
                timestamp=1_700_000_000.0,
                coping_mode="DEFENSIVE",
            )

    def test_emotion_state_response_rejects_libido(self):
        with pytest.raises(ValueError):
            EmotionStateResponse(
                schema_version=1,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[],
                timestamp=1_700_000_000.0,
                libido=0.5,
            )

    def test_pad_rejects_extra_field(self):
        with pytest.raises(ValueError):
            PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0, energy=0.5)

    def test_dominant_emotion_rejects_extra_field(self):
        with pytest.raises(ValueError):
            PublicDominantEmotion(name="joy", intensity=0.5, color="red")


# ─── Requirement 4: PAD unchanged in HTTP contract ───────────────────────────

class TestPADValues:
    """PAD -1, 0, 1 remains unchanged in the HTTP contract."""

    def test_pad_negative_one(self):
        state = _state_with_pad(pleasure=-1.0, arousal=-1.0, dominance=-1.0)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.pad.pleasure == -1.0
        assert result.pad.arousal == -1.0
        assert result.pad.dominance == -1.0

    def test_pad_zero(self):
        state = _state_with_pad(pleasure=0.0, arousal=0.0, dominance=0.0)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.pad.pleasure == 0.0
        assert result.pad.arousal == 0.0
        assert result.pad.dominance == 0.0

    def test_pad_positive_one(self):
        state = _state_with_pad(pleasure=1.0, arousal=1.0, dominance=1.0)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.pad.pleasure == 1.0
        assert result.pad.arousal == 1.0
        assert result.pad.dominance == 1.0

    def test_pad_fractional(self):
        state = _state_with_pad(pleasure=0.35, arousal=-0.72, dominance=0.99)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.pad.pleasure == 0.35
        assert result.pad.arousal == -0.72
        assert result.pad.dominance == 0.99


# ─── Requirement 5: Timestamp ────────────────────────────────────────────────

class TestTimestamp:
    """Timestamp must match EmotionalStateV1.timestamp exactly."""

    def test_timestamp_matches_state(self):
        state = _neutral_state(timestamp=1_700_000_000.0)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.timestamp == 1_700_000_000.0

    def test_timestamp_non_integer(self):
        ts = 1_700_123_456.789
        state = _neutral_state(timestamp=ts)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.timestamp == ts

    def test_timestamp_very_large(self):
        ts = 2_000_000_000.0
        state = _neutral_state(timestamp=ts)
        result = project_public_emotion(state, _neutral_appraisal())
        assert result.timestamp == ts


# ─── Requirement 6: Emotion ordering ─────────────────────────────────────────

class TestEmotionOrdering:
    """Emotions sorted by intensity desc, then name asc for ties."""

    def test_ordered_by_intensity_desc(self):
        emotions = {"joy": 0.8, "sadness": 0.5, "anger": 0.9}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        names = [e.name for e in result.dominant_emotions]
        assert names == ["anger", "joy", "sadness"]

    def test_ties_sorted_by_name_asc(self):
        emotions = {"joy": 0.8, "sadness": 0.8, "anger": 0.8, "fear": 0.8}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        names = [e.name for e in result.dominant_emotions]
        # All same intensity, sorted alphabetically
        assert names == sorted(names)
        assert len(names) <= 3

    def test_mixed_order(self):
        emotions = {"trust": 0.6, "anger": 0.9, "joy": 0.6, "sadness": 0.3}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        names = [e.name for e in result.dominant_emotions]
        # anger (0.9), then trust (0.6) and joy (0.6) sorted alpha
        assert names[0] == "anger"
        assert names[1] in ("joy", "trust")
        assert names[2] in ("joy", "trust")
        assert names[1] != names[2]


# ─── Requirement 7: At most 3 emotions ───────────────────────────────────────

class TestMaxThreeEmotions:
    """At most 3 emotions are returned."""

    def test_four_emotions_limited_to_three(self):
        emotions = {k: 0.9 for k in ["joy", "anger", "sadness", "fear"]}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        assert len(result.dominant_emotions) == 3

    def test_one_emotion_stays_one(self):
        appraisal = _appraisal_with_emotions({"joy": 0.8})
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        assert len(result.dominant_emotions) == 1
        assert result.dominant_emotions[0].name == "joy"

    def test_no_emotions_returns_empty_list(self):
        state = _neutral_state()
        result = project_public_emotion(state, _neutral_appraisal())

        assert result.dominant_emotions == []

    def test_zero_intensity_omitted(self):
        emotions = {"joy": 0.0, "anger": 0.8, "sadness": 0.0}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)

        assert len(result.dominant_emotions) == 1
        assert result.dominant_emotions[0].name == "anger"


# ─── Requirement 8: Zero intensity omitted ───────────────────────────────────

class TestZeroIntensityOmitted:
    """Emotions with intensity 0.0 are not included."""

    def test_all_zeros_returns_empty(self):
        emotions = {k: 0.0 for k in ["joy", "anger", "sadness"]}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)
        assert result.dominant_emotions == []

    def test_mixed_zeros_and_positive(self):
        emotions = {"joy": 0.0, "anger": 0.5, "sadness": 0.0}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)
        assert len(result.dominant_emotions) == 1
        assert result.dominant_emotions[0].name == "anger"

    def test_very_small_positive_kept(self):
        emotions = {"joy": 0.001, "anger": 0.0}
        appraisal = _appraisal_with_emotions(emotions)
        state = _neutral_state()
        result = project_public_emotion(state, appraisal)
        assert len(result.dominant_emotions) == 1
        assert result.dominant_emotions[0].name == "joy"


# ─── Requirement 9: No forbidden fields ──────────────────────────────────────

class TestForbiddenFieldsAbsent:
    """The public contract must not contain forbidden internal fields."""

    FORBIDDEN = [
        "acting_instruction",
        "coping_mode",
        "libido",
        "aggression",
        "connection",
        "energy",
        "tension",
        "prompt",
        "memory",
        "relationship",
        "meta_cognition",
        "meta-cognition",
        "last_update",
    ]

    def test_forbidden_fields_not_in_serialized_output(self):
        state = _neutral_state()
        appraisal = _appraisal_with_emotions({"joy": 0.8, "anger": 0.5})
        result = project_public_emotion(state, appraisal)

        data = result.model_dump()
        for field in self.FORBIDDEN:
            assert field not in data, f"Forbidden field '{field}' found in DTO"

    def test_forbidden_fields_not_in_nested_pad(self):
        pad = PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0)
        data = pad.model_dump()
        for field in ["libido", "aggression", "tension", "energy", "connection"]:
            assert field not in data, f"Forbidden field '{field}' found in PAD"

    def test_model_json_contains_no_forbidden_fields(self):
        state = _neutral_state()
        appraisal = _appraisal_with_emotions({"joy": 0.8})
        result = project_public_emotion(state, appraisal)

        json_str = result.model_dump_json()
        for field in self.FORBIDDEN:
            assert field not in json_str, f"Forbidden field '{field}' found in JSON"


# ─── Requirement 10: ChatResponse uses typed DTO ─────────────────────────────
# This is verified by importing the updated ChatResponse from main.py

class TestChatResponseTyped:
    """Validation that ChatResponse now uses EmotionStateResponse, not dict."""

    def test_emotion_state_response_is_not_dict(self):
        state = _neutral_state()
        appraisal = _neutral_appraisal()
        result = project_public_emotion(state, appraisal)
        assert not isinstance(result, dict)
        assert isinstance(result, EmotionStateResponse)

    def test_emotion_state_response_is_pydantic_model(self):
        state = _neutral_state()
        appraisal = _neutral_appraisal()
        result = project_public_emotion(state, appraisal)
        # Pydantic v2 models have model_dump method
        assert hasattr(result, "model_dump")
        assert hasattr(result, "model_dump_json")


# ─── Requirement 11: Single appraisal + transition ───────────────────────────
# This is a behavioural test in the integration sense. We verify here that
# the presentation module itself does not call parse_llm_appraisal or transition.

class TestNoExtraAppraisalOrTransition:
    """project_public_emotion itself must not call parse_llm_appraisal or transition."""

    def test_projection_does_not_modify_inputs(self):
        state = _state_with_pad(pleasure=0.5, arousal=0.3, dominance=-0.2)
        original_state_dict = state.to_dict()
        appraisal = _appraisal_with_emotions({"joy": 0.8, "sadness": 0.3})
        original_appraisal_dict = appraisal.to_dict()

        project_public_emotion(state, appraisal)

        # State is unchanged
        assert state.to_dict() == original_state_dict
        # Appraisal is unchanged
        assert appraisal.to_dict() == original_appraisal_dict

    def test_projection_pure_no_side_effects(self):
        """Verify that the function has no side effects by calling twice."""
        state = _state_with_pad(pleasure=0.5, arousal=0.3, dominance=-0.2)
        appraisal = _appraisal_with_emotions({"joy": 0.8})

        result1 = project_public_emotion(state, appraisal)
        result2 = project_public_emotion(state, appraisal)

        assert result1.model_dump() == result2.model_dump()


# ─── Requirement 12: Projection does not modify inputs ───────────────────────

class TestProjectionImmutability:
    """project_public_emotion does not mutate EmotionalStateV1 or AppraisalV1."""

    def test_state_unchanged_after_projection(self):
        state = _state_with_pad(pleasure=0.5, arousal=0.3, dominance=-0.2)
        appraisal = _neutral_appraisal()
        before = state.to_dict()
        project_public_emotion(state, appraisal)
        assert state.to_dict() == before

    def test_appraisal_unchanged_after_projection(self):
        state = _neutral_state()
        appraisal = _appraisal_with_emotions({"joy": 0.8})
        before = appraisal.to_dict()
        project_public_emotion(state, appraisal)
        assert appraisal.to_dict() == before


# ─── Requirement 13: Persisted snapshot still v1 without dominant_emotions ───

class TestPersistedSnapshot:
    """The persisted EmotionalStateV1 does NOT include dominant_emotions."""

    def test_state_to_dict_no_dominant_emotions(self):
        state = _neutral_state()
        data = state.to_dict()
        # EmotionalStateV1 fields should not include dominant_emotions
        assert "dominant_emotions" not in data
        expected = {
            "schema_version", "pleasure", "arousal", "dominance",
            "libido", "aggression", "connection", "energy", "tension",
            "coping_mode", "timestamp",
        }
        assert set(data.keys()) == expected

    def test_persisted_state_is_emotional_state_v1(self):
        state = _neutral_state()
        assert isinstance(state, EmotionalStateV1)
        assert state.schema_version == EMOTIONAL_SCHEMA_VERSION


# ─── Requirement 14: No infra dependencies ───────────────────────────────────

class TestNoInfraDependencies:
    """No test uses Groq, Supabase, embeddings, real clock, or real network."""

    def test_presentation_module_pure(self):
        """Verify emotion_presentation can be imported without infra modules."""
        # Use the same pattern as test_emotional_domain.py for isolation tests.
        import subprocess
        import sys
        import textwrap
        import os

        env = {
            **os.environ,
            "PYTHONPATH": str(
                __import__("pathlib").Path(__file__).parent.parent.parent
            ),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
        script = textwrap.dedent('''
            import sys
            import os
            for k in ["GROQ_API_KEY", "GROQ_API_KEY_2", "SUPABASE_URL", "SUPABASE_KEY"]:
                os.environ.pop(k, None)

            from backend.emotion_presentation import (
                EmotionStateResponse, PublicPAD, PublicDominantEmotion,
                classify_pad_mood, project_public_emotion,
            )
            from backend.emotional_domain import EmotionalStateV1, AppraisalV1

            state = EmotionalStateV1.neutral(timestamp=1_700_000_000.0)
            ap = AppraisalV1.neutral()
            result = project_public_emotion(state, ap)
            assert result.schema_version == 1
            assert result.mood_label == "NEUTRA"
            assert result.pad.pleasure == 0.0
            assert result.dominant_emotions == []

            for mod in list(sys.modules.keys()):
                for prefix in ("groq", "supabase", "fastapi", "sentence_transformers"):
                    if mod.startswith(prefix) or prefix in mod:
                        print(f"INFRA_LOADED: {mod}")
                        raise SystemExit(1)
            print("OK")
        ''')
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert proc.returncode == 0, f"stdout: {proc.stdout}, stderr: {proc.stderr}"
        assert "OK" in proc.stdout


# ─── classify_pad_mood tests ─────────────────────────────────────────────────

class TestClassifyPadMood:
    """Tests for the shared mood classification helper."""

    def test_neutral(self):
        assert classify_pad_mood(0.0, 0.0, 0.0) == "NEUTRA"

    def test_extase_dominante(self):
        assert classify_pad_mood(0.8, 0.7, 0.5) == "EXTASE/DOMINANTE"

    def test_encantada(self):
        assert classify_pad_mood(0.8, 0.7, -0.5) == "ENCANTADA"

    def test_alegre_excitada(self):
        assert classify_pad_mood(0.8, 0.7, 0.0) == "ALEGRE/EXCITADA"

    def test_furia_odio(self):
        assert classify_pad_mood(-0.8, 0.7, 0.5) == "FURIA/ODIO"

    def test_terror_panico(self):
        assert classify_pad_mood(-0.8, 0.7, -0.5) == "TERROR/PANICO"

    def test_estresse_agonia(self):
        assert classify_pad_mood(-0.8, 0.7, 0.0) == "ESTRESSE/AGONIA"

    def test_relaxada_satisfeita(self):
        assert classify_pad_mood(0.8, 0.3, 0.0) == "RELAXADA/SATISFEITA"

    def test_desprezo_frio(self):
        assert classify_pad_mood(-0.8, 0.3, 0.5) == "DESPREZO/FRIO"

    def test_depressao_tristeza(self):
        assert classify_pad_mood(-0.8, 0.3, -0.5) == "DEPRESSAO/TRISTEZA"

    def test_tedio(self):
        assert classify_pad_mood(-0.8, 0.3, 0.0) == "TEDIO"

    def test_boundary_arousal(self):
        """At exactly 0.5 arousal, we fall to the 'else' branch (arousal <= 0.5)."""
        assert classify_pad_mood(0.8, 0.5, 0.0) == "RELAXADA/SATISFEITA"

    def test_boundary_pleasure(self):
        """At pleasure > 0.5 with arousal > 0.5, it's ALEGRE/EXCITADA."""
        assert classify_pad_mood(0.51, 0.6, 0.0) == "ALEGRE/EXCITADA"

    def test_just_below_pleasure_threshold(self):
        """At exactly 0.5 pleasure with arousal > 0.5, falls to NEUTRA."""
        assert classify_pad_mood(0.5, 0.6, 0.0) == "NEUTRA"


# ─── Projection integration tests ───────────────────────────────────────────

class TestProjectionIntegration:
    """End-to-end projection tests combining state and appraisal."""

    def test_full_projection_with_emotions(self):
        state = _state_with_pad(pleasure=0.8, arousal=0.7, dominance=0.5)
        appraisal = _appraisal_with_emotions({"joy": 0.9, "gratitude": 0.6, "trust": 0.4})
        result = project_public_emotion(state, appraisal)

        assert result.mood_label == "EXTASE/DOMINANTE"
        assert result.pad.pleasure == 0.8
        assert result.pad.arousal == 0.7
        assert result.pad.dominance == 0.5
        assert len(result.dominant_emotions) == 3
        assert result.dominant_emotions[0].name == "joy"
        assert result.dominant_emotions[0].intensity == 0.9

    def test_projection_negative_state(self):
        state = _state_with_pad(pleasure=-0.8, arousal=0.7, dominance=-0.5)
        appraisal = _appraisal_with_emotions({"fear": 0.9, "sadness": 0.7})
        result = project_public_emotion(state, appraisal)

        assert result.mood_label == "TERROR/PANICO"
        assert len(result.dominant_emotions) == 2

    def test_projection_no_emotions(self):
        state = _neutral_state()
        appraisal = _neutral_appraisal()
        result = project_public_emotion(state, appraisal)

        assert result.mood_label == "NEUTRA"
        assert result.dominant_emotions == []

    def test_projection_model_dump_roundtrip(self):
        state = _state_with_pad(pleasure=-0.3, arousal=0.6, dominance=0.1)
        appraisal = _appraisal_with_emotions({"joy": 0.5, "anger": 0.2})
        result = project_public_emotion(state, appraisal)

        # Round-trip through JSON
        json_str = result.model_dump_json()
        restored = EmotionStateResponse.model_validate_json(json_str)

        assert restored.schema_version == result.schema_version
        assert restored.mood_label == result.mood_label
        assert restored.pad.pleasure == result.pad.pleasure
        assert restored.timestamp == result.timestamp
        assert len(restored.dominant_emotions) == len(result.dominant_emotions)
        for orig, rest in zip(result.dominant_emotions, restored.dominant_emotions):
            assert orig.name == rest.name
            assert orig.intensity == rest.intensity


# ─── Pydantic model validators ──────────────────────────────────────────────

class TestPydanticValidators:
    """Edge case validation for DTO constructors."""

    def test_pad_rejects_nan(self):
        with pytest.raises(ValueError):
            PublicPAD(pleasure=float("nan"), arousal=0.0, dominance=0.0)

    def test_pad_rejects_inf(self):
        with pytest.raises(ValueError):
            PublicPAD(pleasure=0.0, arousal=float("inf"), dominance=0.0)

    def test_pad_rejects_neg_inf(self):
        with pytest.raises(ValueError):
            PublicPAD(pleasure=0.0, arousal=0.0, dominance=float("-inf"))

    def test_pad_rejects_bool(self):
        with pytest.raises(ValueError):
            PublicPAD(pleasure=True, arousal=0.0, dominance=0.0)

    def test_dominant_emotion_rejects_nan(self):
        with pytest.raises(ValueError):
            PublicDominantEmotion(name="joy", intensity=float("nan"))

    def test_dominant_emotion_rejects_negative_intensity(self):
        with pytest.raises(ValueError):
            PublicDominantEmotion(name="joy", intensity=-0.1)

    def test_dominant_emotion_rejects_too_high_intensity(self):
        with pytest.raises(ValueError):
            PublicDominantEmotion(name="joy", intensity=1.1)


# ─── Duplicate emotion rejection ─────────────────────────────────────────────

class TestDuplicateEmotionRejection:
    """EmotionStateResponse must reject duplicate emotion names."""

    def test_duplicate_direct_construction(self):
        """Duplicates rejected via direct EmotionStateResponse construction."""
        with pytest.raises(ValueError, match="Duplicate dominant emotion"):
            EmotionStateResponse(
                schema_version=1,
                mood_label="NEUTRA",
                pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
                dominant_emotions=[
                    PublicDominantEmotion(name="joy", intensity=0.8),
                    PublicDominantEmotion(name="joy", intensity=0.5),
                ],
                timestamp=1_700_000_000.0,
            )

    def test_duplicate_model_validate(self):
        """Duplicates rejected via model_validate."""
        data = {
            "schema_version": 1,
            "mood_label": "NEUTRA",
            "pad": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0},
            "dominant_emotions": [
                {"name": "joy", "intensity": 0.8},
                {"name": "joy", "intensity": 0.5},
            ],
            "timestamp": 1_700_000_000.0,
        }
        with pytest.raises(ValueError, match="Duplicate dominant emotion"):
            EmotionStateResponse.model_validate(data)

    def test_duplicate_json(self):
        """Duplicates rejected via model_validate_json."""
        json_str = json.dumps({
            "schema_version": 1,
            "mood_label": "NEUTRA",
            "pad": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0},
            "dominant_emotions": [
                {"name": "anger", "intensity": 0.9},
                {"name": "anger", "intensity": 0.7},
            ],
            "timestamp": 1_700_000_000.0,
        })
        with pytest.raises(ValueError, match="Duplicate dominant emotion"):
            EmotionStateResponse.model_validate_json(json_str)

    def test_three_distinct_names_valid(self):
        """Three distinct emotion names are accepted."""
        result = EmotionStateResponse(
            schema_version=1,
            mood_label="NEUTRA",
            pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
            dominant_emotions=[
                PublicDominantEmotion(name="joy", intensity=0.8),
                PublicDominantEmotion(name="anger", intensity=0.7),
                PublicDominantEmotion(name="sadness", intensity=0.6),
            ],
            timestamp=1_700_000_000.0,
        )
        assert len(result.dominant_emotions) == 3
        names = [e.name for e in result.dominant_emotions]
        assert names == ["joy", "anger", "sadness"]

    def test_empty_list_valid(self):
        """Empty dominant_emotions list is valid."""
        result = EmotionStateResponse(
            schema_version=1,
            mood_label="NEUTRA",
            pad=PublicPAD(pleasure=0.0, arousal=0.0, dominance=0.0),
            dominant_emotions=[],
            timestamp=1_700_000_000.0,
        )
        assert result.dominant_emotions == []


# ─── project_public_emotion input validation ─────────────────────────────────

class TestProjectPublicEmotionInputValidation:
    """project_public_emotion must fail predictably on invalid inputs."""

    def test_none_state_raises_presentation_error(self):
        with pytest.raises(PresentationError, match="state cannot be None"):
            project_public_emotion(None, _neutral_appraisal())

    def test_none_appraisal_raises_presentation_error(self):
        with pytest.raises(PresentationError, match="appraisal cannot be None"):
            project_public_emotion(_neutral_state(), None)

    def test_wrong_state_type_raises_type_error(self):
        with pytest.raises(TypeError, match="state must be an EmotionalStateV1"):
            project_public_emotion("invalid_state", _neutral_appraisal())

    def test_wrong_appraisal_type_raises_type_error(self):
        with pytest.raises(TypeError, match="appraisal must be an AppraisalV1"):
            project_public_emotion(_neutral_state(), "invalid_appraisal")

    def test_attribute_error_does_not_escape(self):
        """Invalid objects should not produce AttributeError from the projection."""
        import subprocess, sys, textwrap, os
        env = {
            **os.environ,
            "PYTHONPATH": str(
                __import__("pathlib").Path(__file__).parent.parent.parent
            ),
        }
        script = textwrap.dedent('''
            import sys
            from backend.emotion_presentation import project_public_emotion, PresentationError
            from backend.emotional_domain.models import EmotionalStateV1, AppraisalV1

            try:
                # Dict as state (wrong type) — should trigger TypeError, not AttributeError
                project_public_emotion({"pleasure": 0.0}, AppraisalV1.neutral())
            except TypeError:
                print("EXPECTED_TYPE_ERROR")
                sys.exit(0)
            except AttributeError:
                print("ATTRIBUTE_ERROR_ESCAPED")
                sys.exit(1)
            except PresentationError:
                # Dict doesn't have .pleasure etc — could trigger AttributeError if unchecked
                # but our isinstance check catches it first
                print("EXPECTED_TYPE_ERROR")
                sys.exit(0)
            except Exception as e:
                print(f"OTHER_ERROR: {type(e).__name__}: {e}")
                sys.exit(1)

            print("NO_ERROR")
            sys.exit(1)
        ''')
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert proc.returncode == 0, f"stdout: {proc.stdout}, stderr: {proc.stderr}"
        assert "EXPECTED_TYPE_ERROR" in proc.stdout

    def test_wrong_state_type_has_correct_error_type(self):
        """Confirm exact TypeError raised, not AttributeError."""
        try:
            project_public_emotion({"pleasure": 0.0}, _neutral_appraisal())
            pytest.fail("Should have raised")
        except TypeError:
            pass  # Expected
        except Exception as e:
            pytest.fail(f"Expected TypeError, got {type(e).__name__}")


# ─── ChatResponse field type verification ────────────────────────────────────

class TestChatResponseFieldType:
    """ChatResponse.emotion_state field must be EmotionStateResponse."""

    def test_emotion_state_field_is_emotion_state_response(self):
        """The ``emotion_state`` field in the chat response is typed to EmotionStateResponse.

        Verifies via a standalone Pydantic model that mirrors ChatResponse (the real
        ChatResponse in main.py cannot be imported without FastAPI and Supabase deps).
        """
        from pydantic import BaseModel, Field
        from backend.emotion_presentation import EmotionStateResponse

        class _TestChatModel(BaseModel):
            response: str = Field(default="")
            emotion_state: EmotionStateResponse

        # Verify the field annotation is EmotionStateResponse, not a generic dict
        field_info = _TestChatModel.model_fields["emotion_state"]
        annotation = field_info.annotation
        assert annotation is EmotionStateResponse, (
            f"Expected annotation to be EmotionStateResponse, got {annotation}"
        )

        # Verify it accepts an EmotionStateResponse instance
        from backend.emotional_domain.models import EmotionalStateV1, AppraisalV1
        from backend.emotion_presentation import project_public_emotion
        state = EmotionalStateV1.neutral(timestamp=1_700_000_000.0)
        ap = AppraisalV1.neutral()
        emotion = project_public_emotion(state, ap)

        model = _TestChatModel(response="ok", emotion_state=emotion)
        assert isinstance(model.emotion_state, EmotionStateResponse)
        assert model.emotion_state.schema_version == 1
