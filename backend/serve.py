"""Production entrypoint for the Katherine Bot.

This module is the **temporarily supported** production entrypoint. It:

1. Validates runtime containment (single-worker mode) **before** importing
   the heavy application modules.
2. Starts Uvicorn with exactly ``workers=1`` and ``reload=False``.
3. Accepts only ``host`` and ``port`` as configurable parameters.

Usage::

    python -m backend.serve

Or with custom host/port::

    python -m backend.serve --host 127.0.0.1 --port 8080

Development may use ``python backend/main.py`` but that is **not** a
production command.
"""

import argparse
import sys
import logging

logger = logging.getLogger(__name__)

# The ASGI application target as a string.  Uvicorn lazy-imports it,
# so ``backend.main`` (and all its heavy dependencies) are not loaded
# until Uvicorn actually starts the server.  Tests can inject a fake
# runner that never resolves this string, avoiding all heavy imports.
DEFAULT_APP_TARGET = "backend.main:app"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the production server.

    Returns a namespace with ``host`` (str) and ``port`` (int).
    """
    parser = argparse.ArgumentParser(
        description="Katherine Bot — production server (single-worker)"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port (default: 8000)",
    )
    parsed = parser.parse_args(argv)

    # Validate port
    if not (1 <= parsed.port <= 65535):
        parser.error(f"Port must be between 1 and 65535, got {parsed.port}")

    return parsed


def main(
    argv: list[str] | None = None,
    runner=None,
    env: dict[str, str] | None = None,
    app_target: str | None = None,
) -> None:
    """Production server entrypoint.

    Args:
        argv: Override for ``sys.argv`` (used in tests).
        runner: Callable like ``uvicorn.run`` for injection (used in tests).
            When ``None``, Uvicorn is imported and used as the runner.
        env: Override for ``os.environ`` (used in tests).  When ``None``,
            the real ``os.environ`` is read.
        app_target: ASGI application target as a string (e.g.
            ``"backend.main:app"``).  When ``runner`` is injected, this
            string is passed through without being resolved, so the
            application module is never imported during tests.  Defaults to
            ``DEFAULT_APP_TARGET``.
    """
    # 1. Validate containment FIRST — before importing app modules.
    from .runtime_containment import validate_worker_configuration

    if env is not None or argv is not None:
        validate_worker_configuration(env=env, argv=argv)
    else:
        validate_worker_configuration()

    # 2. Parse arguments.
    args = _parse_args(argv)

    # 3. Resolve runner — Uvicorn is only imported when no runner is injected.
    resolved_target = app_target if app_target is not None else DEFAULT_APP_TARGET

    if runner is None:
        import uvicorn
        actual_runner = uvicorn.run
    else:
        actual_runner = runner

    actual_runner(
        resolved_target,
        host=args.host,
        port=args.port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
