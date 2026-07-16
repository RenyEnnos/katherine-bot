# Relationship State v1 — `RelationshipStateV1`

## Boundary: authenticated identity vs. relational snapshot

The relationship snapshot **never** contains the user's identity.

- `user_id` is supplied **by the authenticated context** at the infrastructure boundary.
- `ConversationEngine.load_user_state()` passes the authenticated `user_id` to
  `MemoryManager.load_user_state()`, which uses it as a filter key.
- `MemoryManager.sync_state()` uses the authenticated `user_id` in `.eq("user_id", user_id)`.
- The JSONB column stores only the v1 fields; the database row's `user_id` column holds identity.

**Rule:** identity is always derived from the authenticated token, never from the persisted payload.

## Version and fields

```
RELATIONSHIP_SCHEMA_VERSION = 1
```

| Field           | Type              | Range      | Default | Description                     |
|-----------------|-------------------|------------|---------|---------------------------------|
| `schema_version`| `int`             | exactly 1  | 1       | Schema version                  |
| `trust`         | `float`           | `[0.0, 1.0]` | 0.5   | Trust level                     |
| `affection`     | `float`           | `[0.0, 1.0]` | 0.3   | Affection level                 |
| `tension`       | `float`           | `[0.0, 1.0]` | 0.0   | Tension/resentment level        |
| `triggers`      | `tuple[str, ...]` | max 32     | `()`  | Emotional triggers (immutable)  |
| `timestamp`     | `float`           | `> 0`      | —     | Unix epoch seconds              |

### Never persisted in the snapshot

- `user_id` — comes from the authenticated context.
- `bond_label` — always derived via `compute_bond_label()` at read time.

## Invariants

All public construction paths enforce the same invariants:

1. `schema_version` must be `int` (not `bool`/`float`/`str`/`None`) and equal to `1`.
2. `trust`, `affection`, `tension`: finite `float` in `[0.0, 1.0]`.
3. Reject `bool`, `None`, `str`, `list`, `dict`, `NaN`, `±Inf`.
4. Values outside `[0.0, 1.0]` are **rejected** (no silent clamp in the model; clamps belong to the transition).
5. `timestamp`: finite positive `float`.
6. `triggers`: see trigger policy below.
7. Unknown keys in `from_dict()` are rejected.
8. Missing required fields in `from_dict()` are rejected.

## Trigger policy

```
- Accept only list or tuple of strings.
- Max 32 items.
- Apply `.strip()` to each item.
- Reject item empty after trim.
- Max 128 characters per item.
- Deduplicate preserving first occurrence and order.
- Store as `tuple[str, ...]` (deeply immutable).
- Mutations of the source collection do not affect the snapshot.
```

Triggers are **not** updated by the transition function in this version.
LLM-based trigger updates are out of scope for this task.

## Bond label calculation (`compute_bond_label`)

Preserves the exact labels and thresholds from the legacy implementation:

| Condition                                          | Label         |
|----------------------------------------------------|---------------|
| `tension > 0.7`                                    | `Em Conflito` |
| `tension > 0.4`                                    | `Tenso`       |
| `trust > 0.8` and `affection > 0.8`                | `Alma Gêmea`  |
| `trust > 0.7` and `affection > 0.6`                | `Íntimos`     |
| `trust > 0.5` and `affection > 0.4`                | `Amigos`      |
| `trust < 0.3`                                      | `Desconfiada` |
| otherwise                                          | `Conhecidos`  |

`bond_label` is never serialised and never accepted in `from_dict()` / `to_dict()`.
A legacy `bond_label` value is ignored; the correct label is always recomputed from the metrics.

## Weights and thresholds preserved

