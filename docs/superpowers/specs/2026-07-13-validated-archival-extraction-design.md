# Spec: Validated and Idempotent Archival Memory Extraction

## Context and Goal
The goal of this specification is to restore the extraction of archival facts from conversation turns in a versioned, validated, append-only, atomic, and idempotent manner. The input source is restricted strictly to a persisted user turn.

This implementation replaces legacy unvalidated extraction systems and avoids updating `profiles.user_profile` directly. It also ensures that no sensitive conversation logs, keys, or IDs are exposed during logging or exceptions.

---

## 1. Domain Types and Validation Rules

All validation rules reside inside a pure python module `backend/archival_memory.py`.

### 1.1 Turn Reference (`PersistedTurnRef`)
Represents the structural metadata of a turn successfully written to the database:
* `user_id`: str (non-empty)
* `source_chat_log_id`: int (the id of the `"user"` role message in `chat_logs`)
* `assistant_chat_log_id`: int (the id of the `"assistant"` role message in `chat_logs`)

### 1.2 Archival Fact (`ArchivalFact`)
Represents a single fact extracted from a turn:
* `content`: str
  * Must not be empty after strip/trim.
  * Maximum of 500 characters.
* `importance`: float
  * Finite float value between `0.0` and `1.0` inclusive.
  * Explicitly reject boolean types (`True`, `False`).
  * Reject `None`, `NaN`, and `infinity`.
* `tags`: List[str]
  * Maximum of 8 tags per fact.
  * Normalized to lowercase.
  * Must match the format regex `^[a-z0-9][a-z0-9_-]*$`.
  * Maximum length of 32 characters per tag.
  * Deduplicated while preserving insertion order (e.g. `["b", "a", "b"]` becomes `["b", "a"]`).

### 1.3 Archival Extraction Envelope (`ArchivalExtractionEnvelope`)
The top-level container for facts:
* `facts`: List[ArchivalFact] (maximum of 5 facts allowed)
* `schema_version`: int (must be exactly `1`)
* `extractor_version`: int (must be exactly `1`)

### 1.4 Rigid Structural Rules
* **No Unknown Keys**: Any keys present in the JSON representation not explicitly defined in the envelope or the fact objects will cause validation to fail.
* **Type Safety**: Any values violating type bounds (e.g. `None` in non-nullable fields, boolean where float/int/string is required, list where dict is expected, etc.) are strictly rejected.

---

## 2. Database Schema

The supabase database will be updated with a new table `archival_extractions` in `supabase_schema.sql`:

```sql
create table archival_extractions (
  user_id text references profiles(user_id) on delete cascade,
  source_chat_log_id bigint references chat_logs(id) on delete cascade,
  extractor_version integer not null,
  schema_version integer not null,
  idempotency_key text not null,
  facts jsonb not null,
  created_at timestamp with time zone default timezone('utc'::text, now()),
  primary key (source_chat_log_id, extractor_version)
);

create unique index archival_extractions_idempotency_key_idx on archival_extractions(idempotency_key);
create index archival_extractions_user_id_idx on archival_extractions(user_id);

alter table archival_extractions enable row level security;

create policy "Users can access their own archival extractions"
  on archival_extractions
  for all
  using (auth.uid() = user_id);
```

---

## 3. Database Persistence & Idempotency

### 3.1 Turn Persistence Refinement (`MemoryManager.save_turn`)
We refine `save_turn()` to return a `PersistedTurnRef`. It will query the inserted data and validate:
* Exactly 2 lines are returned from the insert.
* IDs are present on both lines.
* One role is `"user"` and the other role is `"assistant"`.
* Both belong to the same `user_id`.
* Returns `PersistedTurnRef(user_id=user_id, source_chat_log_id=user_line_id, assistant_chat_log_id=assistant_line_id)`.

### 3.2 Idempotency Key
* **Generation**: The idempotency key is computed deterministically in Python using a SHA-256 hash of:
  `f"{user_id}:{source_chat_log_id}:{extractor_version}"`
* **Log Privacy**: The idempotency key is never logged.
* **Conflict Resolution**: If the database raises a unique key violation (PostgreSQL error code `23505`), the operation is treated as an idempotent success.

---

## 4. Orchestration & LLM Integration

### 4.1 Orchestration Task
The extraction is scheduled asynchronously only after `save_turn()` and `sync_state()` successfully complete:

```python
async def run_archival_extraction(self, turn_ref: PersistedTurnRef):
    # 1. Load user message content by turn_ref.user_id + turn_ref.source_chat_log_id
    # 2. Call LLM to extract facts in structured JSON
    # 3. Parse LLM response
    # 4. Validate facts structure using pure python domain validation
    # 5. Compute idempotency key
    # 6. Insert envelope in archival_extractions table (handle 23505)
```

### 4.2 Logging and Monitoring
The system uses the following constant events for logging:
* `archival_extraction_invalid`: The extracted fact/envelope failed validation rules.
* `archival_extraction_duplicate`: The extraction for this turn and version already exists.
* `archival_extraction_llm_failed`: The Groq API failed, timed out, or returned invalid JSON.
* `archival_extraction_store_failed`: Database error during insertion.

Under no circumstances will conversation content, `user_id`, log/message IDs, payloads, the idempotency key, or token counts be written to the logs.

---

## 5. Test Plan

We will write unit and integration tests verifying all target constraints:
1. Valid envelope and empty envelope parsing.
2. Rejection of unknown keys in JSON envelope or facts.
3. Rejection of invalid types (`None`, `bool` as importance, `NaN`, `infinity`).
4. Fact count limits (>5 facts rejected) and length limits (>500 characters rejected).
5. Importance bounds checking (<0.0 or >1.0 rejected).
6. Tag constraints (length >32, regex format matching, normalization to lowercase, deduplication preserving order).
7. `save_turn()` returning valid IDs, matching roles, and error-handling on database incomplete response.
8. Message retrieval requiring correct user and user role `"user"`.
9. LLM failure handled gracefully without database write.
10. Valid extraction persisting exactly one envelope.
11. Idempotency test (repeating the same turn does not duplicate, different turns remain distinct).
12. Check that logging is completely safe (no IDs, user_id, contents, payloads, or keys in `caplog`).
13. BackgroundTask scheduling happens only after state sync and turn save complete.
14. Public chat response continues to return exactly `response` and `emotion_state`.
