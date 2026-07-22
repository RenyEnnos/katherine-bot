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
) -> None:
    """Production server entrypoint.

    Args:
        argv: Override for ``sys.argv`` (used in tests).
        runner: Callable like ``uvicorn.run`` for injection (used in tests).
        env: Override for ``os.environ`` (used in tests).  When ``None``,
            the real ``os.environ`` is read.
    """
    # 1. Validate containment FIRST — before importing app modules
    from .runtime_containment import validate_worker_configuration

    # Forward env/argv to guarantee deterministic, avoid real os.environ reads.
    if env is not None or argv is not None:
        validate_worker_configuration(env=env, argv=argv)
    else:
        validate_worker_configuration()

    # 2. Parse arguments
    args = _parse_args(argv)

    # 3. Import the FastAPI app (heavy dependencies loaded after validation)
    import uvicorn
    from .main import app

    actual_runner = runner if runner is not None else uvicorn.run
    actual_runner(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