| Trigger                           | Effect                    | Delta  |
|-----------------------------------|---------------------------|--------|
| `valence > 0.2`                   | trust `+0.02`             |        |
| `valence < -0.3`                  | trust `-0.05`             |        |
| `tenderness > 0.3`                | affection `+0.03`         |        |
| `joy > 0.3`                       | affection `+0.01`         |        |
| `gratitude > 0.3`                 | affection `+0.02`         |        |
| `anger > 0.3`                     | tension `+0.10`           |        |
| `disgust > 0.3`                   | tension `+0.10`           |        |
| `valence < -0.5`                  | tension `+0.05`           |        |
| `valence > 0.3` and tension `> 0` | reconciliation `-0.10`    |        |

All results are clamped to `[0.0, 1.0]` **in the transition**, not in the model.

## Pure transition

```python
def transition_relationship(
    previous_state: RelationshipStateV1,
    appraisal: AppraisalV1,
    current_time: float,
    config: RelationshipTransitionConfig,
) -> RelationshipStateV1
```

- Pure: no I/O, no `time.time()`, no global state.
- Deterministic: same inputs → same output.
- Immutable: does not modify `previous_state`; returns a new instance.
- Uses `RelationshipTransitionConfig` (immutable, validated defaults).
- Rejects clock regression (`current_time < previous_state.timestamp`).
- Preserves triggers from the previous state.

## Legacy migration

```python
def migrate_legacy_relationship_snapshot(payload: object) -> RelationshipStateV1
```

- Accepts legacy dict with keys: `user_id`, `bond_label`, `trust`, `affection`,
  `tension`, `triggers`, `last_interaction`.
- Maps `last_interaction` → `timestamp`.
- Allows `user_id` and `bond_label` fields but **never uses them** for identity or bonding.
- Rejects unknown legacy keys, empty dicts, and missing required fields.
- Accepts a v1 snapshot idempotently.
- Pure: no I/O, no `time.time()`, does not mutate the input.

## Example JSON (v1, as stored in JSONB)

```json
{
  "schema_version": 1,
  "trust": 0.72,
  "affection": 0.65,
  "tension": 0.12,
  "triggers": ["music", "childhood"],
  "timestamp": 1700000000.0
}
```

## Deliberate exclusions from persistence

| Concept              | Reason                                           |
|----------------------|--------------------------------------------------|
| `user_id`            | Identity belongs to the authenticated context    |
| `bond_label`         | Always derived from validated metrics            |
| Prompt               | Not relationship data                            |
| Memory               | Separately managed (archival, episodic)          |
| Emotional state      | Separately managed (`EmotionalStateV1`)           |
| Meta-cognition       | Separately managed (deactivated per P0)          |
| Acting instructions  | Generated at read time from emotional state      |

## Layer separation

```
┌──────────────────────────────────────────┐
│           ConversationEngine             │
│  (orchestration, identity, lock, I/O)    │
├──────────────────────────────────────────┤
│            MemoryManager                 │
│  (load/save, supabase, embeddings)       │
├──────────────────────────────────────────┤
│           RelationshipStateV1            │
│  (pure domain: valid, immutable, typed)  │
├──────────────────────────────────────────┤
│           EmotionalCore v1               │
│  (EmotionalStateV1, AppraisalV1, etc.)   │
├──────────────────────────────────────────┤
│         EmotionStateResponse             │
│  (public DTO, no relationship fields)    │
└──────────────────────────────────────────┘
```

- `EmotionalCore`, `AppraisalV1`, `EmotionalStateV1` are in `backend/emotional_domain/`.
- `RelationshipStateV1` is in `backend/relationship.py`.
- `EmotionStateResponse` is in `backend/emotion_presentation.py`.
- Each layer imports only the types it needs; no circular dependencies.
- The public HTTP API exposes zero relationship fields.

## File locations

| File                                         | Purpose                                  |
|----------------------------------------------|------------------------------------------|
| `backend/relationship.py`                    | Domain model, migration, transition      |
| `backend/engine.py`                          | Conversation orchestration               |
| `backend/memory.py`                          | Persistence layer                        |
| `backend/emotional_domain/models.py`         | Emotional state & appraisal models       |
| `backend/emotion_presentation.py`            | Public DTO (no relationship fields)      |
| `backend/tests/test_relationship_domain.py`  | Pure domain tests (35+ requirements)     |
