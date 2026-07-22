"""Tests for runtime containment guardrails.

All tests are pure — no network, Docker, Supabase, Groq, embeddings, or FastAPI.
No module-level ``sys.modules`` mocks are used, so these tests do not
contaminate the global test suite.
"""

import os
import sys
import unittest.mock
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
        """Flag absent (None) returns False."""
        assert parse_archival_extraction_flag(None) is False

    def test_false_string(self):
        """``false`` string returns False."""
        assert parse_archival_extraction_flag("false") is False

    def test_false_uppercase(self):
        assert parse_archival_extraction_flag("FALSE") is False

    def test_false_mixed_case(self):
        assert parse_archival_extraction_flag("False") is False

    def test_true_string(self):
        """``true`` string returns True."""
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
    """Tests for the internal ``_check_gunicorn_args`` helper.

    This helper scans ALL worker flag occurrences in a tokenised string.
    """

    def test_no_worker_flag(self):
        """No worker flag is accepted."""
        _check_gunicorn_args("--timeout 120 --log-level info")

    def test_workers_1_accepted(self):
        _check_gunicorn_args("--workers 1")

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
        _check_gunicorn_args("-w 1")

    def test_w1_accepted(self):
        """-w1 is accepted."""
        _check_gunicorn_args("-w1")

    # --- Multi-declaration tests ---

    def test_duplicate_1_accepted(self):
        """Multiple --workers 1 flags are accepted."""
        _check_gunicorn_args("--workers 1 --workers 1")

    def test_duplicate_1_long_short_accepted(self):
        """Mixed long and short forms both with value 1 are accepted."""
        _check_gunicorn_args("--workers 1 -w1 --workers=1 -w 1")

    def test_mixed_1_then_2_rejected(self):
        """--workers 1 followed by --workers 2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers 1 --workers 2")

    def test_mixed_2_then_1_rejected(self):
        """--workers 2 followed by --workers 1 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers 2 --workers 1")

    def test_mixed_1_short_2_long_rejected(self):
        """-w1 followed by --workers=2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("-w1 --workers=2")

    def test_mixed_equals_1_short_2_rejected(self):
        """--workers=1 followed by -w2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers=1 -w2")

    def test_missing_value_after_first(self):
        """--workers 1 --workers with missing value is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers 1 --workers")

    def test_non_int_after_valid(self):
        """--workers 1 --workers abc is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _check_gunicorn_args("--workers 1 --workers abc")

    def test_empty_string(self):
        """Empty string (after split becomes []) is accepted (no flags)."""
        _check_gunicorn_args("")


class TestCollectArgvFlags:
    """Tests for ``_collect_argv_flags``."""

    def test_no_flags(self):
        _collect_argv_flags(["app.py"])

    def test_workers_1_argv(self):
        _collect_argv_flags(["app.py", "--workers", "1"])

    def test_workers_2_argv_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "--workers", "2"])

    def test_workers_equals_2_argv_rejected(self):
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "--workers=2"])

    def test_argv_duplicate_1_accepted(self):
        """Multiple --workers 1 in argv is accepted."""
        _collect_argv_flags(["app.py", "--workers", "1", "--workers", "1"])

    def test_argv_mixed_1_2_rejected(self):
        """argv with --workers 1 then --workers 2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "--workers", "1", "--workers", "2"])

    def test_argv_w1_workers_2_rejected(self):
        """argv with -w1 and --workers=2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            _collect_argv_flags(["app.py", "-w1", "--workers=2"])


# ===================================================================
# WORKER DETECTION — validate_worker_configuration
# ===================================================================


