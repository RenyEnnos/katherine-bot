# Design Spec: Isolate Emotional State Per User (PR #228)

**Date**: 2026-07-12  
**Issue**: #206 — P0: isolar estado emocional por usuário e remover mutabilidade global do ConversationEngine  
**PR**: #228  

## Overview
This design spec addresses the remaining blockers in PR #228 of Katherine Bot. It provides concrete guarantees for emotional state isolation, fail-closed reading/writing, robust local concurrency lock management, input/perception validation, and strict error sanitization.

---

## 1. Architectural Integrity & Goals

1. **Strict Isolation**: No emotional state, relationship, or user-specific configuration is stored in `ConversationEngine` or `AffectiveEngine` globally or as a singleton.
2. **Relational Identity Protection**: The authenticated `user_id` passed to `process_turn` serves as the single source of truth. Any `user_id` inside JSON loaded from Supabase is discarded.
3. **Fail-Closed Semantics**:
   - Reading: Any client absence, exception, missing data, or failure to create a default profile must raise a sanitized `StateLoadError`.
   - Writing: Any update returning `data == []` (0 rows updated) or error must raise a sanitized `StatePersistenceError`.
4. **Perception Normalization**: Robust, deterministic normalizer (`_normalize_perception`) protecting the emotional core from malformed LLM outputs.
5. **Local Lock Cleanup**: Robust reference-counted async user lock manager that handles task cancellations gracefully and cleans up fully.

---

## 2. Component Design & Changes

### 2.1. Relational Identity
* **File**: `backend/relationship.py`
* **Changes**: Update `UserRelationship.from_dict` signature:
  ```python
  @staticmethod
  def from_dict(data: Dict, user_id: str) -> "UserRelationship":
      rel = UserRelationship(user_id=user_id)
      # Load variables from data dictionary (e.g. trust, affection)
      # Do NOT use data["user_id"]
  ```
* **File**: `backend/engine.py`
* **Changes**: Pass authenticated `user_id` when calling `from_dict`.

### 2.2. Fail-Closed Read
* **File**: `backend/memory.py`
* **Changes**:
  - Implement `StateLoadError`.
  - Raise `StateLoadError` on offline client, exceptions, missing/null data responses.
  - Try to create a default profile on `data == []` and raise `StateLoadError` if insert fails.
  - Sanitization: Strip user identifiers and connection/token details from public exception messages.

### 2.3. Fail-Closed Write & Validation
* **File**: `backend/memory.py`
* **Changes**:
  - In `sync_state`, assert `response.data` is not `None` and `len(response.data) > 0`.
  - Raise `StatePersistenceError` if 0 rows are updated (`data == []`).

### 2.4. Perception Normalization
* **File**: `backend/engine.py`
* **Changes**:
  - Implement `_normalize_perception(payload: Optional[Dict]) -> Dict` as a pure function.
  - Ensure all outputs are floats, shifts are clamped to `[-1.0, 1.0]`, and allowlisted emotions to `[0.0, 1.0]`. Reject boolean inputs for numeric fields.

### 2.5. AffectiveEngine Defense
* **File**: `backend/emotional_core.py`
* **Changes**:
  - Defensive extraction of shifts in `update_state` from `perception_override`.
  - Check types explicitly, reject booleans, non-finite floats, and default to `0.0`.

### 2.6. UserLockManager Graceful Cancellation
* **File**: `backend/lock_manager.py`
* **Changes**:
  - Secure dictionary access, lock instantiation, and reference count increment within a `try/finally` structure to prevent resource leaks during cancellation.

---

## 3. Verification Plan
* Add dedicated tests in `backend/tests/test_isolation.py` cover all the edge cases outlined in Section 12 of the instructions, including cancellation and concurrency behaviors.
