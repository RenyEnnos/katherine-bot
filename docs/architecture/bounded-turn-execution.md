# Bounded Turn Execution

## Problem

The `/chat` endpoint had no hard deadline, unlimited retries, and consumed
cancellations until the turn completed. Failures in appraisal or generation
were silently replaced with neutral fallbacks or hardcoded text that was
then persisted as a valid Katherine response.

## Solution

A monotonic deadline (`time.monotonic`) governs every turn. Stages before
persistence are fully cancellable. Only the commit section
(`save_turn` + `sync_state`) is shielded against cancellation.

## Turn Stage Sequence

```
load_state → load_context → appraisal → transition → generation → commit
    │              │             │            │            │          │
    └── all       └── all      └── async    └── pure     └── async  └── shielded
        async         async         LLM          domain       LLM
        (thread)      (thread)                                               
```

1. **load_state** — Load user state from Supabase (threaded)
2. **load_context** — Load history + context (threaded)
3. **appraisal** — Async LLM call via `AsyncGroq` with deadline budget
4. **transition** — Pure domain: emotional + relationship transition
5. **generation** — Async LLM call via `AsyncGroq` with deadline budget
6. **commit** — `save_turn()` + `sync_state()`, shielded

## Deadline & Budget

- **Deadline starts** when `process_turn()` is called, using `time.monotonic`.
- **Commit reserve** is a fixed time budget reserved exclusively for
  persistence (`save_turn` + `sync_state`). If the remaining budget before
  commit is less than the reserve, the turn fails with `turn_timeout`.
- **No persistence happens** if the reserve is insufficient.

### Defaults

| Parameter | Default | Env Variable |
|-----------|---------|--------------|
| total_deadline | 45.0s | `TURN_TOTAL_DEADLINE` |
| connect_timeout | 3.0s | `TURN_CONNECT_TIMEOUT` |
| provider_attempt_timeout | 15.0s | `TURN_PROVIDER_ATTEMPT_TIMEOUT` |
| supabase_timeout | 5.0s | `TURN_SUPABASE_TIMEOUT` |
| commit_reserve | 10.0s | `TURN_COMMIT_RESERVE` |
| max_attempts | 2 | `TURN_MAX_ATTEMPTS` |
| base_backoff | 0.25s | `TURN_BASE_BACKOFF` |
| max_backoff | 0.75s | `TURN_MAX_BACKOFF` |
| max_jitter | 10% | `TURN_MAX_JITTER` |
| frontend_timeout_ms | 50_000ms | `TURN_FRONTEND_TIMEOUT_MS` |

### Invariants

- `connect_timeout <= provider_attempt_timeout`
- `provider_attempt_timeout < total_deadline`
- `commit_reserve >= 2 × supabase_timeout`
- `commit_reserve < total_deadline`
- `max_attempts` is a real integer, never a bool

## Retry Policy

- **SDK retries disabled**: `max_retries=0` on `AsyncGroq`.
- **Application retries** bounded by `min(max_attempts, eligible_key_count)`.
- Each key is tried **at most once** per logical call.
- 401 errors deactivate the key idempotently and try the next key.
- 429 errors mark cooldown and try the next key.
- Connection/5xx errors try the next key.
- Backoff: exponential with jitter, capped by remaining budget.

## Cancellation Semantics

- **Before commit**: Cancellation (`asyncio.CancelledError`) propagates
  immediately. The lock is released. No persistence occurs.
- **During commit**: The commit section is `asyncio.shield()`-ed. If a
  cancel arrives during commit, the shield allows it to complete before
  re-raising `CancelledError`.
- **Lock**: Per-user `asyncio.Lock` serializes requests for the same user.
  Lock is released on timeout, cancellation, or failure before commit.

## HTTP Error Codes

| Code | HTTP Status | `detail.code` |
|------|-------------|---------------|
| Deadline exceeded | 504 | `turn_timeout` |
| Rate limited | 429 | `upstream_rate_limited` |
| Provider unavailable | 503 | `provider_unavailable` |
| Invalid provider response | 500 | `provider_invalid_response` |
| Persistence unavailable | 503 | `persistence_unavailable` |
| Unexpected error | 500 | `internal_error` |

Never exposed: model name, provider detail, exception text, prompt, key,
token, or stack trace.

## Observability

Structured low-cardinality log events:

```
event=turn_stage_completed stage=generation outcome=success duration_ms=120
event=turn_stage_completed stage=appraisal outcome=failed code=provider_invalid_response
event=turn_stage_completed stage=generation outcome=cancelled
```

Never logged: `user_id`, message content, prompt, response, key, token,
DB IDs, or exception text.

## Frontend

- `AbortController` created per request, stored in ref, cleaned up on
  success/error/cancel/unmount.
- Timeout timer at 50s (configurable) aborts the controller.
- `AbortSignal` forwarded to Axios via the `signal` option.
- Error responses classified by HTTP status: 504 → timeout, 429 →
  rate_limited, 503 → service_unavailable, 422 → validation.
- Axios error objects are never logged to console directly.

## Risk: Partial Persistence (#271)

Until issue #271 is resolved, a failure between `save_turn()` and
`sync_state()` can leave the emotional/relationship state out of sync
with the conversation history. The commit section is non-atomic.

## Out of Scope (this issue)

- Rate limiting, quotas, request IDs (#268)
- Transactions, CAS, outbox (#270–#272)
- Full frontend reconciliation (#277)
- Circuit breaker
- Streaming
- Auth, RLS, schema migrations
- Emotional core or relationship changes
- Prompt or personality changes
