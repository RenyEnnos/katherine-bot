"""Test the legacy-to-hardened upgrade path using real Supabase migrations.

This test verifies that:
1. A baseline-only database can be seeded with valid legacy data and then hardened
   via ``supabase migration up --local``, preserving the legacy data.
2. Invalid legacy data causes the hardening migration to fail without destroying data.

The test manipulates migration files to create these scenarios and always restores
them in ``finally`` blocks.
"""

import json
import os
import logging
import subprocess
import pytest

from backend.supabase_cli import run_supabase_op

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def supabase_service_client():
    """Create a Supabase service-role client for querying state after upgrade."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        result = run_supabase_op(
            "legacy_state_query",
            ["status", "-o", "env"],
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("Could not extract service role key from supabase status")
        for line in result.stdout.splitlines():
            if line.startswith("SERVICE_ROLE_KEY="):
                key = line.split("=", 1)[1].strip('"')
                break
        if not key:
            pytest.skip("SERVICE_ROLE_KEY not found")
    return create_client(url, key)


def _run_supabase(op_id: str, args: list[str], check: bool = True):
    """Run a Supabase CLI command via the sanitized helper."""
    result = run_supabase_op(op_id, args, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"Supabase operation failed: {op_id}")
    return result


def _run_fixture_file(filepath: str):
    """Execute a multi-statement SQL fixture file via psql.

    ``supabase db query --file`` does not support multiple SQL statements.
    This helper runs the file directly with psql on the local database,
    using the default Supabase local credentials (postgres:postgres).
    """
    result = subprocess.run(
        [
            "psql",
            "-h", "127.0.0.1",
            "-p", "54322",
            "-U", "postgres",
            "-d", "postgres",
            "-f", filepath,
            "-q",  # quiet mode
            "-v", "ON_ERROR_STOP=1",  # fail on first SQL error
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": "postgres"},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Fixture execution failed: {filepath} (psql exited {result.returncode})"
        )


# ---------------------------------------------------------------------------
# JSON-based query helpers (no textual CLI parsing)
# ---------------------------------------------------------------------------


def _parse_json_scalar(
    stdout: str,
    expected_key: str,
    expected_type: type,
    type_name: str,
    *,
    reject_bool: bool = False,
):
    """Parse JSON scalar output from ``supabase db query --output-format json``.

    Validates that the JSON structure is a list with exactly one dict containing
    exactly the *expected_key* and that the value matches *expected_type*.  On any
    mismatch raises ``AssertionError`` with a constant, sanitized message that never
    includes SQL, stdout, stderr, or sensitive markers.

    When *reject_bool* is True (used for integer queries) Python booleans are
    rejected because ``bool`` is a subtype of ``int`` in Python.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise AssertionError("Query result: invalid JSON response")

    if not isinstance(data, list):
        raise AssertionError("Query result: expected a list")
    if len(data) != 1:
        raise AssertionError("Query result: expected exactly one row")
    if not isinstance(data[0], dict):
        raise AssertionError("Query result: expected a JSON object")
    if len(data[0]) != 1:
        raise AssertionError("Query result: unexpected columns")
    if expected_key not in data[0]:
        raise AssertionError("Query result: missing expected key")

    value = data[0][expected_key]

    if reject_bool and isinstance(value, bool):
        raise AssertionError("Query result: expected an integer, got boolean")
    if not isinstance(value, expected_type):
        raise AssertionError(f"Query result: expected a {type_name} value")

    return value


def _query_scalar_bool(query: str, expected_key: str) -> bool:
    """Execute a SQL query returning a single boolean scalar via explicit JSON output.

    Wraps query with ``--agent=no --output-format json`` to get deterministic
    machine-readable output.  The query must alias its single result column to
    *expected_key*.

    Returns:
        The parsed boolean value.

    Raises:
        AssertionError: On any structural or type mismatch, with a sanitized message.
    """
    res = _run_supabase(
        "legacy_state_query",
        ["db", "query", "--agent=no", "--output-format", "json", query],
    )
    return _parse_json_scalar(res.stdout, expected_key, bool, "boolean")


def _query_scalar_int(query: str, expected_key: str) -> int:
    """Execute a SQL query returning a single integer scalar via explicit JSON output.

    Wraps query with ``--agent=no --output-format json`` to get deterministic
    machine-readable output.  The query must alias its single result column to
    *expected_key*.

    Returns:
        The parsed integer value (non-negative).

    Raises:
        AssertionError: On any structural or type mismatch, with a sanitized message.
    """
    res = _run_supabase(
        "legacy_state_query",
        ["db", "query", "--agent=no", "--output-format", "json", query],
    )
    value = _parse_json_scalar(
        res.stdout, expected_key, int, "integer", reject_bool=True
    )
    if value < 0:
        raise AssertionError("Query result: expected a non-negative integer")
    return value


# ---------------------------------------------------------------------------
# Helpers for moving migration files aside/back
# ---------------------------------------------------------------------------
HARDENING = "supabase/migrations/20240101000002_secure_server_owned_tables.sql"
HARDENING_TMP = "supabase/migrations/20240101000002_secure_server_owned_tables.sql.tmp"


