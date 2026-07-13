# Validated and Idempotent Archival Memory Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the extraction of versioned, validated, append-only, atomic, and idempotent archival facts using only a persisted user turn.

**Architecture:** Create a pure domain module `backend/archival_memory.py` for types and validation rules. Refine `MemoryManager` to validate turns on save and persist extraction envelopes. Update `ConversationEngine` and `FastAPI` endpoints to run the extraction in request-scoped background tasks using the existing thread-safe Groq manager.

**Tech Stack:** Python 3.12, FastAPI, Supabase, Groq.

## Global Constraints
* Define `ARCHIVAL_SCHEMA_VERSION = 1` and `EXTRACTOR_VERSION = 1`.
* Limit facts to at most 5 per turn/envelope.
* Fact content must be non-empty after trimming, maximum 500 characters.
* Fact importance must be a finite float in `[0.0, 1.0]`, rejecting boolean values, `None`, `NaN`, and `inf`.
* Limit tags to at most 8 per fact, maximum 32 characters per tag, lowercase normalized, matching `^[a-z0-9][a-z0-9_-]*$`, and deduplicated while preserving order.
* Reject unknown keys in JSON envelope or fact payload.
* Uniqueness constraint on turn and version (`source_chat_log_id`, `extractor_version`).
* PostgreSQL code `23505` uniqueness violation treated as successful idempotency.
* No sensitive info (IDs, payloads, user_id, conversation content, tokens, idempotency key) logged in caplog/standard logs. Use generic constant events: `archival_extraction_invalid`, `archival_extraction_duplicate`, `archival_extraction_llm_failed`, `archival_extraction_store_failed`.
* Agendar (Schedule) extraction only after turn persistence (`save_turn`) and state sync (`sync_state`) succeed.
* Public response contract of `ChatResponse` remains unchanged.

---

### Task 1: Domain Validation & Types

**Files:**
* Create: `backend/archival_memory.py`
* Test: `backend/tests/test_archival_memory_domain.py`

**Interfaces:**
* Produces:
  ```python
  @dataclass(frozen=True)
  class PersistedTurnRef:
      user_id: str
      source_chat_log_id: int
      assistant_chat_log_id: int

  @dataclass(frozen=True)
  class ArchivalFact:
      content: str
      importance: float
      tags: List[str]

  @dataclass(frozen=True)
  class ArchivalExtractionEnvelope:
      facts: List[ArchivalFact]
      schema_version: int = 1
      extractor_version: int = 1

  class ArchivalValidationError(Exception):
      pass

  def parse_archival_extraction(raw_dict: dict) -> ArchivalExtractionEnvelope:
      pass

  def compute_idempotency_key(user_id: str, source_chat_log_id: int, extractor_version: int) -> str:
      pass
  ```

