# Emotional Core v1 — Architecture

## Scope

This document describes the typed, versioned domain contracts introduced in issue #232.
It covers boundaries, invariants, allowlists, serialisation, migration, and fallback policy.
It does **not** describe transition logic, decay, or production integration (those are #233 and #234).

---

## Layer boundaries

```
┌────────────────────────────────────────────────────────────────┐
│  Presentation  (prompt builder, acting instruction)            │
├────────────────────────────────────────────────────────────────┤
│  Transition    (AffectiveEngine — decay, PAD update, coping)   │
│                          ▲ uses (not replaced in #232)         │
├────────────────────────────────────────────────────────────────┤
│  Appraisal     (parse_llm_appraisal, OCCAppraisal)             │
│                          ▲ produces AppraisalV1                │
├────────────────────────────────────────────────────────────────┤
│  State         (EmotionalStateV1) — this document              │
├────────────────────────────────────────────────────────────────┤
│  Migration     (migrate_legacy_snapshot)                       │
└────────────────────────────────────────────────────────────────┘
```

**What belongs to the state layer:** pleasure, arousal, dominance, drives, coping mode, timestamp.  
**What does NOT belong:** relationship data, memory, prompt text, personality rules, metacognition.

---

## Module location

```
backend/emotional_domain/
    __init__.py           — public API re-exports
    models.py             — EmotionalStateV1, AppraisalV1, constants
    migration.py          — migrate_legacy_snapshot
    serialization.py      — serialize_*/deserialize_* (JSON)
    appraisal_parser.py   — parse_llm_appraisal (with fallback)
```

No file in this package imports FastAPI, Groq, Supabase, sentence_transformers,
environment variables, or any I/O.

---

## Schema version

```python
EMOTIONAL_SCHEMA_VERSION: int = 1
```

Single supported version. All models carry `schema_version` and reject any other value.

---

## EmotionalStateV1

### Fields and invariants

| Field         | Type    | Range / Allowlist       | Policy on violation |
|---------------|---------|-------------------------|---------------------|
| `schema_version` | `int` | must equal `1`        | `EmotionalDomainError` |
| `pleasure`    | `float` | `[-1.0, 1.0]`          | `EmotionalDomainError` |
| `arousal`     | `float` | `[-1.0, 1.0]`          | `EmotionalDomainError` |
| `dominance`   | `float` | `[-1.0, 1.0]`          | `EmotionalDomainError` |
| `libido`      | `float` | `[0.0, 1.0]`           | `EmotionalDomainError` |
| `aggression`  | `float` | `[0.0, 1.0]`           | `EmotionalDomainError` |
| `connection`  | `float` | `[0.0, 1.0]`           | `EmotionalDomainError` |
| `energy`      | `float` | `[0.0, 1.0]`           | `EmotionalDomainError` |
| `tension`     | `float` | `[0.0, 1.0]`           | `EmotionalDomainError` |
| `coping_mode` | `str`   | see `VALID_COPING_MODES` | `EmotionalDomainError` |
| `timestamp`   | `float` | finite, positive        | `EmotionalDomainError` |

**Global rejections (all numeric fields):**
- `bool` (including `True`/`False`)
- `None`
- `str`, `list`, `dict`, or any non-numeric type
- `NaN`, `+Inf`, `-Inf`

**Unknown keys:** always rejected via `EmotionalDomainError`.

### Coping mode allowlist

```python
VALID_COPING_MODES = frozenset({"HEALTHY", "DEFENSIVE", "DISSOCIATED", "MANIC"})
```

### Construction

```python
# Validated factory (recommended)
state = EmotionalStateV1.create(
    pleasure=0.1, arousal=-0.2, dominance=0.3,
    libido=0.0, aggression=0.1, connection=0.5,
    energy=0.8, tension=0.2,
    coping_mode="HEALTHY",
    timestamp=1_700_000_000.0,
)

# Neutral default
state = EmotionalStateV1.neutral(timestamp=time.time())

# From persisted dict (validates all fields + rejects unknown keys)
state = EmotionalStateV1.from_dict(stored_dict)
```

### Valid JSON example

```json
{
  "aggression": 0.1,
  "arousal": -0.2,
  "connection": 0.5,
  "coping_mode": "HEALTHY",
  "dominance": 0.3,
  "energy": 0.8,
  "libido": 0.0,
  "pleasure": 0.1,
  "schema_version": 1,
  "tension": 0.2,
  "timestamp": 1700000000.0
}
```

---

## AppraisalV1

### Fields and invariants

| Field              | Type            | Range / Allowlist          | Policy on violation     |
|--------------------|-----------------|----------------------------|-------------------------|
| `schema_version`   | `int`           | must equal `1`             | `EmotionalDomainError`  |
| `valence_shift`    | `float`         | `[-1.0, 1.0]`              | `EmotionalDomainError`  |
| `arousal_shift`    | `float`         | `[-1.0, 1.0]`              | `EmotionalDomainError`  |
| `dominance_shift`  | `float`         | `[-1.0, 1.0]`              | `EmotionalDomainError`  |
| `discrete_emotions`| `dict[str, float]` | keys ∈ `DISCRETE_EMOTIONS`, values in `[0.0, 1.0]` | `EmotionalDomainError` |

### Discrete emotion allowlist

```python
DISCRETE_EMOTIONS = frozenset({
    "joy", "sadness", "anger", "fear",
    "disgust", "surprise", "trust", "anticipation",
})
```

Unknown emotion keys are **rejected** (strict policy). Intensities follow the same
rejection rules as other numeric fields (no bool, no None, no NaN/Inf, range enforced).

### Neutral appraisal

```python
neutral = AppraisalV1.neutral()
# → valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0, discrete_emotions={}
```

### Valid JSON example

```json
{
  "arousal_shift": -0.1,
  "discrete_emotions": {
    "joy": 0.5,
    "trust": 0.3
  },
  "dominance_shift": 0.0,
  "schema_version": 1,
  "valence_shift": 0.2
}
```

---

## Serialisation

```python
from backend.emotional_domain import serialize_state, deserialize_state
from backend.emotional_domain import serialize_appraisal, deserialize_appraisal

# EmotionalStateV1
json_str = serialize_state(state)    # deterministic JSON, sorted keys
restored = deserialize_state(json_str)
assert state == restored

# AppraisalV1
json_str = serialize_appraisal(appraisal)
restored = deserialize_appraisal(json_str)
assert appraisal == restored
```

**Guarantees:**
- Output always includes `schema_version`.
- Keys are sorted (deterministic format).
- No prompt text, metacognition, relationship, or memory fields exposed.
- Round-trip produces an equivalent object.

---

## Migration from legacy snapshots

The legacy `EmotionalState.to_dict()` format uses `last_update` (float) instead of
`timestamp` and has no `schema_version`.

```python
from backend.emotional_domain import migrate_legacy_snapshot

# From storage (legacy format — no schema_version key)
legacy = {
    "pleasure": 0.1, "arousal": -0.2, "dominance": 0.3,
    "libido": 0.0, "aggression": 0.1, "connection": 0.5,
    "energy": 0.8, "tension": 0.2, "coping_mode": "HEALTHY",
    "last_update": 1700000000.0,
}
state_v1 = migrate_legacy_snapshot(legacy)
```

**Migration contract:**
- Input is never mutated.
- `last_update` → `timestamp`.
- Missing required fields → `EmotionalDomainError`.
- Invalid values → `EmotionalDomainError` (fails closed).
- If `schema_version=1` is already present, re-validates and returns as-is (idempotent).
- Any other `schema_version` → `EmotionalDomainError`.
- No I/O, no Supabase, pure function.

---

## Fallback policy for invalid LLM appraisal

```python
from backend.emotional_domain import parse_llm_appraisal

result = parse_llm_appraisal(raw_llm_dict)

if result.is_fallback:
    # Log result.error — LLM produced invalid output
    appraisal = result.appraisal  # always AppraisalV1.neutral()
else:
    appraisal = result.appraisal  # valid AppraisalV1
```

**Policy:**
- Any validation error → neutral fallback, error recorded in `result.error`.
- Never raises.
- Unknown emotion keys from LLM output are silently filtered (not rejected).
- Invalid intensity values → fallback.
- Result is never an empty dict; always an explicit `AppraisalV1`.

---

## Out of scope (this document / issue #232)

- Transition logic, decay, or PAD update formulas (→ #233).
- Integration of these models into `ConversationEngine` (→ #234).
- Persistence changes.
- API or frontend changes.
- Relationship, memory, prompt, or personality logic.
