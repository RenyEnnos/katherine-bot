import asyncio
import logging
import threading
import time
from enum import Enum
from typing import List, Optional, Any, Callable, Set, Dict
from groq import (
    AsyncGroq,
    Groq,
    RateLimitError,
    APIStatusError,
    AuthenticationError,
    APIConnectionError,
    APITimeoutError,
)
from httpx import Timeout as HttpxTimeout
from . import groq_keys
from .turn_execution import (
    GroqCallParams,
    TurnBudget,
    TurnErrorCode,
    TurnExecutionError,
    compute_backoff,
    compute_backoff_from_params,
    compute_effective_attempt_timeout,
)

# Configure logging without basicConfig to satisfy "remova logging.basicConfig(...)"
logger = logging.getLogger("GroqManager")

class GroqConfigurationError(Exception):
    """Raised when the Groq manager has no valid/non-empty API keys configured."""
    pass

class GroqPoolExhaustedError(Exception):
    """Raised when all configured Groq API keys are exhausted.

    ``code`` carries the ``ProviderFailure`` that caused the final exhaustion,
    so the orchestrator can return a precise HTTP status code.
    """
    def __init__(self, message: str = "", code: Optional["ProviderFailure"] = None):
        super().__init__(message)
        self._code = code

    @property
    def failure_code(self) -> Optional["ProviderFailure"]:
        return self._code


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
    timeout = "timeout"            # APITimeoutError or effective-timeout expiry
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
    if isinstance(exc, APITimeoutError):
        return ProviderFailure.timeout
    if isinstance(exc, APIConnectionError):
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
    if isinstance(exc, asyncio.TimeoutError):
        return ProviderFailure.timeout
    if isinstance(exc, TurnExecutionError):
        if exc.code == TurnErrorCode.turn_timeout:
            return ProviderFailure.timeout
        return ProviderFailure.invalid_response
    return ProviderFailure.invalid_response