- [ ] **Step 1: Write the failing tests**
  Create file `backend/tests/test_archival_memory_domain.py` with tests for:
  * Valid envelope and valid empty envelope.
  * Rejection of unknown keys in JSON/dict.
  * Rejection of invalid types (`None`, bool as importance, `NaN`, `infinity`).
  * Envelope limits (>5 facts) and fact content length limits (>500 chars).
  * Importance range checks.
  * Tag rules (length >32, regex format matching, normalization to lowercase, deduplication preserving order).

  ```python
  import pytest
  import math
  from backend.archival_memory import (
      parse_archival_extraction,
      ArchivalValidationError,
      compute_idempotency_key,
      ArchivalFact,
      ArchivalExtractionEnvelope
  )

  def test_valid_envelope():
      payload = {
          "facts": [
              {"content": "Likes hot coffee", "importance": 0.8, "tags": ["Coffee", "coffee", "likes_coffee"]}
          ],
          "schema_version": 1,
          "extractor_version": 1
      }
      env = parse_archival_extraction(payload)
      assert len(env.facts) == 1
      assert env.facts[0].content == "Likes hot coffee"
      assert env.facts[0].importance == 0.8
      # Normalized, unique, order-preserved tags: ["coffee", "likes_coffee"]
      assert env.facts[0].tags == ["coffee", "likes_coffee"]

  def test_empty_facts_valid():
      payload = {
          "facts": [],
          "schema_version": 1,
          "extractor_version": 1
      }
      env = parse_archival_extraction(payload)
      assert len(env.facts) == 0

  def test_reject_unknown_keys():
      payload = {
          "facts": [{"content": "x", "importance": 0.5, "tags": [], "extra_key": "bad"}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_bool_importance():
      payload = {
          "facts": [{"content": "x", "importance": True, "tags": []}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_invalid_importance_bounds():
      for imp in [-0.1, 1.1, math.nan, math.inf, None, "0.5"]:
          payload = {
              "facts": [{"content": "x", "importance": imp, "tags": []}],
              "schema_version": 1,
              "extractor_version": 1
          }
          with pytest.raises(ArchivalValidationError):
              parse_archival_extraction(payload)

  def test_reject_invalid_tag_chars():
      payload = {
          "facts": [{"content": "x", "importance": 0.5, "tags": ["-tag", "tag!", ""]}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_fact_length_exceeded():
      payload = {
          "facts": [{"content": "a" * 501, "importance": 0.5, "tags": []}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_too_many_facts():
      payload = {
          "facts": [{"content": f"f{i}", "importance": 0.5, "tags": []} for i in range(6)],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_too_many_tags():
      payload = {
          "facts": [{"content": "x", "importance": 0.5, "tags": [f"t{i}" for i in range(9)]}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_tag_too_long():
      payload = {
          "facts": [{"content": "x", "importance": 0.5, "tags": ["a" * 33]}],
          "schema_version": 1,
          "extractor_version": 1
      }
      with pytest.raises(ArchivalValidationError):
          parse_archival_extraction(payload)

  def test_reject_wrong_versions():
      for v in [0, 2, "1"]:
          payload = {
              "facts": [],
              "schema_version": v,
              "extractor_version": 1
          }
          with pytest.raises(ArchivalValidationError):
              parse_archival_extraction(payload)

  def test_compute_idempotency_key():
      key1 = compute_idempotency_key("user1", 123, 1)
      key2 = compute_idempotency_key("user1", 123, 1)
      key3 = compute_idempotency_key("user2", 123, 1)
      assert key1 == key2
      assert key1 != key3
      assert len(key1) == 64
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_domain.py -v`
  Expected: FAIL with ModuleNotFoundError or import error.