def _move_hardening_aside():
    if os.path.exists(HARDENING) and not os.path.exists(HARDENING_TMP):
        os.rename(HARDENING, HARDENING_TMP)


def _restore_hardening():
    if os.path.exists(HARDENING_TMP) and not os.path.exists(HARDENING):
        os.rename(HARDENING_TMP, HARDENING)


def _ensure_hardening_present():
    if os.path.exists(HARDENING_TMP):
        if os.path.exists(HARDENING):
            os.remove(HARDENING_TMP)
        else:
            os.rename(HARDENING_TMP, HARDENING)


# ---------------------------------------------------------------------------
# Shared query constants
# ---------------------------------------------------------------------------

TABLES = ["profiles", "chat_logs", "memories", "archival_extractions"]

_MIGRATION_VERSION_SQL = (
    "SELECT EXISTS("
    "SELECT 1 FROM supabase_migrations.schema_migrations "
    "WHERE version = '20240101000002'"
    ") AS result"
)

_TABLE_RLS_SQL = (
    "SELECT EXISTS("
    "SELECT 1 FROM pg_class WHERE oid = '{tbl}'::regclass "
    "AND relrowsecurity = true"
    ") AS result"
)

_TABLE_FORCE_RLS_SQL = (
    "SELECT EXISTS("
    "SELECT 1 FROM pg_class WHERE oid = '{tbl}'::regclass "
    "AND relforcerowsecurity = true"
    ") AS result"
)

# ---------------------------------------------------------------------------
# SCENARIO 1: Valid legacy upgrade
# ---------------------------------------------------------------------------


@pytest.mark.database_integration
def test_valid_legacy_upgrade(supabase_service_client):
    _move_hardening_aside()
    try:
        _run_supabase("legacy_baseline_reset", ["db", "reset"])

        _run_fixture_file("supabase/fixtures/legacy_upgrade_valid.sql")

        _restore_hardening()
        _run_supabase("legacy_hardening_apply", ["migration", "up", "--local"])

        # ---- Verify migration timestamp ----
        assert _query_scalar_bool(_MIGRATION_VERSION_SQL, "result"), (
            "Hardening migration timestamp not registered"
        )

        # ---- Verify legacy data preserved ----
        svc = supabase_service_client

        profiles_res = svc.table("profiles").select("*").eq(
            "user_id", "legacy_user_valid"
        ).execute()
        assert len(profiles_res.data) == 1
        assert profiles_res.data[0]["user_id"] == "legacy_user_valid"

        chat_res = svc.table("chat_logs").select("*").eq(
            "user_id", "legacy_user_valid"
        ).execute()
        assert len(chat_res.data) == 1
        assert chat_res.data[0]["content"] == "legacy message"
        assert chat_res.data[0]["role"] == "user"

        # ---- RLS and FORCE RLS enabled on all 4 tables ----
        for tbl in TABLES:
            assert _query_scalar_bool(
                _TABLE_RLS_SQL.format(tbl=tbl), "result"
            ), f"RLS not enabled for {tbl}"
            assert _query_scalar_bool(
                _TABLE_FORCE_RLS_SQL.format(tbl=tbl), "result"
            ), f"FORCE RLS not enabled for {tbl}"

        # ---- Constraints on chat_logs ----
        assert _query_scalar_bool(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_role_check' AND conrelid = 'chat_logs'::regclass"
            ") AS result",
            "result",
        ), "chat_logs_role_check not found"

        assert _query_scalar_bool(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_content_check' AND conrelid = 'chat_logs'::regclass"
            ") AS result",
            "result",
        ), "chat_logs_content_check not found"

        # ---- FK on chat_logs ----
        assert _query_scalar_bool(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_user_id_fkey' AND conrelid = 'chat_logs'::regclass"
            ") AS result",
            "result",
        ), "chat_logs_user_id_fkey not found"

        # ---- Composite index ----
        assert _query_scalar_bool(
            "SELECT EXISTS("
            "SELECT 1 FROM pg_indexes "
            "WHERE indexname = 'chat_logs_user_id_created_at_id_idx' "
            "AND tablename = 'chat_logs'"
            ") AS result",
            "result",
        ), "chat_logs_user_id_created_at_id_idx not found"

        # ---- Grants for service_role ----
        for tbl in TABLES:
            for priv in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
                assert _query_scalar_bool(
                    "SELECT EXISTS("
                    "SELECT 1 FROM information_schema.role_table_grants "
                    f"WHERE grantee = 'service_role' "
                    f"AND table_name = '{tbl}' "
                    f"AND privilege_type = '{priv}'"
                    ") AS result",
                    "result",
                ), f"Missing {priv} for service_role on {tbl}"

        # ---- Sequence: service_role USAGE ----
        assert _query_scalar_bool(
            "SELECT EXISTS("
            "SELECT 1 FROM information_schema.role_usage_grants "
            "WHERE grantee = 'service_role' "
            "AND object_name = 'chat_logs_id_seq' "
            "AND privilege_type = 'USAGE'"
            ") AS result",
            "result",
        ), "Missing USAGE for service_role on chat_logs_id_seq"

        # ---- No sequence privileges for anon / authenticated ----
        for role in ["anon", "authenticated"]:
            assert not _query_scalar_bool(
                "SELECT EXISTS("
                "SELECT 1 FROM information_schema.role_usage_grants "
                f"WHERE grantee = '{role}' AND object_name = 'chat_logs_id_seq'"
                ") AS result",
                "result",
            ), f"Unexpected sequence privileges for {role}"

        # ---- Function: service_role EXECUTE on match_memories ----
        assert _query_scalar_bool(
            "SELECT has_function_privilege('service_role', "
            "'public.match_memories(vector, double precision, integer, text)', "
            "'EXECUTE') AS result",
            "result",
        ), "service_role missing EXECUTE on match_memories"

        # ---- No function EXECUTE for anon / authenticated ----
        for role in ["anon", "authenticated"]:
            assert not _query_scalar_bool(
                f"SELECT has_function_privilege('{role}', "
                "'public.match_memories(vector, double precision, integer, text)', "
                "'EXECUTE') AS result",
                "result",
            ), f"{role} should not have EXECUTE on match_memories"

        # ---- PUBLIC has no privileges (effective check via has_*_privilege) ----
        for tbl in TABLES:
            assert not _query_scalar_bool(
                "SELECT has_table_privilege('public', "
                f"'public.{tbl}', "
                "'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'"
                ") AS result",
                "result",
            ), f"PUBLIC should have no privileges on {tbl}"

        assert not _query_scalar_bool(
            "SELECT has_sequence_privilege('public', "
            "'public.chat_logs_id_seq', "
            "'USAGE, SELECT, UPDATE') AS result",
            "result",
        ), "PUBLIC should have no privileges on chat_logs_id_seq"

        assert not _query_scalar_bool(
            "SELECT has_function_privilege('public', "
            "'public.match_memories(vector, double precision, integer, text)', "
            "'EXECUTE') AS result",
            "result",
        ), "PUBLIC should not have EXECUTE on match_memories"

    finally:
        _ensure_hardening_present()