class TestValidateWorkerConfiguration:
    """Integration tests for the full ``validate_worker_configuration``."""

    def test_no_config(self):
        """No configuration is accepted (default = 1 worker)."""
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

    def test_gunicorn_args_empty_rejected(self):
        """Present but empty GUNICORN_CMD_ARGS is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"GUNICORN_CMD_ARGS": ""}, argv=["app.py"]
            )

    def test_gunicorn_args_whitespace_rejected(self):
        """Present but whitespace-only GUNICORN_CMD_ARGS is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"GUNICORN_CMD_ARGS": "   "}, argv=["app.py"]
            )

    def test_gunicorn_args_absent_accepted(self):
        """Absent GUNICORN_CMD_ARGS (None) is accepted."""
        validate_worker_configuration(
            env={"PATH": "/usr/bin"}, argv=["app.py"]
        )

    def test_gunicorn_args_workers_1_accepted(self):
        validate_worker_configuration(
            env={"GUNICORN_CMD_ARGS": "--workers 1"}, argv=["app.py"]
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

    def test_absent_env_var_ignored(self):
        """Absent variables are simply skipped."""
        validate_worker_configuration(
            env={"PATH": "/usr/bin"}, argv=["app.py"]
        )

    def test_multiple_1_accepted(self):
        """All sources at 1 is fine."""
        validate_worker_configuration(
            env={
                "WEB_CONCURRENCY": "1",
                "UVICORN_WORKERS": "1",
                "GUNICORN_CMD_ARGS": "--workers 1",
            },
            argv=["app.py", "--workers", "1"],
        )

    def test_sanitized_error(self):
        """Errors don't leak env values or variable names."""
        with pytest.raises(RuntimeContainmentError) as exc:
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "42"}, argv=["app.py"]
            )
        msg = str(exc.value)
        assert "42" not in msg
        assert "WEB_CONCURRENCY" not in msg

    # --- Cross-source conflict tests ---

    def test_web_concurrency_1_argv_2_rejected(self):
        """WEB_CONCURRENCY=1 with argv --workers 2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "1"},
                argv=["app.py", "--workers", "2"],
            )

    def test_uvicorn_1_gunicorn_2_rejected(self):
        """UVICORN_WORKERS=1 with GUNICORN_CMD_ARGS --workers 2 is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={
                    "UVICORN_WORKERS": "1",
                    "GUNICORN_CMD_ARGS": "--workers 2",
                },
                argv=["app.py"],
            )

    def test_gunicorn_repeated_1_and_2_rejected(self):
        """GUNICORN_CMD_ARGS='--workers 1 --workers 2' is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"GUNICORN_CMD_ARGS": "--workers 1 --workers 2"},
                argv=["app.py"],
            )

    def test_gunicorn_repeated_2_and_1_rejected(self):
        """GUNICORN_CMD_ARGS='--workers 2 --workers 1' is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"GUNICORN_CMD_ARGS": "--workers 2 --workers 1"},
                argv=["app.py"],
            )

    def test_argv_repeated_1_and_2_rejected(self):
        """argv=['--workers', '1', '--workers', '2'] is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={},
                argv=["app.py", "--workers", "1", "--workers", "2"],
            )

    def test_argv_repeated_2_and_1_rejected(self):
        """argv=['--workers', '2', '--workers', '1'] is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={},
                argv=["app.py", "--workers", "2", "--workers", "1"],
            )

    def test_argv_w1_workers_2_rejected(self):
        """argv=['-w1', '--workers=2'] is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={},
                argv=["app.py", "-w1", "--workers=2"],
            )

    def test_argv_workers_1_w2_rejected(self):
        """argv=['--workers=1', '-w2'] is rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={},
                argv=["app.py", "--workers=1", "-w2"],
            )

    def test_gunicorn_prefixed_accepted(self):
        """GUNICORN_CMD_ARGS='--workers 1 --timeout 120 -w1' is accepted."""
        validate_worker_configuration(
            env={"GUNICORN_CMD_ARGS": "--workers 1 --timeout 120 -w1"},
            argv=["app.py"],
        )

    def test_gunicorn_multiple_1_accepted(self):
        """GUNICORN_CMD_ARGS='--workers 1 -w1 --workers=1' is accepted."""
        validate_worker_configuration(
            env={"GUNICORN_CMD_ARGS": "--workers 1 -w1 --workers=1"},
            argv=["app.py"],
        )

    def test_argv_multiple_1_accepted(self):
        """Multiple --workers 1 in argv is accepted."""
        validate_worker_configuration(
            env={},
            argv=["app.py", "--workers", "1", "-w1", "--workers=1"],
        )

    def test_cross_source_2_1_rejected(self):
        """Env has 2, argv has 1, but env wins — still rejected."""
        with pytest.raises(RuntimeContainmentError):
            validate_worker_configuration(
                env={"WEB_CONCURRENCY": "2"},
                argv=["app.py", "--workers", "1"],
            )


# ===================================================================
# SERVE.PY ENTRYPOINT
# ===================================================================