- [ ] **Step 3: Write minimal implementation**
  Create file `backend/archival_memory.py`:

  ```python
  import re
  import hashlib
  import math
  from dataclasses import dataclass
  from typing import List

  ARCHIVAL_SCHEMA_VERSION = 1
  EXTRACTOR_VERSION = 1

  class ArchivalValidationError(Exception):
      """Domain exception for failed validation checks on archival memories."""
      pass

  @dataclass(frozen=True)
  class PersistedTurnRef:
      user_id: str
      source_chat_log_id: int
      assistant_chat_log_id: int

  @dataclass(frozen=True)
  class ArchivalFact:
      content: str
      importance: float
      tags: List[str]

  @dataclass(frozen=True)
  class ArchivalExtractionEnvelope:
      facts: List[ArchivalFact]
      schema_version: int = ARCHIVAL_SCHEMA_VERSION
      extractor_version: int = EXTRACTOR_VERSION

  def compute_idempotency_key(user_id: str, source_chat_log_id: int, extractor_version: int) -> str:
      input_str = f"{user_id}:{source_chat_log_id}:{extractor_version}"
      return hashlib.sha256(input_str.encode("utf-8")).hexdigest()

  def parse_archival_extraction(raw_dict: dict) -> ArchivalExtractionEnvelope:
      if not isinstance(raw_dict, dict):
          raise ArchivalValidationError("Envelope must be a dictionary.")

      # Check for unknown keys in raw_dict
      allowed_keys = {"facts", "schema_version", "extractor_version"}
      if set(raw_dict.keys()) - allowed_keys:
          raise ArchivalValidationError("Unknown keys in envelope.")

      schema_version = raw_dict.get("schema_version", ARCHIVAL_SCHEMA_VERSION)
      extractor_version = raw_dict.get("extractor_version", EXTRACTOR_VERSION)

      # Versions must match exact int values
      if schema_version != ARCHIVAL_SCHEMA_VERSION or isinstance(schema_version, bool):
          raise ArchivalValidationError("Invalid or unsupported schema version.")
      if extractor_version != EXTRACTOR_VERSION or isinstance(extractor_version, bool):
          raise ArchivalValidationError("Invalid or unsupported extractor version.")

      facts_list = raw_dict.get("facts")
      if not isinstance(facts_list, list):
          raise ArchivalValidationError("Facts must be a list.")
      if len(facts_list) > 5:
          raise ArchivalValidationError("At most 5 facts are allowed per turn.")

      parsed_facts = []
      for fact_dict in facts_list:
          if not isinstance(fact_dict, dict):
              raise ArchivalValidationError("Fact must be a dictionary.")
          
          # Unknown keys in fact
          fact_keys = {"content", "importance", "tags"}
          if set(fact_dict.keys()) - fact_keys:
              raise ArchivalValidationError("Unknown keys in fact dictionary.")

          content = fact_dict.get("content")
          importance = fact_dict.get("importance")
          tags = fact_dict.get("tags")

          if content is None or not isinstance(content, str):
              raise ArchivalValidationError("Fact content must be a non-empty string.")
          
          trimmed_content = content.strip()
          if not trimmed_content:
              raise ArchivalValidationError("Fact content cannot be empty after trim.")
          if len(trimmed_content) > 500:
              raise ArchivalValidationError("Fact content exceeds maximum of 500 characters.")

          # Rejects boolean types
          if isinstance(importance, bool) or not isinstance(importance, (int, float)):
              raise ArchivalValidationError("Fact importance must be a float.")
          
          if not math.isfinite(importance) or not (0.0 <= importance <= 1.0):
              raise ArchivalValidationError("Fact importance must be finite and between 0.0 and 1.0.")

          if not isinstance(tags, list):
              raise ArchivalValidationError("Tags must be a list of strings.")
          if len(tags) > 8:
              raise ArchivalValidationError("At most 8 tags are allowed per fact.")

          seen_tags = {}
          deduplicated_tags = []
          for tag in tags:
              if not isinstance(tag, str):
                  raise ArchivalValidationError("Tag must be a string.")
              norm_tag = tag.strip().lower()
              if not norm_tag:
                  raise ArchivalValidationError("Tag cannot be empty.")
              if len(norm_tag) > 32:
                  raise ArchivalValidationError("Tag exceeds 32 characters.")
              if not re.match(r"^[a-z0-9][a-z0-9_-]*$", norm_tag):
                  raise ArchivalValidationError(f"Tag '{norm_tag}' does not match pattern [a-z0-9][a-z0-9_-]*.")
              
              if norm_tag not in seen_tags:
                  seen_tags[norm_tag] = True
                  deduplicated_tags.append(norm_tag)

          parsed_facts.append(
              ArchivalFact(
                  content=trimmed_content,
                  importance=float(importance),
                  tags=deduplicated_tags
              )
          )

      return ArchivalExtractionEnvelope(
          facts=parsed_facts,
          schema_version=schema_version,
          extractor_version=extractor_version
      )
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_domain.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  Run:
  ```bash
  git add backend/archival_memory.py backend/tests/test_archival_memory_domain.py
  git commit -m "feat(memory): implement pure python archival memory domain and validations"
  ```

---

### Task 2: Supabase Schema Update & MemoryManager Persistence Refinement

**Files:**
* Modify: `supabase_schema.sql` (Append new DDL at the end)
* Modify: `backend/memory.py`
* Create: `backend/tests/test_archival_memory_persistence.py`

**Interfaces:**
* Consumes:
  * `PersistedTurnRef` from `backend/archival_memory.py`
  * `ArchivalExtractionEnvelope` from `backend/archival_memory.py`
* Produces:
  * `MemoryManager.save_turn(self, user_id: str, user_msg: str, bot_msg: str) -> PersistedTurnRef`
  * `MemoryManager.load_persisted_user_message(self, user_id: str, source_chat_log_id: int) -> str`
  * `MemoryManager.store_archival_extraction(self, user_id: str, source_chat_log_id: int, idempotency_key: str, envelope: ArchivalExtractionEnvelope)`

- [ ] **Step 1: Write the failing tests**
  Create file `backend/tests/test_archival_memory_persistence.py` with tests verifying:
  * `save_turn()` validation of exactly two lines, IDs, and correct roles.
  * `save_turn()` raising `TurnPersistenceError` on incomplete or invalid DB outputs.
  * `load_persisted_user_message()` successfully retrieving message or raising domain exceptions if roles or users mismatch.
  * `store_archival_extraction()` inserting the correct facts JSONB array and idempotency key.
  * `store_archival_extraction()` resolving unique constraint violations (23505) as idempotent successes.

  ```python
  import pytest
  from unittest.mock import MagicMock, patch
  from backend.memory import MemoryManager, TurnPersistenceError
  from backend.archival_memory import (
      PersistedTurnRef,
      ArchivalFact,
      ArchivalExtractionEnvelope,
      ArchivalValidationError
  )

  def test_save_turn_success():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      mock_resp = MagicMock()
      mock_resp.data = [
          {"id": 100, "user_id": "u1", "role": "user", "content": "hi"},
          {"id": 101, "user_id": "u1", "role": "assistant", "content": "hello"}
      ]
      mock_resp.error = None
      mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
      
      ref = mm.save_turn("u1", "hi", "hello")
      assert isinstance(ref, PersistedTurnRef)
      assert ref.user_id == "u1"
      assert ref.source_chat_log_id == 100
      assert ref.assistant_chat_log_id == 101

  def test_save_turn_invalid_roles():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      mock_resp = MagicMock()
      mock_resp.data = [
          {"id": 100, "user_id": "u1", "role": "user", "content": "hi"},
          {"id": 101, "user_id": "u1", "role": "user", "content": "hello"}  # two users
      ]
      mock_resp.error = None
      mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
      
      with pytest.raises(TurnPersistenceError):
          mm.save_turn("u1", "hi", "hello")

  def test_load_persisted_user_message_success():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      mock_resp = MagicMock()
      mock_resp.data = [{"id": 100, "user_id": "u1", "role": "user", "content": "hi"}]
      mock_resp.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
      
      msg = mm.load_persisted_user_message("u1", 100)
      assert msg == "hi"

  def test_load_persisted_user_message_failure():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      # Mismatch user role
      mock_resp = MagicMock()
      mock_resp.data = [{"id": 100, "user_id": "u1", "role": "assistant", "content": "hello"}]
      mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
      with pytest.raises(KeyError):
          mm.load_persisted_user_message("u1", 100)

  def test_store_archival_extraction_success():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      mock_resp = MagicMock()
      mock_resp.data = [{"source_chat_log_id": 100}]
      mock_resp.error = None
      mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
      
      env = ArchivalExtractionEnvelope(facts=[ArchivalFact(content="F1", importance=0.9, tags=["t1"])])
      # Should run without exception
      mm.store_archival_extraction("u1", 100, "key_abc", env)
      
      mm.supabase.table.assert_called_with("archival_extractions")

  def test_store_archival_extraction_conflict():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      class PostgrestAPIError(Exception):
          def __init__(self):
              self.code = "23505"
              self.message = "Unique violation"

      mm.supabase.table.return_value.insert.return_value.execute.side_effect = PostgrestAPIError()
      
      env = ArchivalExtractionEnvelope(facts=[])
      # 23505 handled as success
      mm.store_archival_extraction("u1", 100, "key_abc", env)
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_persistence.py -v`
  Expected: FAIL with ImportError or AttributeError.

- [ ] **Step 3: Update schema and implement persistence logic**
  Append DDL to `supabase_schema.sql` (lines 63-87):
  ```sql
  -- 5. ARCHIVAL EXTRACTIONS TABLE
  create table if not exists archival_extractions (
    user_id text references profiles(user_id) on delete cascade,
    source_chat_log_id bigint references chat_logs(id) on delete cascade,
    extractor_version integer not null,
    schema_version integer not null,
    idempotency_key text not null,
    facts jsonb not null,
    created_at timestamp with time zone default timezone('utc'::text, now()),
    primary key (source_chat_log_id, extractor_version)
  );

  create unique index if not exists archival_extractions_idempotency_key_idx on archival_extractions(idempotency_key);
  create index if not exists archival_extractions_user_id_idx on archival_extractions(user_id);

  alter table archival_extractions enable row level security;

  create policy "Users can access their own archival extractions"
    on archival_extractions
    for all
    using (auth.uid() = user_id);
  ```

  Modify `backend/memory.py`:
  Add import:
  `from .archival_memory import PersistedTurnRef, ArchivalExtractionEnvelope`

  Modify `save_turn()` to:
  ```python
      def save_turn(self, user_id: str, user_msg: str, bot_msg: str) -> PersistedTurnRef:
          if not self.supabase:
              raise TurnPersistenceError("Serviço de persistência indisponível.")
          try:
              if len(user_msg) > MAX_MESSAGE_LENGTH or len(bot_msg) > MAX_MESSAGE_LENGTH:
                  raise TurnPersistenceError("Limite de caracteres excedido no turno.")
              response = self.supabase.table("chat_logs").insert([
                  {"user_id": user_id, "role": "user", "content": user_msg},
                  {"user_id": user_id, "role": "assistant", "content": bot_msg}
              ]).execute()
              if response is None:
                  raise TurnPersistenceError("Sem resposta do banco de dados ao salvar turno.")
              if hasattr(response, 'error') and response.error:
                  raise TurnPersistenceError("Erro retornado pelo banco de dados ao salvar turno.")
              if not hasattr(response, 'data') or response.data is None or len(response.data) != 2:
                  raise TurnPersistenceError("Falha na gravação do turno: registros inseridos incompletos.")
              
              # Validate roles and IDs
              records = response.data
              user_rec = None
              assistant_rec = None
              for rec in records:
                  if "id" not in rec or "role" not in rec or "user_id" not in rec:
                      raise TurnPersistenceError("Campos estruturais ausentes nas linhas persistidas.")
                  if rec["user_id"] != user_id:
                      raise TurnPersistenceError("Divergência de usuário no turno persistido.")
                  if rec["role"] == "user":
                      user_rec = rec
                  elif rec["role"] == "assistant":
                      assistant_rec = rec
              
              if not user_rec or not assistant_rec:
                  raise TurnPersistenceError("Roles inválidas nas linhas persistidas do turno.")
              
              return PersistedTurnRef(
                  user_id=user_id,
                  source_chat_log_id=user_rec["id"],
                  assistant_chat_log_id=assistant_rec["id"]
              )
          except TurnPersistenceError as e:
              logger.error(f"Erro ao persistir turno: {type(e).__name__}")
              raise
          except Exception as e:
              logger.error(f"Erro ao persistir turno: {type(e).__name__}")
              raise TurnPersistenceError("Falha ao persistir turno de conversação.") from None
  ```

  And add these two new methods to `MemoryManager`:
  ```python
      def load_persisted_user_message(self, user_id: str, source_chat_log_id: int) -> str:
          if not self.supabase:
              raise KeyError("Serviço de persistência indisponível.")
          try:
              response = self.supabase.table("chat_logs")\
                  .select("role, content, user_id")\
                  .eq("id", source_chat_log_id)\
                  .eq("user_id", user_id)\
                  .execute()
              if not response or not hasattr(response, 'data') or not response.data:
                  raise KeyError("Mensagem persistida não encontrada.")
              
              record = response.data[0]
              if record.get("role") != "user":
                  raise KeyError("A mensagem encontrada não é do usuário.")
              
              return record.get("content", "")
          except Exception as e:
              if isinstance(e, KeyError):
                  raise
              raise KeyError("Falha ao carregar mensagem persistida por ID.") from None

      def store_archival_extraction(self, user_id: str, source_chat_log_id: int, idempotency_key: str, envelope: ArchivalExtractionEnvelope):
          if not self.supabase:
              raise RuntimeError("Serviço de persistência indisponível.")
          
          facts_data = [
              {
                  "content": fact.content,
                  "importance": fact.importance,
                  "tags": fact.tags
              }
              for fact in envelope.facts
          ]

          payload = {
              "user_id": user_id,
              "source_chat_log_id": source_chat_log_id,
              "extractor_version": envelope.extractor_version,
              "schema_version": envelope.schema_version,
              "idempotency_key": idempotency_key,
              "facts": facts_data
          }

          try:
              self.supabase.table("archival_extractions").insert(payload).execute()
          except Exception as e:
              # Check for postgrest PostgreSQL 23505 uniqueness constraint violation
              err_code = getattr(e, "code", None)
              if err_code == "23505":
                  # Treat as successful idempotency
                  return
              raise RuntimeError("Falha ao gravar extração arquivística.") from e
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_persistence.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  Run:
  ```bash
  git add supabase_schema.sql backend/memory.py backend/tests/test_archival_memory_persistence.py
  git commit -m "feat(memory): add archival table DDL and implement memory persistence functions"
  ```

