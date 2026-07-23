import asyncio
import logging
import threading
import time
from enum import Enum
from typing import List, Optional, Any, Callable, Set
from groq import (
    AsyncGroq,
    Groq,
    RateLimitError,
    APIStatusError,
    AuthenticationError,
    APIConnectionError,
    APITimeoutError,
)
from . import groq_keys
from .turn_execution import TurnBudget, TurnErrorCode, TurnExecutionError, compute_backoff

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


# ─── Classification helpers ──────────────────────────────────────────────────

class ProviderFailure(str, Enum):
    """Structured classification of provider failures.

    These codes are used internally and can be mapped to ``TurnErrorCode``
    at orchestration boundaries. They contain no raw exception text, key
    prefixes, or user content.
    """
    rate_limited = "rate_limited"
    auth_failed = "auth_failed"
    connection_failed = "connection_failed"
    server_error = "server_error"
    invalid_response = "invalid_response"
    cancelled = "cancelled"


def classify_provider_error(exc: BaseException) -> ProviderFailure:
    """Classify a Groq SDK exception into a ``ProviderFailure`` code.

    Does NOT examine ``str(exception)``. Does NOT log. Does NOT leak
    key details, prompt, or response content.
    """
    if isinstance(exc, RateLimitError):
        return ProviderFailure.rate_limited
    if isinstance(exc, AuthenticationError):
        return ProviderFailure.auth_failed
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return ProviderFailure.connection_failed
    if isinstance(exc, APIStatusError):
        if exc.status_code == 401:
            return ProviderFailure.auth_failed
        if exc.status_code >= 500:
            return ProviderFailure.server_error
        # 4xx non-recoverable
        return ProviderFailure.invalid_response
    if isinstance(exc, asyncio.CancelledError):
        return ProviderFailure.cancelled
    return ProviderFailure.invalid_response


def provider_failure_to_turn_code(failure: ProviderFailure) -> TurnErrorCode:
    """Map a ``ProviderFailure`` to a ``TurnErrorCode`` for HTTP responses."""
    mapping = {
        ProviderFailure.rate_limited: TurnErrorCode.upstream_rate_limited,
        ProviderFailure.auth_failed: TurnErrorCode.provider_invalid_request,
        ProviderFailure.connection_failed: TurnErrorCode.provider_unavailable,
        ProviderFailure.server_error: TurnErrorCode.provider_unavailable,
        ProviderFailure.invalid_response: TurnErrorCode.provider_invalid_response,
        ProviderFailure.cancelled: TurnErrorCode.internal_error,  # propagated, not converted
    }
    return mapping.get(failure, TurnErrorCode.provider_invalid_response)


# ─── GroqClientManager ───────────────────────────────────────────────────────

