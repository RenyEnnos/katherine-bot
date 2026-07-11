🧪 Add test for AffectiveEngine save_state error handling

**Root Cause**: The `save_state` method in `AffectiveEngine` catches all exceptions during file writing and prints an error message, but this error handling path lacked test coverage.
**Solution**: Introduced a new test suite for `emotional_core.py` utilizing `unittest.mock.patch` to mock `builtins.open` to raise an `IOError`, successfully verifying that the exception is caught and correctly reported via `capsys`.
**Changed Files**:
- `backend/tests/test_emotional_core.py` (New)
**Executed Tests**:
- `backend/tests/test_emotional_core.py`
- Existing backend tests via `pytest backend/tests/` (15 passed)
**Risks**: None. This is an additive testing change that does not alter any production code.
**Rollback Plan**: Revert the commit deleting the new test file.
**Out-of-Scope Items**: Testing the entirety of `emotional_core.py` beyond this specific error handling scenario.
