# Turn History Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure that the conversation history loaded from the database is structurally valid, normalized, has a message size limit, fails closed safely with `ContextLoadError` upon any malformation, and that HTTP contract assertions for authentication tests are restored.

**Architecture:** Imperative structural validation loop inside `load_recent_history()` in `backend/memory.py`. Normalizing responses into a strict schema of `[{"role": str, "content": str}]`. Asserting on specific mock response properties in HTTP tests.

**Tech Stack:** Python 3.12, Supabase client, Pytest

## Global Constraints
- Do not use third-party validation libraries (like Pydantic) for validation inside memory.py to avoid overhead.
- All malformed data must raise `ContextLoadError` and be sanitized of user/db details.
- No modifications to files outside the specified scope.
- Do not edit `.Jules/palette.md`.

---

### Task 1: Add Structural Validation and Normalization to `load_recent_history`

**Files:**
- Modify: `backend/memory.py:159-207`

**Interfaces:**
- Consumes: Supabase database response object.
- Produces: `normalized` Turn history list. `load_recent_history(self, user_id: str, limit: int = 10) -> list`

- [ ] **Step 1: Define MAX_MESSAGE_LENGTH constant**
  Verify or add the module-level constant:
  ```python
  MAX_MESSAGE_LENGTH = 10000  # Limite máximo de caracteres por mensagem no histórico para evitar sobrecarga de contexto
  ```

- [ ] **Step 2: Add validation logic to `load_recent_history`**
  Modify `load_recent_history` in `backend/memory.py`:
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
              if not isinstance(response.data, list):
                  raise ContextLoadError("Resposta do banco de dados não é uma lista.")

              normalized = []
              for item in response.data:
                  if not isinstance(item, dict):
                      raise ContextLoadError("Item do histórico não é um dicionário.")
                  if "role" not in item or "content" not in item:
                      raise ContextLoadError("Item do histórico não possui as chaves obrigatórias 'role' e 'content'.")
                  role = item["role"]
                  content = item["content"]
                  if role not in ("user", "assistant"):
                      raise ContextLoadError("Role inválida no histórico recente.")
                  if not isinstance(content, str):
                      raise ContextLoadError("Conteúdo da mensagem não é uma string.")
                  if len(content) > MAX_MESSAGE_LENGTH:
                      raise ContextLoadError("Mensagem no histórico excede o limite máximo de caracteres permitido.")
                  
                  # Normalize: keep only role and content
                  normalized.append({
                      "role": role,
                      "content": content
                  })

              return normalized[::-1]
          except ContextLoadError as e:
              logger.error(f"Erro ao carregar histórico: {type(e).__name__}")
              raise
          except Exception as e:
              logger.error(f"Erro ao carregar histórico: {type(e).__name__}")
              raise ContextLoadError("Falha ao carregar histórico de conversação.") from None
  ```

- [ ] **Step 3: Commit Task 1**
  ```bash
  git add backend/memory.py
  git commit -m "feat(memory): validate and normalize load_recent_history data"
  ```

---

### Task 2: Restore Auth assertions in test_auth.py

**Files:**
- Modify: `backend/tests/test_auth.py:2` and `backend/tests/test_auth.py:128-141`

**Interfaces:**
- Consumes: Test environment client response.
- Produces: Correct assertions in `test_valid_token`.

- [ ] **Step 1: Clean up imports**
  Ensure `ANY` is not imported from `unittest.mock` if unused:
  ```python
  from unittest.mock import patch, MagicMock
  ```

- [ ] **Step 2: Restore body assertion and engine verification**
  Ensure `test_valid_token` has the following assertions:
  ```python
  def test_valid_token(client_app, mock_supabase, mock_engine_process):
      mock_user = MockUser(id="user123")
      mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

      response = client_app.post(
          "/chat",
          json={"message": "Hello"},
          headers={"Authorization": "Bearer valid_token"}
      )

      assert response.status_code == 200
      assert response.json()["response"] == "Mock response"
      mock_engine_process.assert_called_once_with("user123", "Hello")
  ```

- [ ] **Step 3: Commit Task 2**
  ```bash
  git add backend/tests/test_auth.py
  git commit -m "test(auth): restore assert on valid token response body"
  ```

---

### Task 3: Verify and Add Validation failure tests

**Files:**
- Modify: `backend/tests/test_ordered_persisted_turn_history.py`

**Interfaces:**
- Consumes: MemoryManager mock database responses.
- Produces: Passing validation exception test assertions.

- [ ] **Step 1: Check for existing tests or write them**
  Make sure `test_load_recent_history_validation_failures` has test cases for all validation failures:
  ```python
      # Case 4: response.data is not a list
      mock_resp_not_list = MagicMock()
      mock_resp_not_list.data = "not a list"
      mock_resp_not_list.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_not_list
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 5: item is not a dict
      mock_resp_item_not_dict = MagicMock()
      mock_resp_item_not_dict.data = ["not a dict"]
      mock_resp_item_not_dict.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_item_not_dict
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 6: missing role
      mock_resp_missing_role = MagicMock()
      mock_resp_missing_role.data = [{"content": "hello"}]
      mock_resp_missing_role.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_missing_role
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 7: missing content
      mock_resp_missing_content = MagicMock()
      mock_resp_missing_content.data = [{"role": "user"}]
      mock_resp_missing_content.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_missing_content
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 8: unknown role
      mock_resp_unknown_role = MagicMock()
      mock_resp_unknown_role.data = [{"role": "admin", "content": "hello"}]
      mock_resp_unknown_role.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_unknown_role
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 9: content not a string
      mock_resp_content_not_str = MagicMock()
      mock_resp_content_not_str.data = [{"role": "user", "content": 123}]
      mock_resp_content_not_str.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_content_not_str
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 10: content exceeds limit
      mock_resp_exceeds_limit = MagicMock()
      mock_resp_exceeds_limit.data = [{"role": "user", "content": "a" * 10001}]
      mock_resp_exceeds_limit.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_exceeds_limit
      with pytest.raises(ContextLoadError):
          mm.load_recent_history("user123")

      # Case 11: valid payload with extra keys normalized to only role and content
      mock_resp_valid_extra = MagicMock()
      mock_resp_valid_extra.data = [{"role": "user", "content": "hello", "extra_key": "some_value", "id": 1}]
      mock_resp_valid_extra.error = None
      mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp_valid_extra
      history = mm.load_recent_history("user123")
      assert history == [{"role": "user", "content": "hello"}]
  ```

- [ ] **Step 2: Commit Task 3**
  ```bash
  git add backend/tests/test_ordered_persisted_turn_history.py
  git commit -m "test(memory): add coverage for all history validation scenarios"
  ```

- [ ] **Step 3: Run full backend and frontend validation**
  ```bash
  PYTHONPATH=. .venv/bin/pytest backend/tests
  npm run lint --prefix frontend
  npm run build --prefix frontend
  ```
