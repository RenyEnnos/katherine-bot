# Ordered Persisted Turn History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove user-specific conversation history from process-wide `MemoryManager` memory, load recent history deterministically from Supabase `chat_logs` using a stable tie-breaker, and persist turns synchronously inside the per-user lock.

**Architecture:** Retrieve user chat history by querying Supabase `chat_logs` with ordering by `created_at` and `id` (primary key, stable tie-breaker), reversing the list in memory. Perform all turn writes inside the user lock in `engine.py` without using FastAPI `BackgroundTasks`. Raise sanitized `ContextLoadError` and `TurnPersistenceError` upon DB failures.

**Tech Stack:** Python, FastAPI, Supabase client, Pytest.

## Global Constraints
- No user-specific conversation content remains in a process-wide mutable attribute.
- Recent context is loaded from authorized persistence with a strict limit and deterministic ordering.
- The next turn from the same user always observes the previous critical turn write.
- FastAPI `BackgroundTasks` is not responsible for critical persistence.
- Legacy unsafe extraction and compression are not executed or left as reusable unsafe paths.
- Database failures are explicit, sanitized, and tested.
- All backend and frontend CI checks pass.
- No regression is introduced in cancellation, per-user locking, authentication, emotional persistence, or user isolation.

---

### Task 1: Refactoring MemoryManager in `backend/memory.py`

**Files:**
- Modify: `backend/memory.py`
- Test: `backend/tests/test_ordered_persisted_turn_history.py`

**Interfaces:**
- Consumes: None (Core dependency file)
- Produces:
  - `ContextLoadError(Exception)`
  - `TurnPersistenceError(Exception)`
  - `MemoryManager.load_recent_history(user_id: str, limit: int = 10) -> list[dict]`
  - `MemoryManager.get_context(user_id: str, current_message: str, user_state: dict) -> str`
  - `MemoryManager.save_turn(user_id: str, user_msg: str, bot_msg: str) -> None`

- [ ] **Step 1: Write the failing tests for MemoryManager database operations and exception handling**
  Create a new file `backend/tests/test_ordered_persisted_turn_history.py` containing tests that verify the new methods and error handling.
  ```python
  import pytest
  from unittest.mock import MagicMock
  from backend.memory import MemoryManager, ContextLoadError, TurnPersistenceError

  def test_memory_manager_has_no_short_term_memory():
      mm = MemoryManager()
      assert not hasattr(mm, 'short_term_memory')

  def test_load_recent_history_validation_failures():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      
      # Mock None response
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = None
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Mock error attribute
      mock_resp = MagicMock()
      mock_resp.error = "database error"
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

  def test_save_turn_zero_inserted_rows():
      mm = MemoryManager()
      mm.supabase = MagicMock()
      mock_resp = MagicMock()
      mock_resp.data = [] # zero inserted rows
      mock_resp.error = None
      mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
      with pytest.raises(TurnPersistenceError):
          mm.save_turn("user123", "hi", "hello")
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_ordered_persisted_turn_history.py -v`
  Expected: FAIL (ImportError or AttributeError because the exceptions or methods are not implemented yet)