---

### Task 3: Orchestration Task, Log Isolation, API Scheduling & Integration

**Files:**
* Modify: `backend/engine.py`
* Modify: `backend/main.py`
* Create: `backend/tests/test_archival_memory_integration.py`

**Interfaces:**
* Consumes:
  * `parse_archival_extraction` and `compute_idempotency_key` from `backend/archival_memory.py`
  * `store_archival_extraction` and `load_persisted_user_message` from `backend/memory.py`
* Produces:
  * `ConversationEngine.run_archival_extraction(self, turn_ref: PersistedTurnRef)` (async background task)
  * Updated `ConversationEngine.process_turn(..., background_tasks: Optional[BackgroundTasks] = None)`
  * Updated `/chat` endpoint passing BackgroundTasks.

- [ ] **Step 1: Write the failing tests**
  Create file `backend/tests/test_archival_memory_integration.py` with tests for:
  * Background tasks being scheduled correctly inside `process_turn()` only after state sync.
  * Output formats: `ChatResponse` maintaining exactly `response` and `emotion_state`.
  * LLM returning invalid JSON or failure logging constant event `archival_extraction_llm_failed` and failing closed.
  * Validation failure logging constant event `archival_extraction_invalid` and failing closed.
  * Uniqueness conflict logging constant event `archival_extraction_duplicate` and succeeding.
  * DB failure logging constant event `archival_extraction_store_failed`.
  * No sensitive identifiers (user_id, payloads, messages, keys, tokens) found in `caplog` during logging checks.

  ```python
  import pytest
  import logging
  import json
  from unittest.mock import MagicMock, patch
  from backend.engine import ConversationEngine
  from backend.archival_memory import PersistedTurnRef

  @pytest.mark.anyio
  async def test_run_archival_extraction_llm_failure(caplog):
      engine = ConversationEngine()
      engine.memory_manager = MagicMock()
      engine.memory_manager.load_persisted_user_message.return_value = "Hello"
      
      # Mock Groq client failure
      engine.groq_manager.chat_completion = MagicMock(side_effect=Exception("Groq error"))
      
      ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
      
      with caplog.at_level(logging.ERROR):
          await engine.run_archival_extraction(ref)
          
      assert "archival_extraction_llm_failed" in caplog.text
      # Check sensitive values are not logged
      assert "user123" not in caplog.text
      assert "Hello" not in caplog.text
      assert "Groq error" not in caplog.text
      engine.memory_manager.store_archival_extraction.assert_not_called()

  @pytest.mark.anyio
  async def test_run_archival_extraction_validation_failure(caplog):
      engine = ConversationEngine()
      engine.memory_manager = MagicMock()
      engine.memory_manager.load_persisted_user_message.return_value = "Hello"
      
      # Mock Groq client returning invalid fact payload (importance is bool)
      m = MagicMock()
      m.choices = [MagicMock()]
      m.choices[0].message.content = json.dumps({
          "facts": [{"content": "hello", "importance": True, "tags": []}]
      })
      engine.groq_manager.chat_completion = MagicMock(return_value=m)
      
      ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
      
      with caplog.at_level(logging.WARNING):
          await engine.run_archival_extraction(ref)
          
      assert "archival_extraction_invalid" in caplog.text
      assert "user123" not in caplog.text
      engine.memory_manager.store_archival_extraction.assert_not_called()

  @pytest.mark.anyio
  async def test_run_archival_extraction_duplicate(caplog):
      engine = ConversationEngine()
      engine.memory_manager = MagicMock()
      engine.memory_manager.load_persisted_user_message.return_value = "Hello"
      
      m = MagicMock()
      m.choices = [MagicMock()]
      m.choices[0].message.content = json.dumps({
          "facts": [{"content": "likes coding", "importance": 0.9, "tags": []}],
          "schema_version": 1,
          "extractor_version": 1
      })
      engine.groq_manager.chat_completion = MagicMock(return_value=m)
      
      # Simulate unique constraint failure treated as duplicate success
      class PostgrestAPIError(Exception):
          def __init__(self):
              self.code = "23505"
      engine.memory_manager.store_archival_extraction.side_effect = PostgrestAPIError()
      
      ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
      
      with caplog.at_level(logging.INFO):
          await engine.run_archival_extraction(ref)
          
      assert "archival_extraction_duplicate" in caplog.text
      assert "user123" not in caplog.text
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_integration.py -v`
  Expected: FAIL with AttributeError or import error.

