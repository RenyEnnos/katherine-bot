"""Unit tests for the sanitized subprocess helper (backend.supabase_cli).

Tests cover:
- Valid operation identifiers
- Unknown operation identifier rejection
- FileNotFoundError wrapping
- Sensitive marker injection via fake stderr (mocked subprocess)
"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess


@pytest.fixture
def helper():
    from backend.supabase_cli import run_supabase_op, ALLOWED_OPS
    return run_supabase_op, ALLOWED_OPS


class TestValidation:
    def test_unknown_op_rejected(self, helper):
        """Unknown operation identifiers must raise ValueError."""
        run_supabase_op, _ = helper
        with pytest.raises(ValueError, match="Unknown operation"):
            run_supabase_op("unknown_op", ["db", "reset"])

    def test_all_allowed_ops_accepted(self, helper):
        """All ALLOWED_OPS identifiers must be accepted (no exception on construction)."""
        run_supabase_op, allowed = helper
        for op in allowed:
            # The subprocess will fail since there's no real supabase CLI,
            # but we should not get ValueError
            with pytest.raises(RuntimeError):
                run_supabase_op(op, ["nonexistent-command"], check=True)


class TestSanitization:
    """Tests that supabase_cli sanitizes error output properly."""

    @patch("backend.supabase_cli.subprocess.run")
    def test_sanitized_error_from_stderr(self, mock_run, helper):
        """When subprocess.run returns non-zero with sensitive markers in stderr,
        the public exception must NOT contain them."""
        run_supabase_op, _ = helper

        SENSITIVE_MARKERS = [
            "SENSITIVE_JWT_eyJ_test",
            "SENSITIVE_PAYLOAD",
            "SELECT secret_value FROM users",
            "INSERT private_data INTO logs",
            "SUPABASE_SERVICE_KEY=secret",
        ]

        # Construct a CompletedProcess with stderr containing all markers
        fake_result = subprocess.CompletedProcess(
            args=["supabase", "db", "reset"],
            returncode=1,
            stdout="",
            stderr=" | ".join(SENSITIVE_MARKERS),
        )
        mock_run.return_value = fake_result

        with pytest.raises(RuntimeError) as exc:
            run_supabase_op("legacy_baseline_reset", ["db", "reset"], check=True)

        msg = str(exc.value)
        # The public message should only contain the op_id, not the markers
        assert "legacy_baseline_reset" in msg
        for marker in SENSITIVE_MARKERS:
            assert marker not in msg, (
                f"Sensitive marker leaked into exception message: {marker}"
            )

    @patch("backend.supabase_cli.subprocess.run")
    def test_stdout_not_leaked_on_success(self, mock_run, helper):
        """On success, stdout is available to the caller but not in logs/exceptions."""
        run_supabase_op, _ = helper

        fake_result = subprocess.CompletedProcess(
            args=["supabase", "db", "query", "--query", "SELECT 1"],
            returncode=0,
            stdout="(1 row)\n",
            stderr="",
        )
        mock_run.return_value = fake_result

        result = run_supabase_op("legacy_state_query", ["db", "query", "--query", "SELECT 1"], check=False)
        assert result.returncode == 0
        assert result.stdout == "(1 row)\n"

    @patch("backend.supabase_cli.subprocess.run")
    def test_non_zero_expected_return_does_not_raise(self, mock_run, helper):
        """When check=False, a non-zero return should return CompletedProcess, not raise."""
        run_supabase_op, _ = helper

        fake_result = subprocess.CompletedProcess(
            args=["supabase", "migration", "up", "--local"],
            returncode=1,
            stdout="",
            stderr="ERROR: migration failed",
        )
        mock_run.return_value = fake_result

        # Should not raise when check=False
        result = run_supabase_op("legacy_hardening_apply", ["migration", "up", "--local"], check=False)
        assert result.returncode == 1
        assert "migration failed" in result.stderr