- [ ] **Step 3: Modify `backend/memory.py` to define exceptions, delete short-term memory dictionary, implement `load_recent_history`, refactor `get_context` and `save_turn`, and delete legacy compression/extraction routines.**
  Update `backend/memory.py`:
  - Define `ContextLoadError` and `TurnPersistenceError`.
  - Remove `self.short_term_memory` from `__init__`.
  - Implement `load_recent_history`:
    ```python
    def load_recent_history(self, user_id: str, limit: int = 10) -> list:
        if not self.supabase:
            raise ContextLoadError("Serviço de persistência indisponível.")
        try:
            response = self.supabase.table("chat_logs")\
                .select("role, content")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .order("id", desc=True)\
                .limit(limit)\
                .execute()
            if response is None:
                raise ContextLoadError("Sem resposta do banco de dados na leitura do histórico.")
            if hasattr(response, 'error') and response.error:
                raise ContextLoadError("Erro retornado pelo banco de dados na leitura do histórico.")
            if not hasattr(response, 'data') or response.data is None:
                raise ContextLoadError("Resposta inválida do banco de dados na leitura do histórico.")
            return response.data[::-1]
        except ContextLoadError:
            raise
        except Exception:
            raise ContextLoadError("Falha ao carregar histórico de conversação.") from None
    ```
  - Refactor `get_context`:
    ```python
    def get_context(self, user_id: str, current_message: str, user_state: dict):
        history = self.load_recent_history(user_id, limit=10)
        short_term_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
        relevant_memories = self._retrieve_relevant(user_id, current_message)
        context_str = f"""
        === CORE MEMORY (QUEM VOCÊ É) ===
        {user_state.get('persona_config', 'Katherine...')}

        === CORE MEMORY (QUEM É O USUÁRIO) ===
        {user_state.get('user_profile', {})}

        === MEMÓRIA ARQUIVADA (LEMBRANÇAS RELEVANTES) ===
        {relevant_memories}

        === CONVERSA ATUAL (CURTO PRAZO) ===
        {short_term_str}
        """
        return context_str
    ```
  - Refactor `save_turn`:
    ```python
    def save_turn(self, user_id: str, user_msg: str, bot_msg: str):
        if not self.supabase:
            raise TurnPersistenceError("Serviço de persistência indisponível.")
        try:
            response = self.supabase.table("chat_logs").insert([
                {"user_id": user_id, "role": "user", "content": user_msg},
                {"user_id": user_id, "role": "assistant", "content": bot_msg}
            ]).execute()
            if response is None:
                raise TurnPersistenceError("Sem resposta do banco de dados ao salvar turno.")
            if hasattr(response, 'error') and response.error:
                raise TurnPersistenceError("Erro retornado pelo banco de dados ao salvar turno.")
            if not hasattr(response, 'data') or response.data is None or len(response.data) == 0:
                raise TurnPersistenceError("Falha na gravação do turno: nenhum registro inserido.")
        except TurnPersistenceError:
            raise
        except Exception:
            raise TurnPersistenceError("Falha ao persistir turno de conversação.") from None
    ```
  - Delete `_compress_episodes`, `_analyze_and_store`, `_store_memory`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_ordered_persisted_turn_history.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add backend/memory.py backend/tests/test_ordered_persisted_turn_history.py
  git commit -m "feat(memory): remove memory manager in-memory history, add DB-backed load_recent_history and validated save_turn"
  ```

---

### Task 2: Refactoring ConversationEngine in `backend/engine.py`

**Files:**
- Modify: `backend/engine.py`
- Test: `backend/tests/test_ordered_persisted_turn_history.py`

**Interfaces:**
- Consumes:
  - `MemoryManager.save_turn(user_id: str, user_msg: str, bot_msg: str)`
- Produces:
  - `ConversationEngine.process_turn(user_id: str, user_message: str, background_tasks=None) -> tuple[str, dict]`

- [ ] **Step 1: Write a failing test for synchronous persistence inside per-user lock**
  Add a test to `backend/tests/test_ordered_persisted_turn_history.py` verifying that `process_turn` awaits `save_turn` inside the lock.
  ```python
  import asyncio
  from unittest.mock import MagicMock, patch
  from backend.engine import ConversationEngine

  @pytest.mark.asyncio
  async def test_process_turn_awaits_save_turn_inside_lock():
      engine = ConversationEngine()
      engine.memory_manager.load_user_state = MagicMock(return_value={})
      engine.memory_manager.sync_state = MagicMock()
      engine._perceive = MagicMock(return_value={})
      
      mock_chat = MagicMock()
      mock_chat.choices = [MagicMock()]
      mock_chat.choices[0].message.content = "Bot reply"
      engine.groq_manager.chat_completion = MagicMock(return_value=mock_chat)

      # We track save_turn execution
      save_turn_called = False
      async def slow_save_turn(*args, **kwargs):
          nonlocal save_turn_called
          await asyncio.sleep(0.1)
          save_turn_called = True

      with patch.object(engine.memory_manager, 'save_turn', side_effect=lambda *a, **kw: asyncio.run(slow_save_turn(*a, **kw))):
          # We call process_turn
          t = asyncio.create_task(engine.process_turn("user123", "Hello"))
          
          # Check lock is held and save_turn is not yet complete but started/awaited
          await asyncio.sleep(0.02)
          async with engine.lock_manager._dict_lock:
              # Lock should still be held for user123 since slow_save_turn is sleeping
              assert "user123" in engine.lock_manager._locks
          
          await t
          assert save_turn_called
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_ordered_persisted_turn_history.py::test_process_turn_awaits_save_turn_inside_lock -v`
  Expected: FAIL (because save_turn is scheduled on BackgroundTasks if background_tasks argument is mock-passed, or uses background_tasks check)

- [ ] **Step 3: Modify `backend/engine.py`**
  Update `backend/engine.py` lines 78-81:
  Remove the background tasks check and directly call:
  ```python
  # 7. Post-processing & Storage (Offloaded to thread)
  # Await critical turn persistence synchronously inside the lock (do not use BackgroundTasks)
  await asyncio.to_thread(self.memory_manager.save_turn, user_id, user_message, response_text)
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_ordered_persisted_turn_history.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add backend/engine.py backend/tests/test_ordered_persisted_turn_history.py
  git commit -m "feat(engine): await turn persistence inside user lock, remove FastAPI BackgroundTasks from save_turn"
  ```

---

### Task 3: Comprehensive Integration Tests and Cleanups

**Files:**
- Modify: `backend/tests/test_ordered_persisted_turn_history.py`
- Modify: `backend/tests/test_isolation.py` (update any failing tests due to short_term_memory removal)

**Interfaces:**
- Consumes:
  - `MemoryManager`
  - `ConversationEngine`
- Produces:
  - Full suite of validation tests passing locally

- [ ] **Step 1: Write all remaining required tests in `backend/tests/test_ordered_persisted_turn_history.py`**
  Write tests for:
  - User isolation: User A never receives history belonging to User B (verify `.eq("user_id", ...)`).
  - Equal timestamps producing deterministic ordering via stable tie-breaker `id`.
  - Recreating `ConversationEngine` does not lose recent context.
  - Failures and logs containing no conversation content or identifiers.
  - Empty, None, or zero-row insert responses failing explicitly.

- [ ] **Step 2: Run all tests in the repository**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/`
  Expected: PASS

- [ ] **Step 3: Commit and finalize**
  ```bash
  git add backend/tests/
  git commit -m "test(memory): add comprehensive tests for deterministic ordering, user isolation, and sanitized DB failures"
  ```
