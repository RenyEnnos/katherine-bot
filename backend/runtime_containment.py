"""Runtime containment guardrails for single-worker operation.

This module provides pure, testable functions to enforce temporary production
containment while the project lacks distributed locking, revision, or atomic
turn commits.

It performs two kinds of validation:

1. **Worker count**: detects multi-worker configurations via environment
   variables (``WEB_CONCURRENCY``, ``UVICORN_WORKERS``, ``GUNICORN_CMD_ARGS``)
   and process arguments (``--workers``, ``-w``).  A value other than ``1``
   or the absence of configuration (which defaults to 1) is rejected.

2. **Archival extraction flag**: parses the ``ARCHIVAL_EXTRACTION_ENABLED``
   environment variable.  Missing or ``false`` means disabled; ``true`` means
   enabled; anything else is a configuration error.

Limitations documented explicitly:
- The application **cannot** detect external replicas, additional containers,
  or load-balanced instances.  Deployments must configure ``replicas=1``.
"""

import os
import sys
import re
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------


class RuntimeContainmentError(Exception):
    """Raised when a runtime containment check fails.

    The message is a constant, sanitised string that never includes raw
    environment variable values, argv content, or tokens.
    """
    pass


# ---------------------------------------------------------------------------
# Archival extraction flag
# ---------------------------------------------------------------------------

_ARCHIVAL_VAR = "ARCHIVAL_EXTRACTION_ENABLED"


def parse_archival_extraction_flag(value: str | None) -> bool:
    """Parse the archival extraction enabled flag.

    Semantics:
    - ``None`` / variable absent → ``False`` (disabled)
    - ``"true"`` (case-insensitive) → ``True`` (enabled)
    - ``"false"`` (case-insensitive) → ``False`` (disabled)
    - Any other non-``None`` value → raises ``RuntimeContainmentError``

    Args:
        value: The raw value of ``ARCHIVAL_EXTRACTION_ENABLED``, or ``None``
            if the variable is not set.

    Returns:
        ``True`` if archival extraction is enabled, ``False`` otherwise.

    Raises:
        RuntimeContainmentError: If the value is not a recognised boolean string.
    """
    if value is None:
        return False

    lower = value.strip().lower()

    if lower == "true":
        return True
    if lower == "false":
        return False

    raise RuntimeContainmentError(
        "Invalid value for archival extraction configuration"
    )


# ---------------------------------------------------------------------------
# Worker detection helpers
# ---------------------------------------------------------------------------

# fmt: off
_SUPPORTED_WORKER_VARS = [
    "WEB_CONCURRENCY",
    "UVICORN_WORKERS",
]
# fmt: on


def _check_env_var(raw: str) -> None:
    """Parse a single environment variable for worker count.

    Raises ``RuntimeContainmentError`` if the value is malformed (non-integer,
    empty, negative, zero, or greater than ``1``).  Returns ``None`` when the
    value is ``1`` (the only accepted value besides absent/``None``).
    """
    stripped = raw.strip()
    if not stripped:
        raise RuntimeContainmentError("Invalid worker configuration")

    try:
        val = int(stripped)
    except ValueError:
        raise RuntimeContainmentError("Invalid worker configuration")

    if val < 0:
        raise RuntimeContainmentError("Invalid worker configuration")
    if val == 0:
        raise RuntimeContainmentError("Invalid worker configuration")
    if val > 1:
        raise RuntimeContainmentError("Invalid worker configuration")

    # val == 1 — accepted


def _check_gunicorn_args(raw: str) -> int | None:
    """Parse ``GUNICORN_CMD_ARGS`` for ``--workers`` or ``-w`` flags.

    Returns ``None`` if no worker flag is found or the value is ``1``.
    Raises ``RuntimeContainmentError`` for any value other than ``1``
    (or for malformed content).
    """
    args = raw.split()
    i = 0
    while i < len(args):
        arg = args[i]

        # --workers 2  or  --workers=2
        if arg.startswith("--workers="):
            suffix = arg[len("--workers="):]
            if not suffix:
                raise RuntimeContainmentError("Invalid worker configuration")
            try:
                val = int(suffix)
            except ValueError:
                raise RuntimeContainmentError("Invalid worker configuration")
            if val != 1:
                raise RuntimeContainmentError("Invalid worker configuration")
            return None

        if arg == "--workers":
            i += 1
            if i >= len(args):
                raise RuntimeContainmentError("Invalid worker configuration")
            try:
                val = int(args[i])
            except ValueError:
                raise RuntimeContainmentError("Invalid worker configuration")
            if val != 1:
                raise RuntimeContainmentError("Invalid worker configuration")
            return None

        # -w 2  or  -w2
        if arg.startswith("-w"):
            suffix = arg[2:]
            if suffix == "":
                # -w followed by next arg
                i += 1
                if i >= len(args):
                    raise RuntimeContainmentError("Invalid worker configuration")
                try:
                    val = int(args[i])
                except ValueError:
                    raise RuntimeContainmentError("Invalid worker configuration")
                if val != 1:
                    raise RuntimeContainmentError("Invalid worker configuration")
                return None
            else:
                # -w2
                try:
                    val = int(suffix)
                except ValueError:
                    raise RuntimeContainmentError("Invalid worker configuration")
                if val != 1:
                    raise RuntimeContainmentError("Invalid worker configuration")
                return None

        i += 1

    return None


def _collect_argv_flags(argv: list[str]) -> int | None:
    """Scan ``sys.argv``-like list for ``--workers`` or ``-w`` flags.

    Same semantics as ``_check_gunicorn_args``.
    """
    return _check_gunicorn_args(" ".join(argv))


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def validate_worker_configuration(
    env: dict[str, str] | None = None,
    argv: list[str] | None = None,
) -> None:
    """Validate that the environment and arguments permit single-worker mode.

    Checks, in order:

    1. ``WEB_CONCURRENCY`` (must be absent or ``1``)
    2. ``UVICORN_WORKERS`` (must be absent or ``1``)
    3. ``GUNICORN_CMD_ARGS`` (must not request > 1 worker)
    4. Process ``argv`` (must not request > 1 worker)

    Raises ``RuntimeContainmentError`` on the **first** violation found.

    Args:
        env: Environment dict (defaults to ``os.environ``).
        argv: Argument list (defaults to ``sys.argv``).
    """
    env = os.environ if env is None else env
    argv = list(sys.argv) if argv is None else argv

    # Check known worker-count environment variables
    for _var_name in _SUPPORTED_WORKER_VARS:
        raw = env.get(_var_name)
        if raw is not None:
            _check_env_var(raw)

    # Check GUNICORN_CMD_ARGS
    gunicorn_raw = env.get("GUNICORN_CMD_ARGS")
    if gunicorn_raw is not None and gunicorn_raw.strip():
        _check_gunicorn_args(gunicorn_raw)

    # Check process argv
    _collect_argv_flags(argv)

    # All checks passed — single-worker mode is satisfied.
