# Emotional Core v1 — Architecture

## Scope

This document describes the typed, versioned domain contracts introduced in issue #232
and hardened in issue #232 v1.1, plus the deterministic emotional transition introduced
in issue #233.

It covers construction invariants, deep immutability, serialisation, migration, parser,
fallback policy, alias translation, and the transition layer (decay, appraisal shifts,
tension update, and coping regulation).

It does **not** describe production integration (#234).

---

## Layer boundaries

```
┌────────────────────────────────────────────────────────────────┐
│  Presentation  (prompt builder, acting instruction)            │
├────────────────────────────────────────────────────────────────┤
│  Transition    (transition.transition — #233)                  │
│     pure, deterministic, infrastructure-free                   │
│     no I/O, no time.time(), no randomness                      │
│     decay → appraisal shifts → tension → regulation            │
├────────────────────────────────────────────────────────────────┤
│  Appraisal     (parse_llm_appraisal, AppraisalV1)              │
│                          ▲ produces AppraisalV1                │
├────────────────────────────────────────────────────────────────┤
│  State         (EmotionalStateV1)                              │
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
    transition.py         — transition(), TransitionConfig, RegulationResult (added in #233)
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

## Transition layer — `transition.py`

### Public API

```python
from backend.emotional_domain import transition, TransitionConfig, RegulationResult, TransitionResult

result = transition(
    previous_state=EmotionalStateV1,
    appraisal=AppraisalV1,
    current_time=float,            # Unix epoch seconds, explicit
    config=TransitionConfig,
)
# → TransitionResult with .state (EmotionalStateV1) and .regulation (RegulationResult)
```

### Design principles

- **Pure**: no I/O, no randomness, no global state, no `time.time()`, no environment variables.
- **Deterministic**: same inputs always produce identical outputs.
- **Immutable**: never mutates `previous_state`, `appraisal`, or `config`.
- **Infrastructure-free**: no FastAPI, Groq, Supabase, embeddings, or network.
- **Single source of appraisal**: receives exactly one canonical `AppraisalV1`. Does **not**
  execute `OCCAppraisal`, keyword heuristics, alias translation, or LLM payload parsing.

### Order of operations

```
1. Validate current_time (reject bool, None, str, list, dict, NaN, Inf, <= 0)
2. Compute elapsed seconds (clock regression → elapsed = 0.0)
3. Apply exponential decay to PAD and tension toward baselines
4. Apply capped appraisal shifts to PAD
5. Clamp PAD to [-1.0, +1.0]
6. Update tension based on pleasure level
7. Clamp tension to [0.0, 1.0]
8. Determine coping mode (with hysteresis + MANIC handling)
9. Apply regulation effects
10. Build new EmotionalStateV1 via validated factory
11. Return TransitionResult
```

### Exponential decay formula

```python
factor = 0.5 ** (elapsed_seconds / half_life_seconds)
value_after_decay = baseline + (value_before - baseline) * factor
```

#### Default parameters

| Parameter | Value | Domain |
|---|---|---|
| PAD half-life | 3600.0 s (1 hour) | pleasure, arousal, dominance |
| tension half-life | 7200.0 s (2 hours) | tension |
| PAD baseline | 0.0 | pleasure, arousal, dominance |
| tension baseline | 0.0 | tension |

**Not decayed in v1:** `libido`, `aggression`, `connection`, `energy` — these remain unchanged.

> ⚠️ All default parameters are **engineering choices**. They have **no claim of clinical
> validity**.

### Appraisal shift caps

No single appraisal can move an axis more than **0.25** (configurable via `TransitionConfig`):

```python
effective_shift = clamp(appraisal_shift, -configured_max, configured_max)
```

Each axis (`pleasure`, `arousal`, `dominance`) has its own configurable cap.

### Discrete emotions are not accumulated

Two appraisals with the same scalar shifts but different `discrete_emotions` produce the
**same emotional snapshot** (same PAD, drives, tension, coping mode). Discrete emotions
are signals of the event, not accumulated in the persistent snapshot.

### Current time and clock regression

- `current_time` must be a finite positive float (Unix epoch seconds).
- `bool`, `None`, `str`, `list`, `dict`, `NaN`, `Inf`, and values ≤ 0 are rejected.
- If `current_time < previous_state.timestamp`, elapsed is set to 0.0 and the output
  timestamp equals `previous_state.timestamp`.
- The output timestamp **never decreases** below `previous_state.timestamp`.

```python
output_timestamp = max(previous_state.timestamp, current_time)
```

### Tension update (pleasure-reactive)

| Condition | Tension delta |
|---|---|
| `pleasure < negative_pleasure_threshold` (default −0.3) | `+tension_increase` (+0.05) |
| `pleasure > positive_pleasure_threshold` (default +0.3) | `−tension_relief` (−0.05) |
| Otherwise | 0.0 |

Tension is always clamped to `[0.0, 1.0]`.

### Coping mode determination (hysteresis)

#### Default thresholds

| Threshold | Value |
|---|---|
| `activation_threshold` | 0.8 (inclusive) |
| `recovery_threshold` | 0.3 (inclusive) |

#### Rules

| Condition | Coping mode |
|---|---|
| `tension ≥ 0.8` and `dominance > 0.0` | `DEFENSIVE` |
| `tension ≥ 0.8` and `dominance ≤ 0.0` | `DISSOCIATED` |
| `tension ≤ 0.3` | `HEALTHY` |
| `0.3 < tension < 0.8` | Preserve previous mode (hysteresis) |

#### MANIC handling

- In the intermediate range (`0.3 < tension < 0.8`), MANIC **remains MANIC**.
- On recovery (`tension ≤ 0.3`), MANIC transitions to **HEALTHY**.
- On activation (`tension ≥ 0.8`), MANIC transitions to **DEFENSIVE** (if
  `dominance > 0.0`) or **DISSOCIATED** (if `dominance ≤ 0.0`).

#### Regulation effects

| Mode | Effects |
|---|---|
| `HEALTHY` | No additional effects. |
| `DEFENSIVE` | No additional effects in v1. **Does not increase aggression.** |
| `DISSOCIATED` | Arousal is multiplied by `dissociation_arousal_factor` (default 0.5), then clamped to `[-1.0, 1.0]`. |

No mode produces prompt text, acting instructions, or user-facing content.

### RegulationResult

```python
@dataclass(frozen=True)
class RegulationResult:
    previous_mode: str          # Coping mode before regulation
    current_mode: str           # Coping mode after regulation
    changed: bool               # True when previous_mode != current_mode
    reason: RegulationReason    # Enum: NONE, HIGH_TENSION_POSITIVE_DOMINANCE,
                                #       HIGH_TENSION_NONPOSITIVE_DOMINANCE, RECOVERED
```

`RegulationReason` is a `str` enum with the following values:

| Value | Meaning |
|---|---|
| `none` | No change in coping mode |
| `high_tension_positive_dominance` | Activation with dominance > 0 (→ DEFENSIVE) |
| `high_tension_nonpositive_dominance` | Activation with dominance ≤ 0 (→ DISSOCIATED) |
| `recovered` | Tension dropped to recovery threshold (→ HEALTHY) |

`RegulationResult` contains no prompt text, no user content, no LLM output, no
acting instruction, and no metacognitive strategy.

## Out of scope (this document)

- Integration of these models into `ConversationEngine` (→ #234).
- Persistence changes.
- API or frontend changes.
- Relationship, memory, prompt, or personality logic.
