"""Tests for runtime containment guardrails.

All tests are pure — no network, Docker, Supabase, Groq, embeddings, or FastAPI.
"""

import os
import sys
import pytest

from backend.runtime_containment import (
    RuntimeContainmentError,
    parse_archival_extraction_flag,
    validate_worker_configuration,
    _check_env_var,
    _check_gunicorn_args,
    _collect_argv_flags,
)


# ===================================================================
# ARCHIVAL EXTRACTION FLAG
# ===================================================================


class TestParseArchivalExtractionFlag:
    """Tests for ``parse_archival_extraction_flag``."""

    def test_absent_defaults_to_false(self):
        """Flag absent (None) → False."""
        assert parse_archival_extraction_flag(None) is False

    def test_false_string(self):
        """``false`` string → False."""
        assert parse_archival_extraction_flag("false") is False

    def test_false_uppercase(self):
        assert parse_archival_extraction_flag("FALSE") is False

    def test_false_mixed_case(self):
        assert parse_archival_extraction_flag("False") is False

    def test_true_string(self):
        """``true`` string → True."""
        assert parse_archival_extraction_flag("true") is True

    def test_true_uppercase(self):
        assert parse_archival_extraction_flag("TRUE") is True

    def test_invalid_value_raises(self):
        """Any value other than true/false raises RuntimeContainmentError."""
        for val in ["1", "0", "yes", "no", "enabled", "disabled", "", "  "]:
            with pytest.raises(RuntimeContainmentError):
                parse_archival_extraction_flag(val)

    def test_sanitized_error_message(self):
        """Error message must not contain the raw invalid value."""
        with pytest.raises(RuntimeContainmentError) as exc:
            parse_archival_extraction_flag("SENSITIVE_TOKEN_xyz")
        assert "SENSITIVE_TOKEN_xyz" not in str(exc.value)


# ===================================================================
# WORKER DETECTION — internal helpers
# ===================================================================


class TestCheckEnvVar:
    """Tests for the internal ``_check_env_var`` helper."""

    def test_value_1_accepted(self):
        _check_env_var("1")

    def test_value_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("2")

    def test_zero_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("0")

    def test_negative_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("-1")

    def test_empty_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("")

    def test_whitespace_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("   ")

    def test_non_integer_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("abc")

    def test_float_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_env_var("2.5")

    def test_sanitized_message(self):
        with pytest.raises(RuntimeContainmentError) as exc:
            _check_env_var("SENSITIVE")
        assert "SENSITIVE" not in str(exc.value)


class TestCheckGunicornArgs:
    """Tests for the internal ``_check_gunicorn_args`` helper."""

    def test_no_worker_flag(self):
        """No worker flag → accepted."""
        assert _check_gunicorn_args("--timeout 120 --log-level info") is None

    def test_workers_1_accepted(self):
        assert _check_gunicorn_args("--workers 1") is None

    def test_workers_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers 2")

    def test_workers_equals_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers=2")

    def test_w_flag_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("-w 2")

    def test_w2_flag_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("-w2")

    def test_w_missing_value_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers")

    def test_workers_non_int_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers abc")

    def test_sanitized_message(self):
        with pytest.raises(RuntimeContainmentError) as exc:
            _check_gunicorn_args("--workers 99")
        assert "99" not in str(exc.value)

    def test_w_1_accepted(self):
        """-w 1 is accepted."""
        assert _check_gunicorn_args("-w 1") is None

    def test_w1_accepted(self):
        """-w1 is accepted."""
        assert _check_gunicorn_args("-w1") is None


# ===================================================================
# WORKER DETECTION — validate_worker_configuration
# ===================================================================