- [ ] **Step 3: Implement orchestrator and integration**
  Modify `backend/engine.py`:
  Add imports:
  ```python
  from typing import Optional
  from fastapi import BackgroundTasks
  from .archival_memory import (
      PersistedTurnRef,
      parse_archival_extraction,
      compute_idempotency_key,
      EXTRACTOR_VERSION,
      ArchivalValidationError
  )
  ```

  Add background task method `run_archival_extraction` inside `ConversationEngine` class:
  ```python
      async def run_archival_extraction(self, turn_ref: PersistedTurnRef):
          # 1. Load user message content
          try:
              user_message = await asyncio.to_thread(
                  self.memory_manager.load_persisted_user_message,
                  turn_ref.user_id,
                  turn_ref.source_chat_log_id
              )
          except Exception:
              # Simply fail closed silently since load failed
              return

          # 2. Call LLM to extract facts
          prompt = f"""
          Extract facts from this user message for archival memory.
          Facts should be significant, long-term personal details about the user (e.g. preferences, habits, facts, background).
          Return JSON ONLY matching the following schema:
          {{
              "facts": [
                  {{
                      "content": "Fact description (max 500 chars)",
                      "importance": 0.0 to 1.0 (float),
                      "tags": ["lowercase-tag-1", "lowercase-tag-2"] (max 8 tags per fact, each tag max 32 chars matching ^[a-z0-9][a-z0-9_-]*$)
                  }}
              ],
              "schema_version": 1,
              "extractor_version": 1
          }}
          Maximum of 5 facts. If no relevant facts are found, return an empty facts list.
          Do not include any other markdown formatting outside the JSON code block.

          User message: "{user_message}"
          """

          try:
              chat_completion = await asyncio.to_thread(
                  self.groq_manager.chat_completion,
                  messages=[{"role": "user", "content": prompt}],
                  model=self.model_fast,
                  temperature=0.0,
                  response_format={"type": "json_object"}
              )
              response_text = chat_completion.choices[0].message.content
              raw_envelope = json.loads(response_text)
          except Exception:
              logger.error("Event: archival_extraction_llm_failed")
              return

          # 3. Validate raw facts envelope
          try:
              envelope = parse_archival_extraction(raw_envelope)
          except ArchivalValidationError:
              logger.warning("Event: archival_extraction_invalid")
              return
          except Exception:
              logger.warning("Event: archival_extraction_invalid")
              return

          # 4. Generate idempotency key and store
          idempotency_key = compute_idempotency_key(
              turn_ref.user_id,
              turn_ref.source_chat_log_id,
              EXTRACTOR_VERSION
          )

          try:
              await asyncio.to_thread(
                  self.memory_manager.store_archival_extraction,
                  turn_ref.user_id,
                  turn_ref.source_chat_log_id,
                  idempotency_key,
                  envelope
              )
          except Exception as e:
              # Check for Postgres 23505 unique violation in case it bubbled up
              err_code = getattr(e, "code", None)
              if err_code == "23505":
                  logger.info("Event: archival_extraction_duplicate")
              else:
                  logger.error("Event: archival_extraction_store_failed")
  ```

  Modify `process_turn()` signature and implementation in `ConversationEngine` (lines 22-86):
  ```python
      async def process_turn(self, user_id: str, user_message: str, background_tasks: Optional[BackgroundTasks] = None):
          async def run_under_lock():
              current_time = time.time()

              # 1. Load State from Supabase (Offloaded to thread)
              # Raises StateLoadError on DB failure
              user_state = await asyncio.to_thread(self.memory_manager.load_user_state, user_id)

              # Hydrate Emotional State
              emotional_state = EmotionalState.from_dict(user_state.get("emotional_state", {}))

              # Hydrate Relationship State - Enforce authenticated user_id
              rel_data = user_state.get("relationship_state")
              if rel_data:
                  relationship = UserRelationship.from_dict(rel_data, user_id=user_id)
              else:
                  relationship = UserRelationship(user_id=user_id)

              # 2. Perception & Memory Retrieval
              context = await asyncio.to_thread(self.memory_manager.get_context, user_id, user_message, user_state)

              # 3. Analyze Intent & Sentiment (LLM Perception)
              raw_perception = await asyncio.to_thread(self._perceive, user_message)
              perception = self._normalize_perception(raw_perception)

              # 4. Update Emotional State & Relationship (Local computations)
              new_state, coping_instruction = self.affective_engine.update_state(
                  emotional_state,
                  user_message,
                  current_time=current_time,
                  perception_override=perception
              )
              relationship = self.relationship_manager.update_relationship(relationship, perception)

              # 5. Meta-Cognition: DEACTIVATED as per P0 instructions
              adaptation_strategy = ""

              # 6. Generate Response (LLM call offloaded to thread)
              system_prompt = self._build_system_prompt(new_state, context, relationship, adaptation_strategy, coping_instruction)

              try:
                  chat_completion = await asyncio.to_thread(
                      self.groq_manager.chat_completion,
                      messages=[
                          {"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_message}
                      ],
                      model=self.model_main,
                      temperature=0.8,
                      max_tokens=200,
                  )
                  response_text = chat_completion.choices[0].message.content
              except Exception:
                  response_text = "*suspiro cansado* Sinto que minha mente está um pouco nublada agora... Podemos tentar de novo em alguns segundos?"

              # 7. Post-processing & Storage (Offloaded to thread)
              # Await critical turn persistence synchronously inside the lock (do not use BackgroundTasks)
              turn_ref = await asyncio.to_thread(self.memory_manager.save_turn, user_id, user_message, response_text)

              # CRITICAL: sync_state MUST complete before releasing lock.
              # Raises StatePersistenceError on failure.
              await asyncio.to_thread(self.memory_manager.sync_state, user_id, new_state, relationship)

              # Schedule background task only after save_turn and sync_state have successfully completed
              if background_tasks:
                  background_tasks.add_task(self.run_archival_extraction, turn_ref)

              return response_text, new_state.to_dict()

          async with self.lock_manager.lock(user_id):
              task = asyncio.create_task(run_under_lock())
              try:
                  return await asyncio.shield(task)
              except asyncio.CancelledError:
                  # If we get CancelledError, the caller cancelled process_turn.
                  # We must wait for task to complete, shielding it even against subsequent cancellations.
                  while not task.done():
                      try:
                          # Shield the task again to prevent cancellations from stopping this await
                          await asyncio.shield(task)
                      except asyncio.CancelledError:
                          # A second/subsequent cancel arrived. Consume it, but keep waiting until task is done.
                          pass
                      except Exception:
                          # Other exceptions from the task are caught and ignored here because we want to propagate CancelledError
                          break
                  raise
  ```

  Modify `backend/main.py`:
  Add import:
  `from fastapi import BackgroundTasks`

  Update chat endpoint:
  ```python
  @app.post("/chat", response_model=ChatResponse)
  async def chat_endpoint(
      input_data: ChatInput,
      background_tasks: BackgroundTasks,
      current_user = Depends(get_current_user)
  ):
      try:
          user_id = current_user.id
          response_text, current_emotion = await engine.process_turn(user_id, input_data.message, background_tasks)
          return ChatResponse(response=response_text, emotion_state=current_emotion)
      except Exception:
          # Sanitize logging: avoid logging raw exceptions that might contain secrets or tracebacks
          logger.error("Event: Chat Turn Failure")
          raise HTTPException(status_code=500, detail="Internal Server Error")
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_archival_memory_integration.py -v`
  Expected: PASS

- [ ] **Step 5: Run full test suite**
  Run: `PYTHONPATH=. .venv/bin/pytest -v`
  Expected: ALL tests pass

- [ ] **Step 6: Commit**
  Run:
  ```bash
  git add backend/engine.py backend/main.py backend/tests/test_archival_memory_integration.py
  git commit -m "feat(memory): integrate archival extraction task into engine and chat endpoint"
  ```
