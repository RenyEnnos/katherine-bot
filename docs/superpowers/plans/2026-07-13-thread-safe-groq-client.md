# Thread-Safe Groq Client Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `GroqClientManager` in `backend/groq_manager.py` to be thread-safe, deterministic (round-robin), sanitizing logs and exceptions against secret/payload/traceback leakage, and add test coverage.

**Architecture:** Use a private `threading.Lock` to guard rotation index, active keys pool, and cooldown dictionary. Select keys deterministically using round-robin. Catch `AuthenticationError` using the Groq SDK class rather than text parsing. Sanitize all logs and exceptions. Support dependency injection for time and client creation to enable unit testing.

**Tech Stack:** Python 3.12, Groq SDK, standard library `threading`.

## Global Constraints
* No network/real Groq calls during tests.
* No print statements or `logging.basicConfig(...)` in production code.
* Logs and exceptions must remain fully sanitized, only using constant event strings.
* Upstream exception chained internally via `from error`, but public string remains sanitized.
* No changes to prompts, emotional logic, models, temperature, or frontend files.

---

### Task 1: Thread-Safe GroqClientManager Implementation

**Files:**
- Modify: `backend/groq_manager.py`

**Interfaces:**
- Consumes: `groq` SDK, `backend/groq_keys.py`
- Produces: `GroqClientManager` with contract: `GroqClientManager.chat_completion(messages, model, **kwargs)`

- [ ] **Step 1: Write Domain Exceptions and Manager Structure**
Implement the exceptions and `GroqClientManager` class structure with dependency injection.

```python
import logging
import threading
import time
from typing import List, Optional, Any, Callable, Set
from groq import Groq, RateLimitError, APIError, APIStatusError, AuthenticationError
from .groq_keys import GROQ_API_KEYS

logger = logging.getLogger("GroqManager")

class GroqConfigurationError(Exception):
    """Raised when no valid API keys are configured."""
    pass

class GroqPoolExhaustedError(Exception):
    """Raised when all keys are deactivated, in cooldown, or exhausted."""
    pass

class GroqRequestError(Exception):
    """Raised on unexpected request failures."""
    pass
```

- [ ] **Step 2: Implement Init with DI**
Support `keys`, `time_provider`, and `client_factory` in `__init__`.

```python
class GroqClientManager:
    def __init__(
        self,
        keys: Optional[List[str]] = None,
        time_provider: Optional[Callable[[], float]] = None,
        client_factory: Optional[Callable[[str], Any]] = None
    ):
        self._time_provider = time_provider or time.time
        self._client_factory = client_factory or (lambda k: Groq(api_key=k))
        
        raw_keys = keys if keys is not None else GROQ_API_KEYS
        self._keys = [k for k in raw_keys if k and k.strip()]
        if not self._keys:
            raise GroqConfigurationError("No Groq API keys configured.")
            
        self._lock = threading.Lock()
        self._deactivated: Set[str] = set()
        self._cooldowns = {}
        self._cooldown_duration = 10
        self._index = 0
```

- [ ] **Step 3: Implement Lock-Protected Key Retrieval**
Implement `_acquire_next_key` to deterministically select the next eligible key.

```python
    def _acquire_next_key(self, tried_keys: Set[str]) -> str:
        with self._lock:
            active_keys = [k for k in self._keys if k not in self._deactivated]
            if not active_keys:
                logger.warning("event=groq_pool_unavailable")
                raise GroqPoolExhaustedError("All keys deactivated.")
                
            now = self._time_provider()
            # Clean expired cooldowns
            for k in list(self._cooldowns.keys()):
                if now >= self._cooldowns[k]:
                    del self._cooldowns[k]
                    
            for i in range(len(self._keys)):
                idx = (self._index + i) % len(self._keys)
                k = self._keys[idx]
                if k in self._deactivated:
                    continue
                if k in self._cooldowns:
                    continue
                if k in tried_keys:
                    continue
                    
                self._index = (idx + 1) % len(self._keys)
                return k
                
            logger.warning("event=groq_pool_unavailable")
            raise GroqPoolExhaustedError("No eligible Groq keys available.")
```

- [ ] **Step 4: Implement Thread-Safe Cooldown and Deactivation Helpers**

```python
    def _mark_key_rate_limited(self, key: str):
        with self._lock:
            self._cooldowns[key] = self._time_provider() + self._cooldown_duration
            logger.warning("event=groq_key_rate_limited")

    def _deactivate_key(self, key: str):
        with self._lock:
            self._deactivated.add(key)
            logger.error("event=groq_key_disabled")
```

- [ ] **Step 5: Implement `chat_completion` with Retry Loop and Sanitized logs/exceptions**

```python
    def chat_completion(self, messages: List[dict], model: str, **kwargs) -> Any:
        tried_keys: Set[str] = set()
        
        while True:
            try:
                api_key = self._acquire_next_key(tried_keys)
            except GroqPoolExhaustedError as e:
                # Re-raise the clean domain exception
                raise e
                
            client = self._client_factory(api_key)
            
            try:
                # Perform request outside of lock
                return client.chat.completions.create(
                    messages=messages,
                    model=model,
                    **kwargs
                )
            except RateLimitError:
                self._mark_key_rate_limited(api_key)
                tried_keys.add(api_key)
            except AuthenticationError:
                self._deactivate_key(api_key)
                tried_keys.add(api_key)
            except APIStatusError as e:
                if e.status_code == 401:
                    self._deactivate_key(api_key)
                    tried_keys.add(api_key)
                else:
                    logger.error("event=groq_request_failed")
                    raise GroqRequestError("Falha ao executar requisição Groq.") from e
            except Exception as e:
                logger.error("event=groq_request_failed")
                raise GroqRequestError("Falha ao executar requisição Groq.") from e
```

---

### Task 2: Create Comprehensive Tests

**Files:**
- Create: `backend/tests/test_groq_manager.py`

- [ ] **Step 1: Write tests covering all 14 specified constraints**
Implement tests including empty init, round robin order, thread-safety with delayed fake client calls, barrier synchronization, fake clock progression, rate limit rotation, and strict logging `caplog` sanitization checks.

- [ ] **Step 2: Run backend tests**
Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/test_groq_manager.py -v`
Expected: PASS

- [ ] **Step 3: Run the whole test suite**
Run: `PYTHONPATH=. .venv/bin/pytest backend/tests/`
Expected: PASS