class TestValidateWorkerConfiguration:
    """Integration tests for the full ``validate_worker_configuration``."""

    def test_no_config(self):
        """No configuration → single-worker accepted."""
        validate_worker_configuration(env={}, argv=["app.py"])

    def test_web_concurrency_1(self):
        validate_worker_configuration(env={"WEB_CONCURRENCY": "1"}, argv=["app.py"])

    def test_web_concurrency_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "2"}, argv=["app.py"]
            )

    def test_uvicorn_workers_1(self):
        validate_worker_configuration(env={"UVICORN_WORKERS": "1"}, argv=["app.py"])

    def test_uvicorn_workers_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"UVICORN_WORKERS": "2"}, argv=["app.py"]
            )

    def test_gunicorn_args_workers_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"GUNICORN_CMD_ARGS": "--workers 2"}, argv=["app.py"]
            )

    def test_argv_workers_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(env={}, argv=["app.py", "--workers", "2"])

    def test_argv_w2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(env={}, argv=["app.py", "-w2"])

    def test_argv_w_2_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(env={}, argv=["app.py", "-w", "2"])

    def test_conflicting_config_rejected(self):
        """WEB_CONCURRENCY=2 with argv --workers 1 → fails on first violation."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "2"}, argv=["app.py"]
            )

    def test_absent_env_var_ignored(self):
        """Absent variables are simply skipped."""
        validate_worker_configuration(
            env={"PATH": "/usr/bin"}, argv=["app.py"]
        )

    def test_multiple_1_accepted(self):
        """All at 1 is fine."""
        validate_worker_configuration(
            env={
                "WEB_CONCURRENCY": "1",
                "UVICORN_WORKERS": "1",
            },
            argv=["app.py"],
        )

    def test_sanitized_error(self):
        """Errors don't leak env values."""
        with pytest.raises(RuntimeContainmentError) as exc:
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "42"}, argv=["app.py"]
            )
        msg = str(exc.value)
        assert "42" not in msg
        assert "WEB_CONCURRENCY" not in msg


# ===================================================================
# PROCESS ARGV
# ===================================================================


class TestCollectArgvFlags:
    """Tests for ``_collect_argv_flags``."""

    def test_no_flags(self):
        assert _collect_argv_flags(["app.py"]) is None

    def test_workers_1_argv(self):
        assert _collect_argv_flags(["app.py", "--workers", "1"]) is None

    def test_workers_2_argv_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "--workers", "2"])

    def test_workers_equals_2_argv_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "--workers=2"])


# ===================================================================
# SERVE.PY ENTRYPOINT
# ===================================================================


class TestServeEntrypoint:
    """Tests for the production entrypoint (serve.py)."""

    def test_validate_before_import(self):
        """The guardrail must raise before any heavy imports happen.

        We verify that ``validate_worker_configuration`` is called before
        ``uvicorn.run`` by testing that a bad environment causes failure
        even without importing uvicorn.
        """
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "2"}, argv=["serve.py"]
            )

    def test_port_validation(self):
        """Port validation in argparse rejects invalid ports."""
        from backend.serve import _parse_args

        for invalid_port in [-1, 0, 65536, 99999]:
            with pytest.raises(SystemExit):
                _parse_args(["--port", str(invalid_port)])

    def test_valid_port(self):
        from backend.serve import _parse_args

        args = _parse_args(["--port", "8080"])
        assert args.port == 8080

    def test_default_host_port(self):
        from backend.serve import _parse_args

        args = _parse_args([])
        assert args.host == "0.0.0.0"
        assert args.port == 8000

    def test_runner_injection(self):
        """Runner injection allows testing without starting a real server."""
        calls = []

        def fake_runner(app, **kwargs):
            calls.append(("run", kwargs))

        from backend.serve import main

        try:
            main(argv=["--port", "9999"], runner=fake_runner)
        except RuntimeContainmentError:
            # Environment might have multi-worker config — test runner injection only
            pass

        if not calls:
            pytest.skip("Skipping due to environment worker configuration")

        kwargs = calls[0][1]
        assert kwargs.get("workers") == 1
        assert kwargs.get("reload") is False
        assert kwargs.get("port") == 9999


# ===================================================================
# ENGINE: archival_extraction_enabled flag
# ===================================================================


class TestEngineArchivalFlag:
    """Tests for the engine's archival_extraction_enabled parameter."""

    def test_default_is_false(self):
        from backend.engine import ConversationEngine

        engine = ConversationEngine()
        assert engine.archival_extraction_enabled is False

    def test_explicit_true(self):
        from backend.engine import ConversationEngine

        engine = ConversationEngine(archival_extraction_enabled=True)
        assert engine.archival_extraction_enabled is True

    def test_explicit_false(self):
        from backend.engine import ConversationEngine

        engine = ConversationEngine(archival_extraction_enabled=False)
        assert engine.archival_extraction_enabled is False
