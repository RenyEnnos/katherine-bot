import logging
import threading
import time
from typing import List, Optional, Any, Callable, Set
from groq import (
    Groq,
    RateLimitError,
    APIStatusError,
    AuthenticationError,
    APIConnectionError,
    APITimeoutError,
)
from . import groq_keys

# Configure logging without basicConfig to satisfy "remova logging.basicConfig(...)"
logger = logging.getLogger("GroqManager")

class GroqConfigurationError(Exception):
    """Raised when the Groq manager has no valid/non-empty API keys configured."""
    pass

class GroqPoolExhaustedError(Exception):
    """Raised when all configured Groq API keys are currently in cooldown or deactivated."""
    pass

class GroqRequestError(Exception):
    """Raised when an unexpected error occurs during a Groq completion request."""
    pass

class GroqClientManager:
    def __init__(
        self,
        keys: Optional[List[str]] = None,
        time_provider: Optional[Callable[[], float]] = None,
        client_factory: Optional[Callable[[str], Any]] = None
    ):
        self._time_provider = time_provider or time.time
        self._client_factory = client_factory or (lambda k: Groq(api_key=k))
        
        # Load and validate keys
        raw_keys = groq_keys.get_groq_api_keys() if keys is None else keys
        self._keys = [key for key in raw_keys if key and key.strip()]
        if not self._keys:
            raise GroqConfigurationError("No Groq API keys configured.")
            
        self._lock = threading.Lock()
        self._deactivated: Set[str] = set()
        self._cooldowns = {}
        self._cooldown_duration = 10
        self._index = 0

    def _acquire_next_key(self, tried_keys: Set[str]) -> str:
        with self._lock:
            # Check if there are any active keys left in the entire pool
            active_keys = [k for k in self._keys if k not in self._deactivated]
            if not active_keys:
                logger.warning("event=groq_pool_unavailable")
                raise GroqPoolExhaustedError("All keys are deactivated.")
                
            now = self._time_provider()
            # Clean up expired cooldowns
            for k in list(self._cooldowns.keys()):
                if now >= self._cooldowns[k]:
                    del self._cooldowns[k]
            
            # Find the next eligible key starting from self._index
            for i in range(len(self._keys)):
                idx = (self._index + i) % len(self._keys)
                k = self._keys[idx]
                
                if k in self._deactivated:
                    continue
                if k in self._cooldowns:
                    continue
                if k in tried_keys:
                    continue
                    
                # Mark this index as used and set it to next for next call
                self._index = (idx + 1) % len(self._keys)
                return k
                
            # If we scanned all keys and found none eligible
            logger.warning("event=groq_pool_unavailable")
            raise GroqPoolExhaustedError("No eligible Groq keys available.")

    def _mark_key_rate_limited(self, key: str):
        with self._lock:
            self._cooldowns[key] = self._time_provider() + self._cooldown_duration
            logger.warning("event=groq_key_rate_limited")

    def _deactivate_key(self, key: str):
        with self._lock:
            self._deactivated.add(key)
            logger.error("event=groq_key_disabled")

    def chat_completion(self, messages: List[dict], model: str, **kwargs) -> Any:
        tried_keys: Set[str] = set()
        
        while True:
            api_key = self._acquire_next_key(tried_keys)
                
            try:
                # Factory call protected against leakage and exceptions escaping
                client = self._client_factory(api_key)
            except Exception as e:
                logger.error("event=groq_request_failed")
                raise GroqRequestError("Falha ao executar requisição Groq.") from e
            
            try:
                # Execution happens outside of the lock
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
            except (APIConnectionError, APITimeoutError):
                logger.error("event=groq_request_failed")
                tried_keys.add(api_key)
            except APIStatusError as e:
                if e.status_code == 401:
                    self._deactivate_key(api_key)
                    tried_keys.add(api_key)
                elif e.status_code >= 500:
                    logger.error("event=groq_request_failed")
                    tried_keys.add(api_key)
                else:
                    logger.error("event=groq_request_failed")
                    raise GroqRequestError("Falha ao executar requisição Groq.") from e
            except Exception as e:
                logger.error("event=groq_request_failed")
                raise GroqRequestError("Falha ao executar requisição Groq.") from e
