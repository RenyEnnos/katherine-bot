# Isolate Emotional State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct all remaining user-state isolation blockers in Katherine Bot to ensure strict emotional/relational isolation per authenticated user, fail-closed persistence, robust lock safety, and clean test suite passing.

**Architecture:** Use the authenticated `user_id` as the sole source of truth for loading, updating, and saving user state/relationship. Implement structured, sanitized custom errors (`StateLoadError`, `StatePersistenceError`) and clean input normalizations to enforce fail-closed behavior.

**Tech Stack:** Python 3.12, FastAPI, Supabase, pytest.

## Global Constraints
- State of A must never contaminate B.
- Any user_id inside Supabase JSON must be ignored; the authenticated user_id from process_turn prevails.
- Failures in read/write must not recover silently to default states or hide errors.
- Lock manager must clean up lock references under any scenario (success, error, cancellation).
- No secrets, raw DB messages, or user IDs are allowed in exception messages, logs, or HTTP responses.

---

### Task 1: Relational Identity Identity Check
**Files:**
- Modify: `backend/relationship.py:21-31`
- Modify: `backend/engine.py:31-35`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: Authenticated `user_id` in `process_turn`.
- Produces: `UserRelationship.from_dict(data: Dict, user_id: str) -> UserRelationship`.

