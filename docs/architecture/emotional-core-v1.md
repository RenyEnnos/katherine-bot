# Emotional Core v1 — Architecture

## Scope

This document describes the typed, versioned domain contracts introduced in issue #232
and hardened in issue #232 v1.1.
It covers construction invariants, deep immutability, serialisation, migration, parser,
fallback policy, and alias translation.
It does **not** describe transition logic, decay, or production integration (#233/#234).

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
    appraisal_parser.py   — parse_llm_appraisal (with ParseResult and ParseErrorCode)
```

No file in this package imports FastAPI, Groq, Supabase, sentence_transformers,
environment variables, or any I/O. This is verified by an isolated subprocess test.

---

## Schema version

```python
EMOTIONAL_SCHEMA_VERSION: int = 1
```

Single supported version. All models carry `schema_version` and reject any other value,
including: `None`, `bool`, `float`, `str`, and any integer ≠ 1.

---

## Validation on all public construction paths

Every public construction path validates all invariants:

| Path | Validation |
|---|---|
| `EmotionalStateV1(...)` | `__post_init__` validates all fields |
| `EmotionalStateV1.create(...)` | validates, then delegates to `__init__` |
| `EmotionalStateV1.from_dict(...)` | checks structure, then delegates to `create` |
| `EmotionalStateV1.neutral(...)` | delegates to `create` |
| `AppraisalV1(...)` | `__post_init__` validates all fields and enforces immutability |
| `AppraisalV1.create(...)` | validates, then delegates to `__init__` |
| `AppraisalV1.from_dict(...)` | checks structure, then delegates to `create` |
| `AppraisalV1.neutral()` | delegates to `create` |

> **There is no way to produce an invalid instance through any public path.**

---

## EmotionalStateV1

### Fields and invariants

| Field         | Type    | Range / Allowlist       | Policy on violation |
|---------------|---------|-------------------------|---------------------|
| `schema_version` | `int` | must equal `1`; not bool, float, str, None | `EmotionalDomainError` |
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

**Unknown keys in `from_dict`:** always rejected via `EmotionalDomainError`.

**Error messages do not include raw values** (e.g., out-of-range numbers, enum values from input) to avoid leaking untrusted data.

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

# Direct construction also validates (via __post_init__)
state = EmotionalStateV1(pleasure=0.1, ..., schema_version=1)  # raises if invalid
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
| `discrete_emotions`| `MappingProxyType[str, float]` | keys ∈ `DISCRETE_EMOTIONS`, values in `[0.0, 1.0]` | `EmotionalDomainError` |

### Discrete emotion allowlist

```python
DISCRETE_EMOTIONS = frozenset({
    # Core emotions
    "joy", "sadness", "anger", "fear",
    "disgust", "surprise",
    # Extended emotions (from v1 model)
    "trust", "anticipation",
    # Production emotions (consumed by RelationshipManager via _perceive)
    "tenderness", "guilt", "pride", "jealousy", "gratitude",
})
```

**Total: 13 emotions.** This allowlist is compatible with the production
`_perceive()` output and the emotions used by `RelationshipManager`
(tenderness and gratitude for affection, anger and disgust for tension).

The LLM parser (`parse_llm_appraisal`) **filters** unknown emotion keys
from LLM output silently, while the constructors (`create`, `from_dict`,
direct `__init__`) **reject** unknown emotion keys with
`EmotionalDomainError`.

Unknown emotion keys are **rejected** via `create`/`from_dict`/direct constructor.
In the LLM parser (`parse_llm_appraisal`), unknown emotions are **filtered silently**
(different policy — see Parser section).

### Deep immutability

`discrete_emotions` is stored as a `MappingProxyType`. This means:

- The object passed by the caller is **copied defensively** at construction time.
- Mutations to the original dict after construction have **no effect** on the model.
- The stored mapping **cannot be mutated** (`TypeError` if attempted).
- `to_dict()` returns a **fresh mutable copy** for serialisation; this copy does not
  share state with the stored proxy.

```python
src = {"joy": 0.5}
ap = AppraisalV1.create(..., discrete_emotions=src)
src["joy"] = 99.0      # no effect
ap.discrete_emotions["joy"] = 0.9  # raises TypeError
d = ap.to_dict()
d["discrete_emotions"]["joy"] = 0.9  # no effect on ap
```

### Neutral appraisal

```python
neutral = AppraisalV1.neutral()
# → valence_shift=0.0, arousal_shift=0.0, dominance_shift=0.0, discrete_emotions={}
```

---

## Serialisation

```python
from backend.emotional_domain import serialize_state, deserialize_state
from backend.emotional_domain import serialize_appraisal, deserialize_appraisal

json_str = serialize_state(state)    # deterministic JSON, sorted keys
restored = deserialize_state(json_str)
assert state == restored
```

**Guarantees:**
- Output always includes `schema_version`.
- Keys are sorted (deterministic format).
- No prompt, metacognition, relationship, or memory fields.
- Round-trip produces an equivalent object.
- Output remains valid even after the `to_dict()` copy is mutated (deep immutability).

---

## Migration from legacy snapshots

### Legacy format (exact field set)

The legacy `EmotionalState.to_dict()` format uses `last_update` instead of `timestamp`,
and has no `schema_version` key.

**Exactly these fields are accepted in a legacy snapshot:**

```
pleasure, arousal, dominance, libido, aggression, connection,
energy, tension, coping_mode, last_update
```

Any additional field (including `timestamp`, `schema_version`, `memory`, `system_prompt`,
`relationship_score`, `acting_label`, etc.) causes `EmotionalDomainError`.

### Migration contract

```python
from backend.emotional_domain import migrate_legacy_snapshot

state_v1 = migrate_legacy_snapshot(legacy_dict)
```

| Condition | Result |
|---|---|
| Key `schema_version` absent | Treated as legacy snapshot |
| `schema_version` key present, value `None` | `EmotionalDomainError` (not "absent") |
| `schema_version` key present, value `True`/`False`/`"1"` | `EmotionalDomainError` |
| `schema_version=1` present | V1 idempotent path (re-validates) |
| Both `last_update` and `timestamp` present | `EmotionalDomainError` (ambiguous) |
| Any extra field in legacy snapshot | `EmotionalDomainError` |
| Missing required legacy field | `EmotionalDomainError` |
| Any field value violating invariants | `EmotionalDomainError` |

Input dict is **never mutated**.

---

## LLM appraisal parser

### Minimum structure

An appraisal from LLM output must contain all three shift fields (after alias
translation). An empty dict `{}` is **not valid** and produces a fallback.

### Top-level key allowlist

Only these keys are accepted at the top level:

```
valence_shift, valence,          (canonical + legacy alias)
arousal_shift,
dominance_shift,
discrete_emotions, triggered_emotions   (canonical + legacy alias)
```

Any unknown key produces `unknown_top_level_key` fallback.

### Legacy alias translation (explicit, tested)

| Production key | V1 canonical key |
|---|---|
| `valence` | `valence_shift` |
| `triggered_emotions` | `discrete_emotions` |

**Conflict policy (validated+normalised comparison):**

When both alias and canonical key are present, **each side is validated and
normalised independently** using the same rules as the parser:

1. **Validate** each side — reject bool, None, string, NaN, Inf, out-of-range,
   non-mapping types, and invalid intensities.
2. **Normalise** each side — convert int → float, filter unknown emotion keys
   silently (mappings that differ only by unknown emotions normalise to the
   same result).
3. **Compare** only normalised values:
   - If **either** side is invalid → the parser returns the corresponding
     validation error code (`invalid_numeric_value` or `unsupported_emotion`),
     **not** `conflicting_aliases`.
   - If both are valid and normalised values **match** → drop the alias, use
     the canonical key.
   - If both are valid and normalised values **differ** → `conflicting_aliases`
     fallback.

`1` and `1.0` are equivalent **only after both are validated** as finite floats.

`{"invented": 0.5}` and `{}` are equivalent because unknown emotion keys are
filtered during normalisation, producing `{}` in both cases.

### discrete_emotions handling

| `discrete_emotions` value | Result |
|---|---|
| Key absent from dict | Empty emotions (no fallback) |
| `{}` (explicit empty dict) | Empty emotions (valid) |
| `None` (key present, value None) | `unsupported_emotion` fallback |
| `str`, `list`, `number`, `bool` | `unsupported_emotion` fallback |
| Dict with unknown emotion keys | Keys silently filtered |
| Dict with invalid intensity | `invalid_numeric_value` fallback |

### Fallback codes (ParseErrorCode enum)

| Code | Meaning |
|---|---|
| `invalid_structure` | Not a dict |
| `unknown_top_level_key` | Dict contains key outside allowlist |
| `missing_required_field` | A shift field is absent |
| `conflicting_aliases` | Alias and canonical both valid but **normalised** values differ |
| `invalid_numeric_value` | Bad type (bool, None, string), NaN/Inf, out-of-range, or overflow in shift/intensity |
| `unsupported_emotion` | `discrete_emotions`/`triggered_emotions` is not a mapping (None, bool, str, list, number) |
| `unexpected_parser_failure` | Anything else (unexpected error) |

### Observable result

```python
from backend.emotional_domain import parse_llm_appraisal, ParseErrorCode

result = parse_llm_appraisal(raw_llm_dict)

if result.is_fallback:
    # Log result.error_code — stable enum value, safe to log
    # DO NOT log str(result.error_code) to an external system that sees LLM data
    code = result.error_code  # ParseErrorCode enum
    appraisal = result.appraisal  # AppraisalV1.neutral()
else:
    appraisal = result.appraisal  # valid AppraisalV1
```

> **Never log `str(exc)` from the parser.** Use `result.error_code.value` (a stable enum
> string) for observability. The error code never contains raw LLM text, user content,
> field names from untrusted input, or exception repr.

---

## Out of scope (this document / issue #232)

- Transition logic, decay, or PAD update formulas (→ #233).
- Integration of these models into `ConversationEngine` (→ #234).
- Persistence changes.
- API or frontend changes.
- Relationship, memory, prompt, or personality logic.
