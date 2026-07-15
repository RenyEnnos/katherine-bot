# Public Emotion Contract v1

## Overview

The public emotion contract defines the **only** emotion payload sent from the backend to the frontend. It is versioned, typed, and explicitly excludes all internal state.

## JSON Contract

```json
{
  "schema_version": 1,
  "mood_label": "NEUTRA",
  "pad": {
    "pleasure": 0.0,
    "arousal": 0.0,
    "dominance": 0.0
  },
  "dominant_emotions": [
    {
      "name": "joy",
      "intensity": 0.8
    }
  ],
  "timestamp": 1700000000.0
}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `int` | Must be `1`. Only version 1 is accepted. |
| `mood_label` | `string` | Human-readable mood derived from PAD coordinates. See classification below. |
| `pad` | `object` | Pleasure-Arousal-Dominance in bipolar `[-1.0, +1.0]` scale. |
| `pad.pleasure` | `float` | `-1.0` (Agony) to `+1.0` (Ecstasy) |
| `pad.arousal` | `float` | `-1.0` (Sleep) to `+1.0` (Frenzy) |
| `pad.dominance` | `float` | `-1.0` (Submissive) to `+1.0` (Dominant) |
| `dominant_emotions` | `array` | At most 3 discrete emotions, sorted by intensity descending, then name ascending for ties. |
| `dominant_emotions[].name` | `string` | Canonical emotion identifier (e.g. `"joy"`, `"anger"`). |
| `dominant_emotions[].intensity` | `float` | `0.0` to `1.0`. Zero-intensity emotions are omitted. |
| `timestamp` | `float` | Unix epoch seconds from `EmotionalStateV1.timestamp`. |

## Version

- **Current version**: `1`
- The `schema_version` field is mandatory. Payloads with a missing or different version are **rejected** by the frontend.

## Mood Classification (`classify_pad_mood`)

The mood label is derived from PAD coordinates using a deterministic rule set:

| Condition | Label |
|---|---|
| arousal > 0.5, pleasure > 0.5, dominance > 0.3 | `EXTASE/DOMINANTE` |
| arousal > 0.5, pleasure > 0.5, dominance < -0.3 | `ENCANTADA` |
| arousal > 0.5, pleasure > 0.5, otherwise | `ALEGRE/EXCITADA` |
| arousal > 0.5, pleasure < -0.5, dominance > 0.3 | `FURIA/ODIO` |
| arousal > 0.5, pleasure < -0.5, dominance < -0.3 | `TERROR/PANICO` |
| arousal > 0.5, pleasure < -0.5, otherwise | `ESTRESSE/AGONIA` |
| arousal ≤ 0.5, pleasure > 0.5 | `RELAXADA/SATISFEITA` |
| arousal ≤ 0.5, pleasure < -0.5, dominance > 0.3 | `DESPREZO/FRIO` |
| arousal ≤ 0.5, pleasure < -0.5, dominance < -0.3 | `DEPRESSAO/TRISTEZA` |
| arousal ≤ 0.5, pleasure < -0.5, otherwise | `TEDIO` |
| Default (none of the above) | `NEUTRA` |

This classification is used exclusively by the public DTO. The internal prompt builder uses a separate
classifier (``AffectiveEngine.get_emotional_label``, legacy path). Consolidating the two classifiers
into a single shared implementation is tracked as a follow-up item.

## Emotion Ordering

`dominant_emotions` is sorted by:
1. **Intensity descending** (highest first)
2. **Name ascending** (alphabetically) for ties

**Example**: `[{anger: 0.9}, {joy: 0.6}, {trust: 0.6}]` — anger first (highest), then joy before trust (alphabetical tie-break).

## Frontend Validation Policy

When the frontend receives an `emotion_state` payload, it applies the following rules:

| Condition | Behaviour |
|---|---|
| Payload is `null` or `undefined` | Store `null`, do not render the panel |
| `schema_version` missing or ≠ 1 | Reject entire payload, render nothing |
| `pad` missing or malformed | Reject entire payload, render nothing |
| Any PAD value is `NaN` / `Infinity` / `-Infinity` | Reject entire payload |
| `dominant_emotions` missing or not an array | Reject entire payload |
| `dominant_emotions` is an empty array | Render panel with PAD bars but no emotion badges |
| All valid | Render normally |

**No partial state is ever rendered.** If validation fails, the panel is hidden.

## Conversion Helpers (Frontend)

### PAD Bipolar → Display Percentage

```
bipolarToPercent(-1.0) → 0
bipolarToPercent( 0.0) → 50
bipolarToPercent( 1.0) → 100
```

Clamp: values below -1 are treated as -1; above 1 as 1.
Non-finite values fall back to 50 (neutral).

### Intensity → Display Percentage

```
intensityToPercent(0.0) → 0
intensityToPercent(0.5) → 50
intensityToPercent(1.0) → 100
```

Clamp: values below 0 are treated as 0; above 1 as 1.
Non-finite values fall back to 0.

## Architecture: Layering

Four distinct layers exist in the emotion system:

| Layer | What | Contains | Exposed to |
|---|---|---|---|
| **Persisted snapshot** | `EmotionalStateV1` | PAD + drives + coping_mode + tension + timestamp | Database (Supabase) |
| **Appraisal** | `AppraisalV1` | shift values + discrete_emotions (11 emotions) | Transition engine |
| **Internal presentation** | Prompt builder | `classify_pad_mood` + `get_acting_instruction` | LLM prompt |
| **Public DTO** | `EmotionStateResponse` | mood_label + PAD + dominant_emotions (max 3) + timestamp | Browser |

The **public DTO** is the only layer sent to the browser. All other layers are internal.

## Explicitly Prohibited Fields

The public DTO must **never** contain, directly or indirectly:

| Field | Reason |
|---|---|
| `acting_instruction` | Internal prompt directive |
| `coping_mode` | Internal coping state |
| `libido` | Internal drive |
| `aggression` | Internal drive |
| `connection`, `energy`, `tension` | Internal system state |
| `last_update` | Superseded by `timestamp` |
| Memory | Not part of emotion contract |
| Relationship | Not part of emotion contract |
| Meta-cognition | Not part of emotion contract |
| Raw LLM output | Not validated, may contain sensitive content |
| Complete appraisal | Internal, too detailed for public |
| Internal fallback codes | Observability only |
| Secrets or user IDs | Security |

## Source Files

- **Backend DTO**: `backend/emotion_presentation.py`
- **Mood classification**: `classify_pad_mood()` in `backend/emotion_presentation.py`
- **ChatResponse with typed field**: `backend/main.py`
- **Frontend validation**: `validateEmotionState()` in `frontend/src/shared/utils/formatters.js`
- **Frontend component**: `frontend/src/features/chat/components/EmotionPanel.jsx`
- **Frontend percent helpers**: `bipolarToPercent()` and `intensityToPercent()` in `frontend/src/shared/utils/formatters.js`
