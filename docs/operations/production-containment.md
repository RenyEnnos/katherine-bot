# Production Containment

## Context

This document describes the temporary production containment measures
implemented by [issue #266](https://github.com/RenyEnnos/katherine-bot/issues/266).

The project currently lacks:

- Distributed locking or compare-and-swap for user state
- Revision-based turn commits
- Persistent outbox or durable workers
- Governed memory pipeline with user approval

Until these capabilities exist, a single-worker, single-replica deployment is
**mandatory** to prevent lost updates, race conditions, and inconsistent state.

---

## Why single-worker and single-replica?

The per-user lock (`UserLockManager`) only works **within a single process**.
Two workers, containers, replicas, or event loops can process the same user
simultaneously, causing:

- Lost emotional state updates
- Corrupted relationship state
- Duplicate or missing turns
- Inconsistent archival extraction records

The application **cannot** detect external replicas, load-balanced instances,
or additional containers.  Deployments must configure exactly one replica.

---

## Detected configurations

At startup, the application checks:

| Source | Variable / Argument | Values |
|--------|-------------------|--------|
| Environment | `WEB_CONCURRENCY` | Must be `1` or absent |
| Environment | `UVICORN_WORKERS` | Must be `1` or absent |
| Environment | `GUNICORN_CMD_ARGS` | Must not request `--workers > 1` or `-w > 1` |
| Process args | `--workers`, `--workers=N`, `-w N`, `-wN` | Must not request `> 1` |

Any violation raises `RuntimeContainmentError` and prevents the application
from starting.

### What is NOT detected

- Multiple containers or replicas orchestrated by Docker Compose, Kubernetes,
  Nomad, or similar
- Multiple processes started manually on different ports
- Serverless / function-as-a-service scaling

**Operations must ensure `replicas=1`** in the deployment configuration.

---

## Supported production command

```bash
python -m backend.serve
```

This starts Uvicorn with exactly `workers=1` and `reload=False`.

Optional parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `8000` | Bind port (1–65535) |

The development entrypoint (`python backend/main.py`) uses `reload=True` and
is **not** suitable for production.

---

## `ARCHIVAL_EXTRACTION_ENABLED`

### Default: `false`

Archival extraction extracts facts from user messages by calling an LLM and
persisting the result to `archival_extractions`.  This feature is **disabled
by default** because:

- It incurs additional LLM cost on every turn
- It runs as a non-durable background task that may be lost on restart
- It is not governed by user approval, correction, or deletion
- It does not feed the active recovery path

### Enabling

```bash
ARCHIVAL_EXTRACTION_ENABLED=true python -m backend.serve
```

Only the string `true` (case-insensitive) enables the feature.  Any other
non-`None` value that is not `false` raises a configuration error.

### Behaviour when disabled

- `process_turn()` does **not** schedule archival extraction via
  `BackgroundTasks.add_task()`
- `run_archival_extraction()` returns immediately, even if called directly
  (no message loading, no LLM call, no persistence)
- Turn persistence, state synchronisation, emotional state, relationship
  state, and the public API are **unaffected**

---

## Existing records

All existing archival extraction records remain stored in the database.
They are **not** deleted, migrated, or reprocessed.

> **Note:** `archival_extractions` does **not** represent recoverable or
> user-approved memory.  Retention, governance, and recovery are tracked
> by future issues.

---

## Rollback

To roll back the containment changes without losing data:

1. Revert the PR, or check out the previous deployment image/tag
2. Ensure the deployment still uses `replicas=1` (the containment check does
   not prevent starting, it only fails early)
3. The database schema is unchanged — no migration rollback is needed
4. Existing archival records remain intact

There is no silent re-activation of archival extraction on rollback because
the flag default (`false`) is part of the code, not a database setting.

---

## Dependencies

| Issue | Description |
|-------|-------------|
| [#274](https://github.com/RenyEnnos/katherine-bot/issues/274) | Distributed lock / revision for concurrent access |
| [#276](https://github.com/RenyEnnos/katherine-bot/issues/276) | Governed memory lifecycle (approval, retention, deletion) |
