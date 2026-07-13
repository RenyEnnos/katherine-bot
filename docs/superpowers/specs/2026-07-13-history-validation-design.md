# Design Spec: Ordered Turn History Validation & Auth assertion restoration

- **Date**: 2026-07-13
- **Author**: Antigravity AI
- **Status**: Approved (Automatic approval mode authorized)

## 1. Problem Description

The turn history load function `load_recent_history()` in `backend/memory.py` did not structurally validate the data retrieved from the Supabase database. Specifically, it assumed `response.data` was a list of valid message turn records and returned them directly. This could leak malformed data, trigger unhandled exceptions (like `KeyError` or `TypeError`) in downstream logic, or lead to silent truncations of persisted data.

Additionally, a change in the HTTP contract testing in `backend/tests/test_auth.py` removed an assertion verifying the response JSON body of a valid chat requests, weakening the test contract.

## 2. Proposed Solution

### 2.1. Structural Validation in `load_recent_history`
Implement strict validation assertions for the database response data format:
1. Ensure `response.data` is a list.
2. For each message turn in the list, assert that:
   - It is a dictionary.
   - It contains exactly the `role` and `content` keys.
   - The value of `role` is either `"user"` or `"assistant"`.
   - The value of `content` is a string.
   - The size of `content` is less than or equal to `MAX_MESSAGE_LENGTH` (10000 characters).
3. **Normalization**: Construct a new list of dicts that only keeps the keys `role` and `content`, filtering out any extra keys.
4. **Sanitization**: Wrap validation steps to intercept and convert unexpected failures to a clean `ContextLoadError` exception to prevent leaking database structure or internal tracebacks.

### 2.2. Auth Test Assertion Restoration
Restore the contract check in `backend/tests/test_auth.py`:
1. Verify that `response.json()["response"] == "Mock response"`.
2. Clean up unused `ANY` from `unittest.mock`.
3. Assure engine process is called with correct arguments: `mock_engine_process.assert_called_once_with("user123", "Hello")`.

## 3. Test Coverage

The test suite in `backend/tests/test_ordered_persisted_turn_history.py` must include assertions for:
- `response.data` not being a list.
- Item not being a dictionary.
- Absence of `role` key.
- Absence of `content` key.
- Unknown role value.
- Content not being a string.
- Content exceeding the limit (`MAX_MESSAGE_LENGTH`).
- Payload with extra keys being normalized to only `role` and `content`.

## 4. Implementation Plan

1. Modify `backend/memory.py` to add strict type and format checks on turns, normalize structure, and enforce character limit.
2. Modify `backend/tests/test_auth.py` to restore HTTP response body assertion.
3. Update `backend/tests/test_ordered_persisted_turn_history.py` to test all failure/edge cases.
4. Run python backend tests (`pytest backend/tests`) and frontend lint/build to ensure compatibility.