class TestServeEntrypoint:
    """Tests for the production entrypoint (serve.py).

    These tests use a fake runner, so no real Uvicorn, FastAPI, Groq,
    Supabase, or embeddings are imported.  ``backend.main`` is never
    loaded because the app is passed as a string target.
    """

    def test_validate_before_import(self):
        """A bad env must raise before any imports happen."""
        from backend.serve import main

        fake_runner = unittest.mock.MagicMock()

        with pytest.raises(RuntimeContainmentError):
            main(
                argv=["--port", "9999"],
                runner=fake_runner,
                env={"WEB_CONCURRENCY": "2"},
            )

        # The runner must NEVER be called — validation failed first.
        fake_runner.assert_not_called()

    def test_runner_injection_deterministic(self):
        """Runner injection allows deterministic testing.

        With a fake runner, no Uvicorn, FastAPI, Groq, or Supabase are
        imported.  The env and argv are fully controlled, so this test
        always runs and never skips.
        """
        from backend.serve import main, DEFAULT_APP_TARGET

        calls = []

        def fake_runner(app_target, **kwargs):
            calls.append((app_target, kwargs))

        main(
            argv=["--port", "9999"],
            runner=fake_runner,
            env={},
        )

        assert len(calls) == 1
        app_target, kwargs = calls[0]
        assert app_target == DEFAULT_APP_TARGET
        assert kwargs.get("workers") == 1
        assert kwargs.get("reload") is False
        assert kwargs.get("port") == 9999
        assert kwargs.get("host") == "0.0.0.0"

    def test_runner_injection_with_host(self):
        """Custom host is passed through to the runner."""
        from backend.serve import main, DEFAULT_APP_TARGET

        calls = []

        def fake_runner(app_target, **kwargs):
            calls.append((app_target, kwargs))

        main(
            argv=["--host", "127.0.0.1", "--port", "8080"],
            runner=fake_runner,
            env={},
        )

        assert len(calls) == 1
        app_target, kwargs = calls[0]
        assert app_target == DEFAULT_APP_TARGET
        assert kwargs.get("host") == "127.0.0.1"
        assert kwargs.get("port") == 8080
        assert kwargs.get("workers") == 1
        assert kwargs.get("reload") is False

    def test_custom_app_target(self):
        """A custom app_target string is passed to the runner."""
        from backend.serve import main

        calls = []

        def fake_runner(app_target, **kwargs):
            calls.append((app_target, kwargs))

        main(
            argv=["--port", "9999"],
            runner=fake_runner,
            env={},
            app_target="my.module:app",
        )

        assert len(calls) == 1
        app_target, kwargs = calls[0]
        assert app_target == "my.module:app"
        assert kwargs.get("workers") == 1

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

    def test_startup_order_proof(self, monkeypatch):
        """Proof that bad env fails before importing ``backend.main``.

        Uses a ``monkeypatch`` context so ``sys.modules`` is automatically
        restored after the test, even on failure.
        """
        # Ensure backend.main is absent from sys.modules at test start.
        monkeypatch.delitem(sys.modules, "backend.main", raising=False)

        from backend.serve import main

        fake_runner = unittest.mock.MagicMock()

        with pytest.raises(RuntimeContainmentError):
            main(
                argv=["--port", "9999"],
                runner=fake_runner,
                env={"WEB_CONCURRENCY": "2"},
            )

        # backend.main must NOT have been imported during the failed call.
        assert "backend.main" not in sys.modules, (
            "backend.main was imported despite validation failure"
        )

        fake_runner.assert_not_called()

    def test_runner_injection_no_heavy_imports(self):
        """Proof that with a fake runner, no heavy modules are imported.

        Captures a snapshot of ``sys.modules`` before calling ``main()``
        with a valid configuration and a fake runner, then verifies that
        no heavy application modules were loaded during the call.
        """
        snapshot = set(sys.modules.keys())

        from backend.serve import main

        calls = []

        def fake_runner(app_target, **kwargs):
            calls.append((app_target, kwargs))

        main(
            argv=["--port", "9999"],
            runner=fake_runner,
            env={},
        )

        # Determine which modules were newly added during main()
        new_keys = set(sys.modules.keys()) - snapshot

        # These modules should NOT have been imported — they are
        # heavy (FastAPI, Groq, Supabase, embeddings, Uvicorn,
        # or the application module itself).
        forbidden = {
            "backend.main",
            "uvicorn",
            "groq",
            "fastapi",
            "sentence_transformers",
            "supabase",
            "supabase_auth",
            "supabase_auth.errors",
            "dotenv",
        }
        actually_imported = new_keys & forbidden
        assert not actually_imported, (
            f"Heavy modules were imported despite fake runner: {actually_imported}"
        )

        assert len(calls) == 1
        assert calls[0][1].get("workers") == 1
        assert calls[0][1].get("reload") is False


# ===================================================================
# CONTAMINATION VERIFICATION
# ===================================================================


class TestSysModulesContamination:
    """Verifies that importing and running containment tests does not
    contaminate ``sys.modules`` with mock objects.

    These tests ensure the file plays well with the rest of the test suite
    when run in any order.
    """

    def test_no_fake_groq_after_import(self):
        """``groq`` must not be a MagicMock after importing containment."""
        from unittest.mock import MagicMock

        mod = sys.modules.get("groq")
        if mod is not None:
            assert not isinstance(mod, MagicMock), (
                "groq was replaced by a MagicMock — global contamination detected"
            )

    def test_no_fake_supabase_after_import(self):
        """``supabase`` must not be a MagicMock after importing containment."""
        from unittest.mock import MagicMock

        mod = sys.modules.get("supabase")
        if mod is not None:
            assert not isinstance(mod, MagicMock), (
                "supabase was replaced by a MagicMock — global contamination detected"
            )

    def test_no_fake_supabase_auth_after_import(self):
        """``supabase_auth`` must not be a MagicMock."""
        from unittest.mock import MagicMock

        mod = sys.modules.get("supabase_auth")
        if mod is not None:
            assert not isinstance(mod, MagicMock), (
                "supabase_auth was replaced by a MagicMock — contamination detected"
            )

    def test_no_fake_sentence_transformers_after_import(self):
        """``sentence_transformers`` must not be a MagicMock."""
        from unittest.mock import MagicMock

        mod = sys.modules.get("sentence_transformers")
        if mod is not None:
            assert not isinstance(mod, MagicMock), (
                "sentence_transformers replaced by a MagicMock — contamination detected"
            )

    def test_real_modules_retain_identity(self):
        """Well-known stdlib modules retain their original identity."""
        import os as real_os
        import sys as real_sys
        import json as real_json

        assert sys.modules["os"] is real_os
        assert sys.modules["sys"] is real_sys
        assert sys.modules["json"] is real_json