def provider_failure_to_turn_code(failure: ProviderFailure) -> TurnErrorCode:
    """Map a ``ProviderFailure`` to a ``TurnErrorCode`` for HTTP responses."""
    mapping = {
        ProviderFailure.rate_limited: TurnErrorCode.upstream_rate_limited,
        ProviderFailure.auth_failed: TurnErrorCode.provider_invalid_request,
        ProviderFailure.connection_failed: TurnErrorCode.provider_unavailable,
        ProviderFailure.server_error: TurnErrorCode.provider_unavailable,
        ProviderFailure.timeout: TurnErrorCode.turn_timeout,
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
        groq_params: Optional[GroqCallParams] = None,
    ):
        self._time_provider = time_provider or time.time
        self._groq_params = groq_params or GroqCallParams()
        self._client_factory = client_factory or (lambda k: Groq(api_key=k))

        # Build async client factory with httpx.Timeout for connect + read
        default_params = self._groq_params

        def _default_async_factory(key: str) -> AsyncGroq:
            timeout = HttpxTimeout(
                connect=default_params.connect_timeout,
                read=default_params.provider_attempt_timeout,
                write=default_params.connect_timeout,
                pool=default_params.connect_timeout,
            )
            return AsyncGroq(
                api_key=key,
                max_retries=0,
                timeout=timeout,
            )

        self._async_client_factory = async_client_factory or _default_async_factory

        # Reusable async clients per key (closed on deactivation or shutdown)
        self._async_clients: Dict[str, AsyncGroq] = {}

        # Load and validate keys
        raw_keys = groq_keys.get_groq_api_keys() if keys is None else keys
        self._keys = [key for key in raw_keys if key and key.strip()]
        if not self._keys:
            raise GroqConfigurationError("No Groq API keys configured.")

        self._lock = threading.Lock()
        self._deactivated: Set[str] = set()
        self._cooldowns: Dict[str, float] = {}
        self._cooldown_duration = 10
        self._index = 0

    def _get_or_create_async_client(self, api_key: str) -> AsyncGroq:
        """Get reusable async client for a key, or create and cache it."""
        if api_key not in self._async_clients:
            self._async_clients[api_key] = self._async_client_factory(api_key)
        return self._async_clients[api_key]

    def _close_async_client(self, api_key: str) -> None:
        """Close and remove the async client for a deactivated key."""
        client = self._async_clients.pop(api_key, None)
        if client is not None and hasattr(client, 'aclose'):
            try:
                asyncio.create_task(client.aclose())
            except Exception:
                pass

    def _acquire_next_key(self, tried_keys: Set[str]) -> str:
        with self._lock:
            now = self._time_provider()
            # Clean up expired cooldowns
            for k in list(self._cooldowns.keys()):
                if now >= self._cooldowns[k]:
                    del self._cooldowns[k]

            # Distinguish pool states for structured error reporting
            all_deactivated = all(k in self._deactivated for k in self._keys)
            all_in_cooldown = (
                not all_deactivated
                and all(k in self._cooldowns for k in self._keys if k not in self._deactivated)
            )
            all_tried = (
                not all_deactivated
                and not all_in_cooldown
                and all(k in tried_keys for k in self._keys if k not in self._deactivated and k not in self._cooldowns)
            )

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

            # All keys exhausted — raise with the correct failure code
            if all_deactivated:
                logger.warning("event=groq_pool_unavailable reason=deactivated")
                raise GroqPoolExhaustedError("All keys deactivated.", code=ProviderFailure.auth_failed)
            if all_in_cooldown:
                logger.warning("event=groq_pool_unavailable reason=cooldown")
                raise GroqPoolExhaustedError("All keys in cooldown.", code=ProviderFailure.rate_limited)
            if all_tried:
                logger.warning("event=groq_pool_unavailable reason=exhausted")
                raise GroqPoolExhaustedError("All keys tried, none succeeded.", code=ProviderFailure.connection_failed)

            # Fallback — should not be reached, but be safe
            logger.warning("event=groq_pool_unavailable")
            raise GroqPoolExhaustedError("No eligible Groq keys available.", code=ProviderFailure.connection_failed)

    def _mark_key_rate_limited(self, key: str):
        with self._lock:
            self._cooldowns[key] = self._time_provider() + self._cooldown_duration
            logger.warning("event=groq_key_rate_limited")

    def _deactivate_key(self, key: str):
        with self._lock:
            self._deactivated.add(key)
            self._close_async_client(key)
            logger.error("event=groq_key_disabled")

    def chat_completion(self, messages: List[dict], model: str, **kwargs) -> Any:
        """Synchronous completion — kept for archival extraction and backward compat.

        Uses the sync Groq client. Only SDK-internal retries apply here
        (they are minimal since ``max_retries`` is not set on the sync client).
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
        * Timeout per attempt uses ``compute_effective_attempt_timeout()``
          wrapped via ``asyncio.wait_for``.
        * Backoff uses the configured ``GroqCallParams``.
        * 401 structured errors deactivate the key idempotently and try another.
        * 429 marks cooldown and tries the next eligible key.
        * Connection/5xx errors try the next eligible key.
        * ``asyncio.CancelledError`` is propagated immediately.
        * ``APITimeoutError`` or ``asyncio.TimeoutError`` from wait_for
          produces ``ProviderFailure.timeout`` → ``TurnErrorCode.turn_timeout``.
        * When all eligible keys exhausted, raises ``GroqPoolExhaustedError``
          with the specific ``ProviderFailure.code``.

        Args:
            messages: Chat messages for the completion.
            model: Model name.
            budget: ``TurnBudget`` from ``turn_execution`` — deadline + reserve.
            stage: Stage label for observability (not used for routing).
            **kwargs: Only SDK-supported parameters (temperature, max_tokens, etc.).
                      Must NOT contain: max_attempts, attempt_timeout, backoff params,
                      stage, or other internal control values.

        Returns:
            The Groq chat completion response object.

        Raises:
            GroqPoolExhaustedError: All eligible keys exhausted (with .failure_code).
            TurnExecutionError: Budget exhaustion before attempt.
            asyncio.CancelledError: Operation was cancelled.
        """
        params = self._groq_params

        # Determine max attempts: bounded by config and eligible key count
        active = [k for k in self._keys if k not in self._deactivated]
        max_attempts = min(params.max_attempts, len(active))
        if max_attempts < 1:
            max_attempts = 1

        tried_keys: Set[str] = set()
        last_failure: Optional[ProviderFailure] = None

        for attempt in range(max_attempts):
            # Check budget before trying
            effective_timeout = compute_effective_attempt_timeout(params, budget)
            if effective_timeout <= 0.0:
                raise TurnExecutionError(
                    TurnErrorCode.turn_timeout,
                    "No budget remaining for provider call."
                )

            api_key = self._acquire_next_key(tried_keys)

            try:
                client = self._get_or_create_async_client(api_key)
            except Exception:
                logger.error("event=groq_request_failed")
                raise GroqRequestError("Falha ao executar requisição Groq.")

            try:
                # Only SDK-supported params are forwarded.
                # The httpx.Timeout is set at client creation time.
                sanitised_kwargs = {
                    k: v for k, v in kwargs.items()
                    if k not in ("max_attempts", "attempt_timeout", "stage",
                                 "base_backoff", "max_backoff", "max_jitter")
                }
                # Wrap the actual provider call with asyncio.wait_for using
                # the effective timeout so the coroutine is cancelled when the
                # budget is exhausted.  This is the primary timeout mechanism;
                # the httpx client-level timeout is a secondary safety net.
                result = await asyncio.wait_for(
                    client.chat.completions.create(
                        messages=messages,
                        model=model,
                        **sanitised_kwargs,
                    ),
                    timeout=effective_timeout,
                )
                return result
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                # Effective-timeout expiry — map to timeout failure.
                # The httpx read timeout may also fire independently, but we
                # treat both as the same classification here.
                last_failure = ProviderFailure.timeout
                tried_keys.add(api_key)
            except APITimeoutError:
                last_failure = ProviderFailure.timeout
                tried_keys.add(api_key)
            except RateLimitError:
                self._mark_key_rate_limited(api_key)
                last_failure = ProviderFailure.rate_limited
                tried_keys.add(api_key)
            except AuthenticationError:
                self._deactivate_key(api_key)
                last_failure = ProviderFailure.auth_failed
                tried_keys.add(api_key)
            except APIConnectionError:
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
            except TurnExecutionError:
                raise
            except Exception:
                raise GroqRequestError("Falha ao executar requisição Groq.")

            # If we have more attempts and this wasn't a terminal failure,
            # compute backoff and sleep (if budget allows)
            if attempt < max_attempts - 1:
                remaining_eff = compute_effective_attempt_timeout(params, budget)
                backoff = compute_backoff_from_params(attempt, params)
                if backoff < remaining_eff:
                    await asyncio.sleep(backoff)

        # All attempts exhausted — the GroqPoolExhaustedError from
        # _acquire_next_key already carries the correct ProviderFailure code.
        # If we reach here (shouldn't normally), raise based on last_failure.
        if last_failure == ProviderFailure.rate_limited:
            raise GroqPoolExhaustedError("All keys rate limited.", code=last_failure)
        if last_failure == ProviderFailure.timeout:
            raise GroqPoolExhaustedError("All attempts timed out.", code=last_failure)
        raise GroqPoolExhaustedError(
            "Provider unavailable after all attempts.",
            code=last_failure or ProviderFailure.connection_failed,
        )