# ---------------------------------------------------------------------------
# SCENARIO 2: Invalid legacy data → non-destructive failure
# ---------------------------------------------------------------------------


@pytest.mark.database_integration
def test_invalid_legacy_rejected(supabase_service_client):
    _move_hardening_aside()
    try:
        _run_supabase("legacy_baseline_reset", ["db", "reset"])

        _run_fixture_file("supabase/fixtures/legacy_upgrade_valid.sql")
        _run_fixture_file("supabase/fixtures/legacy_upgrade_invalid.sql")

        _restore_hardening()

        # Attempt to apply hardening — should fail with SQLSTATE 23514
        res = _run_supabase(
            "legacy_hardening_apply", ["migration", "up", "--local"], check=False
        )
        assert res.returncode != 0, (
            "Expected hardening migration to fail with invalid data"
        )
        # Verify the failure is specifically the preflight constraint check
        assert "23514" in res.stderr, (
            "Expected SQLSTATE 23514 from preflight validation"
        )

        # Verify hardening migration timestamp NOT registered
        assert not _query_scalar_bool(_MIGRATION_VERSION_SQL, "result"), (
            "Hardening migration was registered despite invalid data"
        )

        # Verify all data preserved
        svc = supabase_service_client

        assert _query_scalar_int(
            "SELECT count(*)::int AS count FROM public.profiles", "count"
        ) == 2, "Expected 2 profiles preserved"
        assert _query_scalar_int(
            "SELECT count(*)::int AS count FROM public.chat_logs", "count"
        ) == 2, "Expected 2 chat logs preserved"

        # Valid data intact
        profiles_res = svc.table("profiles").select("*").eq(
            "user_id", "legacy_user_valid"
        ).execute()
        assert len(profiles_res.data) == 1, "Valid profile was affected"

        chat_res = svc.table("chat_logs").select("*").eq(
            "user_id", "legacy_user_valid"
        ).execute()
        assert len(chat_res.data) == 1, "Valid chat log was affected"
        assert chat_res.data[0]["content"] == "legacy message"
        assert chat_res.data[0]["role"] == "user"

        # Invalid data also preserved (not deleted, corrected, or truncated)
        profiles_inv = svc.table("profiles").select("*").eq(
            "user_id", "legacy_user_invalid"
        ).execute()
        assert len(profiles_inv.data) == 1, "Invalid profile was deleted"

        chat_inv = svc.table("chat_logs").select("*").eq(
            "user_id", "legacy_user_invalid"
        ).execute()
        assert len(chat_inv.data) == 1, "Invalid chat log was deleted"
        assert chat_inv.data[0]["content"] == ""
        assert chat_inv.data[0]["role"] == "user"

    finally:
        _ensure_hardening_present()