- [ ] **Step 1: Write failing test for relational identity mismatch**
  Add the following test to `backend/tests/test_isolation.py`:
  ```python
  def test_relational_identity_adulterated():
      from backend.relationship import UserRelationship
      # Simulated state has B, but authenticated user is A
      raw_data = {"user_id": "user-B", "trust": 0.8, "affection": 0.9}
      rel = UserRelationship.from_dict(raw_data, user_id="user-A")
      assert rel.user_id == "user-A"
      assert rel.trust == 0.8
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_relational_identity_adulterated`
  Expected: Fail/Error (since from_dict doesn't accept user_id argument yet).
- [ ] **Step 3: Modify UserRelationship.from_dict and Call Site**
  Update `backend/relationship.py`:
  ```python
      @staticmethod
      def from_dict(data: Dict, user_id: str):
          rel = UserRelationship(user_id=user_id)
          rel.trust = data.get("trust", 0.5)
          rel.affection = data.get("affection", 0.3)
          rel.tension = data.get("tension", 0.0)
          rel.bond_label = data.get("bond_label", "Conhecidos")
          rel.triggers = data.get("triggers", [])
          rel.last_interaction = data.get("last_interaction", time.time())
          return rel
  ```
  Update `backend/engine.py` line 32:
  ```python
              if user_state.get("relationship_state"):
                  relationship = UserRelationship.from_dict(user_state["relationship_state"], user_id=user_id)
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_relational_identity_adulterated`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/relationship.py backend/engine.py; git commit -m "fix(emotion): enforce authenticated user_id on relationship load"`

---

### Task 2: Fail-Closed Read Implementation
**Files:**
- Modify: `backend/memory.py:18-77`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: Supabase database connection and `user_id`.
- Produces: `StateLoadError` exception, `MemoryManager.load_user_state(user_id: str) -> dict`.

- [ ] **Step 1: Write failing tests for read failures**
  Add these to `backend/tests/test_isolation.py`:
  ```python
  from backend.memory import StateLoadError
  
  def test_read_failure_raises_stateloaderror():
      from backend.memory import MemoryManager
      from unittest.mock import MagicMock
      mgr = MemoryManager()
      mgr.supabase = MagicMock()
      mgr.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("SECRET_TOKEN")
      
      with pytest.raises(StateLoadError) as exc_info:
          mgr.load_user_state("user-123")
      assert "SECRET_TOKEN" not in str(exc_info.value)
      assert "user-123" not in str(exc_info.value)
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_read_failure_raises_stateloaderror`
  Expected: Fail (raises default state instead of StateLoadError).
- [ ] **Step 3: Modify MemoryManager.load_user_state and add StateLoadError**
  Modify `backend/memory.py`:
  ```python
  class StateLoadError(Exception):
      """Exception raised when user state cannot be loaded safely."""
      def __init__(self, message="Falha ao carregar estado do usuário"):
          self.message = message
          super().__init__(self.message)
  ```
  And update `load_user_state`:
  ```python
      def load_user_state(self, user_id: str) -> dict:
          if not self.supabase:
              raise StateLoadError("Serviço de persistência indisponível.")
          try:
              response = self.supabase.table("profiles").select("*").eq("user_id", user_id).execute()
          except Exception as e:
              raise StateLoadError("Erro ao recuperar perfil do banco de dados.") from e
  
          if response is None or not hasattr(response, "data") or response.data is None:
              raise StateLoadError("Resposta inválida do serviço de persistência.")
  
          if len(response.data) == 0:
              default_state = self._get_default_state(user_id)
              try:
                  insert_resp = self.supabase.table("profiles").insert({
                      "user_id": user_id,
                      "persona_config": default_state["persona_config"],
                      "user_profile": default_state["user_profile"],
                      "relationship_state": default_state["relationship_state"],
                      "emotional_state": default_state["emotional_state"]
                  }).execute()
              except Exception as e:
                  raise StateLoadError("Falha ao inicializar perfil padrão.") from e
  
              if insert_resp is None or not hasattr(insert_resp, "data") or not insert_resp.data:
                  raise StateLoadError("Falha ao salvar perfil padrão criado.")
              return default_state
  
          try:
              data = response.data[0]
              return {
                  "persona_config": data.get("persona_config"),
                  "user_profile": data.get("user_profile") or {},
                  "relationship_state": data.get("relationship_state") or {},
                  "emotional_state": data.get("emotional_state") or {}
              }
          except Exception as e:
              raise StateLoadError("Erro ao processar dados de perfil.") from e
  ```
- [ ] **Step 4: Run tests to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_read_failure_raises_stateloaderror`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/memory.py; git commit -m "fix(memory): make user state loading fail-closed on error"`

---

### Task 3: Fail-Closed Write & Validation
**Files:**
- Modify: `backend/memory.py:86-117`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: Supabase connection, `user_id`, states to persist.
- Produces: `StatePersistenceError` on zero rows updated.

- [ ] **Step 1: Write failing test for zero rows updated**
  Add to `backend/tests/test_isolation.py`:
  ```python
  def test_zero_rows_updated_raises_statepersistenceerror():
      from backend.memory import MemoryManager, StatePersistenceError
      from unittest.mock import MagicMock
      mgr = MemoryManager()
      mgr.supabase = MagicMock()
      
      # Mock update return with empty data list (data=[])
      mock_response = MagicMock()
      mock_response.data = []
      mock_response.error = None
      mgr.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_response
      
      from backend.emotional_core import EmotionalState
      from backend.relationship import UserRelationship
      with pytest.raises(StatePersistenceError):
          mgr.sync_state("user-123", EmotionalState(), UserRelationship(user_id="user-123"))
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_zero_rows_updated_raises_statepersistenceerror`
  Expected: Fail.
- [ ] **Step 3: Modify MemoryManager.sync_state**
  Update `sync_state` in `backend/memory.py`:
  ```python
      def sync_state(self, user_id: str, emotional_state: EmotionalState, relationship: UserRelationship, user_profile: dict = None):
          if not self.supabase:
              raise StatePersistenceError("Serviço de persistência não configurado.")
  
          update_data = {
              "emotional_state": emotional_state.to_dict(),
              "relationship_state": relationship.to_dict(),
              "updated_at": datetime.utcnow().isoformat()
          }
          if user_profile:
              update_data["user_profile"] = user_profile
  
          try:
              response = self.supabase.table("profiles").update(update_data).eq("user_id", user_id).execute()
              if response is None:
                  raise StatePersistenceError("Sem resposta da base de dados.")
              if hasattr(response, 'error') and response.error:
                  raise StatePersistenceError("Erro retornado pelo banco de dados.")
              if not hasattr(response, 'data') or response.data is None or len(response.data) == 0:
                  raise StatePersistenceError("Nenhuma linha foi atualizada no banco de dados.")
          except StatePersistenceError:
              raise
          except Exception as e:
              raise StatePersistenceError("Falha na gravação do estado.") from e
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_zero_rows_updated_raises_statepersistenceerror`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/memory.py; git commit -m "fix(memory): sync_state fails on zero rows updated"`

---

### Task 4: Perception Normalization
**Files:**
- Modify: `backend/engine.py`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: Raw input JSON/dict from LLM.
- Produces: Normalized dict matching `_normalize_perception(payload)`.

- [ ] **Step 1: Write failing test for various malformed payloads**
  Add `test_normalize_perception` in `backend/tests/test_isolation.py`:
  ```python
  def test_normalize_perception():
      from backend.engine import _normalize_perception
      import math
      
      # None payload
      res = _normalize_perception(None)
      assert res["valence"] == 0.0
      assert res["triggered_emotions"]["joy"] == 0.0
      
      # Malformed valence types (bool, string, nan, inf)
      res = _normalize_perception({"valence": True, "arousal_shift": "invalid", "dominance_shift": float('nan')})
      assert res["valence"] == 0.0
      assert res["arousal_shift"] == 0.0
      assert res["dominance_shift"] == 0.0
      
      # Out of bounds
      res = _normalize_perception({"valence": 2.5, "triggered_emotions": {"joy": -0.5, "sadness": 1.5}})
      assert res["valence"] == 1.0
      assert res["triggered_emotions"]["joy"] == 0.0
      assert res["triggered_emotions"]["sadness"] == 1.0
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_normalize_perception`
  Expected: Fail.
- [ ] **Step 3: Implement _normalize_perception**
  Add to `backend/engine.py` as a standalone helper or module-level function:
  ```python
  import math
  
  def _normalize_perception(payload) -> dict:
      emotions_list = ["joy", "sadness", "anger", "fear", "disgust", "surprise", "tenderness", "guilt", "pride", "jealousy", "gratitude"]
      default_emotions = {emo: 0.0 for emo in emotions_list}
      
      default_res = {
          "valence": 0.0,
          "arousal_shift": 0.0,
          "dominance_shift": 0.0,
          "triggered_emotions": default_emotions
      }
      
      if not isinstance(payload, dict):
          return default_res
          
      res = default_res.copy()
      res["triggered_emotions"] = default_emotions.copy()
      
      def clean_shift(val):
          if isinstance(val, bool): # bool inherits from int
              return 0.0
          if not isinstance(val, (int, float)):
              return 0.0
          if not math.isfinite(val):
              return 0.0
          return max(-1.0, min(1.0, float(val)))
          
      res["valence"] = clean_shift(payload.get("valence"))
      res["arousal_shift"] = clean_shift(payload.get("arousal_shift"))
      res["dominance_shift"] = clean_shift(payload.get("dominance_shift"))
      
      raw_emotions = payload.get("triggered_emotions")
      if isinstance(raw_emotions, dict):
          for emo in emotions_list:
              val = raw_emotions.get(emo)
              if isinstance(val, bool):
                  clean_val = 0.0
              elif isinstance(val, (int, float)) and math.isfinite(val):
                  clean_val = max(0.0, min(1.0, float(val)))
              else:
                  clean_val = 0.0
              res["triggered_emotions"][emo] = clean_val
              
      return res
  ```
  And update `backend/engine.py` line 40:
  ```python
              # 3. Analyze Intent & Sentiment (LLM Perception - offloaded to thread)
              raw_perception = await asyncio.to_thread(self._perceive, user_message)
              perception = _normalize_perception(raw_perception)
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_normalize_perception`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/engine.py; git commit -m "feat(engine): add fail-closed perception normalization"`

---

### Task 5: AffectiveEngine Defensive Core
**Files:**
- Modify: `backend/emotional_core.py:144-147`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: `perception_override` dictionary in `update_state`.
- Produces: Clamp and validated shifts preventing exceptions.

- [ ] **Step 1: Write failing test for AffectiveEngine overrides**
  Add to `backend/tests/test_isolation.py`:
  ```python
  def test_affective_engine_defensiveness():
      from backend.emotional_core import AffectiveEngine, EmotionalState
      engine = AffectiveEngine()
      state = EmotionalState()
      
      # Call update_state with unsafe override shifts (None, bool, NaN)
      override = {"valence": None, "arousal_shift": True, "dominance_shift": float('inf')}
      new_state, _ = engine.update_state(state, "Hello", time.time(), perception_override=override)
      
      assert isinstance(new_state.pleasure, float)
      assert new_state.pleasure == 0.0
      assert new_state.arousal == 0.0
      assert new_state.dominance == 0.0
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_affective_engine_defensiveness`
  Expected: Fail (TypeError on summing shifts).
- [ ] **Step 3: Modify AffectiveEngine.update_state shifts extraction**
  Update `backend/emotional_core.py`:
  ```python
      def update_state(self, state: EmotionalState, user_input: str, current_time: float, perception_override: Optional[Dict] = None) -> Tuple[EmotionalState, str]:
          state = self._apply_time_decay(state, current_time)
          shifts = self.occ.evaluate(user_input, state)
          
          def get_override_shift(key):
              if not perception_override:
                  return 0.0
              val = perception_override.get(key)
              if isinstance(val, bool):
                  return 0.0
              if not isinstance(val, (int, float)):
                  return 0.0
              import math
              if not math.isfinite(val):
                  return 0.0
              return float(val)
  
          p_final_shift = shifts["p_shift"] + get_override_shift("valence")
          a_final_shift = shifts["a_shift"] + get_override_shift("arousal_shift")
          d_final_shift = shifts["d_shift"] + get_override_shift("dominance_shift")
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_affective_engine_defensiveness`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/emotional_core.py; git commit -m "fix(emotion): add defense in AffectiveEngine update_state"`

---

### Task 6: UserLockManager Robustness
**Files:**
- Modify: `backend/lock_manager.py:14-38`
- Test: `backend/tests/test_isolation.py`

**Interfaces:**
- Consumes: `user_id` inside `UserLockManager.lock(user_id)`.
- Produces: Safe lock acquisition under tasks, errors, and cancellations.

- [ ] **Step 1: Write failing test for cancellation during lock wait**
  Add to `backend/tests/test_isolation.py`:
  ```python
  def test_lock_cleanup_on_cancellation_during_wait():
      async def run_test():
          from backend.lock_manager import UserLockManager
          import asyncio
          mgr = UserLockManager()
          user_id = "test_cancel_user"
          
          task1_entered = asyncio.Event()
          task2_started = asyncio.Event()
          
          async def t1():
              async with mgr.lock(user_id):
                  task1_entered.set()
                  await asyncio.sleep(5)
                  
          async def t2():
              task2_started.set()
              async with mgr.lock(user_id):
                  pass
                  
          task1 = asyncio.create_task(t1())
          await task1_entered.wait()
          
          task2 = asyncio.create_task(t2())
          await task2_started.wait()
          await asyncio.sleep(0.1) # Let task2 wait on user_lock
          
          task2.cancel()
          try:
              await task2
          except asyncio.CancelledError:
              pass
              
          task1.cancel()
          try:
              await task1
          except asyncio.CancelledError:
              pass
              
          async with mgr._dict_lock:
              assert user_id not in mgr._locks
  
      asyncio.run(run_test())
  ```
- [ ] **Step 2: Run test to verify it fails**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_lock_cleanup_on_cancellation_during_wait`
  Expected: Fail (reference count is not cleaned up correctly, user_id remains in dict).
- [ ] **Step 3: Modify UserLockManager.lock**
  Update `backend/lock_manager.py`:
  ```python
      @asynccontextmanager
      async def lock(self, user_id: str):
          registered = False
          user_lock = None
          try:
              async with self._dict_lock:
                  if user_id not in self._locks:
                      self._locks[user_id] = [asyncio.Lock(), 0]
                  self._locks[user_id][1] += 1
                  user_lock = self._locks[user_id][0]
                  registered = True
  
              async with user_lock:
                  yield
          finally:
              if registered:
                  async with self._dict_lock:
                      if user_id in self._locks:
                          self._locks[user_id][1] -= 1
                          if self._locks[user_id][1] <= 0:
                              del self._locks[user_id]
  ```
- [ ] **Step 4: Run test to verify it passes**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_isolation.py -k test_lock_cleanup_on_cancellation_during_wait`
  Expected: Pass.
- [ ] **Step 5: Commit**
  Run: `git add backend/lock_manager.py; git commit -m "fix(lock): secure lock manager reference count in try/finally"`

---

### Task 7: Comprehensive Integration Testing & Verification
**Files:**
- Modify/Create: `backend/tests/test_isolation.py` (Add missing edge cases: concurrency, exceptions sanitization, etc.)
- Run: Complete verification scripts

- [ ] **Step 1: Write integration tests for remaining cases in backend/tests/test_isolation.py**
  Add test for reading/writing exceptions sanitization, non-existant profile default, concurrent requests from different users, and persistence before return.
- [ ] **Step 2: Run all backend tests**
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests -v`
  Expected: All tests pass.
- [ ] **Step 3: Compile backend code**
  Run: `python3 -m compileall -q backend`
  Expected: Success.
- [ ] **Step 4: Verify frontend linting and build**
  Run: `npm --prefix frontend ci; npm --prefix frontend run lint; npm --prefix frontend run build`
  Expected: Success.
- [ ] **Step 5: Check git diff**
  Run: `git diff --check`
  Expected: Success.
