# Design Spec: Thread-Safe Groq Client Manager & Sanitized Logging

- **Date**: 2026-07-13
- **Author**: Antigravity AI
- **Status**: Approved (Automatic approval mode authorized)

## 1. Problem Description

The existing `GroqClientManager` implementation in `backend/groq_manager.py` contains several concurrency and logging issues:
1. **Concurrency Hazards**: Mutable states such as `keys` and `cooldowns` are accessed and modified concurrently by multiple threads without synchronization. This can lead to race conditions, concurrent modification errors (e.g., removing a key from a list being iterated), and inconsistent pool status.
2. **Log/Exception Exposure**: The API keys (and prefixes/fragments thereof), model responses, user messages, tokens, and raw upstream error tracebacks can be exposed in logs or public exceptions.
3. **Random Selection**: Keys are selected randomly, which makes deterministic rotation and testing difficult.
4. **Infinite Loops / Unbounded Retries**: Retries are calculated based on list lengths that can shrink concurrently, leading to potential infinite loops.
5. **No Network-free Testing support**: The system lacks clear dependency injection for key lists, time sources, and client factories, forcing tests to rely on environment variables or mock patching.

## 2. Proposed Solution

### 2.1. Synchronization and Thread-Safety
We will introduce a private `threading.Lock` to synchronize all read and write access to the pool state:
- Configured keys list (`self._keys`).
- Set of deactivated keys (`self._deactivated`).
- Dictionary of cooldown timestamps (`self._cooldowns`).
- Current rotation index (`self._index`).

We will explicitly **never** hold the lock during the actual network invocation (`client.chat.completions.create(...)`). The lock will only be acquired briefly to select the next eligible key, mark a key as rate-limited, or deactivate a key.

### 2.2. Deterministic Round-Robin Rotation
Instead of random choice, we will iterate over `self._keys` starting from `self._index`:
1. Loop over keys using `(self._index + i) % len(self._keys)`.
2. Check if a key is deactivated or in cooldown.
3. If a cooldown has expired (relative to a controlled clock provider), remove it from cooldowns and mark it eligible.
4. Keep track of already tried keys in a local `tried_keys` set within the invocation to ensure no key is tried more than once per `chat_completion` call.
5. Once an eligible, untried key is selected, update `self._index` and return the key.
6. If no eligible key is found, raise `GroqPoolExhaustedError`.

### 2.3. Safe Exception and Log Sanitization
We will define three custom domain exceptions:
- `GroqConfigurationError`: Raised when initialized with no keys.
- `GroqPoolExhaustedError`: Raised when all keys are deactivated or in cooldown.
- `GroqRequestError`: Raised when an unexpected exception is caught during execution.

No keys, fragments, tokens, user messages, or raw upstream errors will be included in the logs or exception messages. Upstream exceptions can be chained internally using `raise ... from error` to preserve tracebacks for developer debugging in local environments, but public strings and logs must remain sanitized.
All logs will use constant event strings:
- `event=groq_key_rate_limited`
- `event=groq_key_disabled`
- `event=groq_pool_unavailable`
- `event=groq_request_failed`

### 2.4. Dependency Injection for Testing
The `GroqClientManager` will accept optional keyword arguments:
- `keys`: A list of strings to override the default `GROQ_API_KEYS`.
- `time_provider`: A callable returning a float (defaults to `time.time`) to mock time progression.
- `client_factory`: A callable taking a string and returning an object (defaults to a lambda creating a real `Groq` client) to mock the API client.

## 3. Test Coverage

We will create `backend/tests/test_groq_manager.py` with tests for:
1. **Empty initialization**: `GroqClientManager(keys=[])` raises `GroqConfigurationError`.
2. **Concurrent access safety**: Multiple threads calling `chat_completion` concurrently with mock delay does not cause state corruption.
3. **Idempotent Rate-limiting**: Multiple concurrent threads marking the same key as rate-limited maintain consistent cooldown timestamps.
4. **Idempotent Deactivation**: Multiple concurrent threads deactivating the same invalid key only record it in the deactivated set once.
5. **No Lock during network call**: Threads are able to retrieve and call completion concurrently on a slow client without blocking each other.
6. **Clock progression**: Expired cooldowns make keys eligible again when the fake clock is advanced, without actual sleeps.
7. **Attempt Limits**: Each call terminates with a clean exception after exhausting all keys.
8. **Rate-limit Rotation**: Getting a rate-limit error on one key rotates immediately to try another eligible key.
9. **All keys unavailable**: Raises `GroqPoolExhaustedError` when all keys are in cooldown/disabled.
10. **Structured 401 recognition**: Checks that `AuthenticationError` (or APIStatusError with 401) is used to deactivate keys, while other status codes are treated as request errors.
11. **Sanitization checks**: Asserting that no log captures (using `caplog`) or exception message strings contain API keys, prefixes, tokens, message payloads, or specific error details.

## 4. Implementation Plan

1. Modify `backend/groq_manager.py` with the thread-safe implementation, domain exceptions, round-robin search, sanitized logging, and testable dependency injections.
2. Create `backend/tests/test_groq_manager.py` to cover all specified test cases.
3. Run `pytest backend/tests/test_groq_manager.py` to verify the new manager functionality.
4. Run the entire test suite to ensure no regressions.