class GroqClientManager:
    def __init__(
        self,
        keys: Optional[List[str]] = None,
        time_provider: Optional[Callable[[], float]] = None,
        client_factory: Optional[Callable[[str], Any]] = None,
        async_client_factory: Optional[Callable[[str], Any]] = None,
    ):
        self._time_provider = time_provider or time.time
        self._client_factory = client_factory or (lambda k: Groq(api_key=k))
        self._async_client_factory = async_client_factory or (
            lambda k: AsyncGroq(api_key=k, max_retries=0)
        )
        
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
        """Synchronous completion — kept for archival extraction and backward compat.

        Uses ``AsyncGroq`` internally via ``asyncio.run`` + ``asyncio.to_thread``
        pattern is NOT used here. Instead, this delegates to the sync Groq client.
        """
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

    async def chat_completion_async(
        self,
        messages: List[dict],
        model: str,
        budget: TurnBudget,
        stage: str = "generation",
        **kwargs,
    ) -> Any:
        """Async completion with deadline-based budget and bounded retries.

        * Uses ``AsyncGroq`` with ``max_retries=0`` (SDK retries disabled).
        * Each key is tried at most once per logical call.
        * Total attempts: ``min(max_attempts, eligible_key_count)``.
        * Timeout per attempt is the minimum of:
          - configured attempt timeout
          - remaining budget before commit reserve
        * 401 structured errors deactivate the key idempotently and try another.
        * 429 marks cooldown and tries the next eligible key.
        * Connection/5xx errors try the next eligible key.
        * When all eligible keys exhausted, raises ``GroqPoolExhaustedError``.
        * ``asyncio.CancelledError`` is propagated immediately.

        Args:
            messages: Chat messages for the completion.
            model: Model name.
            budget: ``TurnBudget`` from ``turn_execution`` — deadline + reserve.
            stage: Stage label for observability (not used for routing).
            **kwargs: Additional completion parameters (temperature, max_tokens, etc.).

        Returns:
            The Groq chat completion response object.

        Raises:
            GroqPoolExhaustedError: All eligible keys exhausted.
            asyncio.CancelledError: Operation was cancelled.
        """
        # Determine max attempts: bounded by config and eligible key count
        active = [k for k in self._keys if k not in self._deactivated]
        configured_max = kwargs.get("max_attempts", len(active))
        max_attempts = min(configured_max, len(active))
        if max_attempts < 1:
            max_attempts = 1

        # Extract attempt timeout or use a reasonable default
        attempt_timeout = kwargs.get("attempt_timeout", 15.0)

        tried_keys: Set[str] = set()
        last_failure: Optional[ProviderFailure] = None

        for attempt in range(max_attempts):
            # Check budget before trying
            effective_timeout = budget.remaining_for_attempt(attempt_timeout)
            if effective_timeout <= 0.0:
                raise TurnExecutionError(
                    TurnErrorCode.turn_timeout,
                    "No budget remaining for provider call."
                )

            api_key = self._acquire_next_key(tried_keys)

            try:
                client = self._async_client_factory(api_key)
            except Exception:
                logger.error("event=groq_request_failed")
                raise GroqRequestError("Falha ao executar requisição Groq.")

            try:
                # Create an asyncio timeout for this attempt
                result = await asyncio.wait_for(
                    client.chat.completions.create(
                        messages=messages,
                        model=model,
                        timeout=effective_timeout,
                        **kwargs,
                    ),
                    timeout=effective_timeout,
                )
                return result
            except asyncio.TimeoutError:
                last_failure = ProviderFailure.connection_failed
                tried_keys.add(api_key)
            except asyncio.CancelledError:
                raise
            except RateLimitError:
                self._mark_key_rate_limited(api_key)
                last_failure = ProviderFailure.rate_limited
                tried_keys.add(api_key)
            except AuthenticationError:
                self._deactivate_key(api_key)
                last_failure = ProviderFailure.auth_failed
                tried_keys.add(api_key)
            except (APIConnectionError, APITimeoutError):
                last_failure = ProviderFailure.connection_failed
                tried_keys.add(api_key)
            except APIStatusError as e:
                if e.status_code == 401:
                    self._deactivate_key(api_key)
                    last_failure = ProviderFailure.auth_failed
                    tried_keys.add(api_key)
                elif e.status_code >= 500:
                    last_failure = ProviderFailure.server_error
                    tried_keys.add(api_key)
                else:
                    # Non-retryable 4xx
                    raise GroqRequestError("Falha ao executar requisição Groq.")
            except Exception:
                raise GroqRequestError("Falha ao executar requisição Groq.")

            # If we have more attempts and this wasn't a terminal failure, compute backoff
            if attempt < max_attempts - 1:
                remaining_eff = budget.remaining_for_attempt(attempt_timeout)
                backoff = compute_backoff(attempt, jitter_fraction=0.10)
                if backoff < remaining_eff:
                    await asyncio.sleep(backoff)

        # All attempts exhausted
        if last_failure == ProviderFailure.rate_limited:
            raise GroqPoolExhaustedError("All keys rate limited.")
        raise GroqPoolExhaustedError("Provider unavailable.")
