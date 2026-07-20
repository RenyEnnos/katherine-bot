"""Test the legacy-to-hardened upgrade path using real Supabase migrations.

This test verifies that:
1. A baseline-only database can be seeded with valid legacy data and then hardened
   via ``supabase migration up --local``, preserving the legacy data.
2. Invalid legacy data causes the hardening migration to fail without destroying data.

The test manipulates migration files to create these scenarios and always restores
them in ``finally`` blocks.
"""

import os
import logging
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
    if check:
        assert result.returncode == 0, f"Supabase operation failed: {op_id}"
    return result


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


def _table_count(table: str) -> int:
    """Return the number of rows in a table via a count query."""
    res = _run_supabase(
        "legacy_state_query",
        ["db", "query", "--query", f"SELECT count(*) FROM public.{table}"],
    )
    # Output: "  count\n-------\n     N\n(1 row)"
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.lstrip("-").isdigit():
            return int(line)
    return -1


def _row_returned(query: str) -> bool:
    """Return True if the query returns at least one row."""
    res = _run_supabase(
        "legacy_state_query",
        ["db", "query", "--query", query],
    )
    for line in res.stdout.splitlines():
        if line.strip().startswith("(") and "row" in line:
            count_str = line.strip().split("(")[1].split()[0]
            try:
                return int(count_str) > 0
            except ValueError:
                return False
    return False


# ---------------------------------------------------------------------------
# SCENARIO 1: Valid legacy upgrade
# ---------------------------------------------------------------------------
@pytest.mark.database_integration
def test_valid_legacy_upgrade(supabase_service_client):
    _move_hardening_aside()
    try:
        _run_supabase("legacy_baseline_reset", ["db", "reset"])

        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_valid.sql"],
        )

        _restore_hardening()
        _run_supabase("legacy_hardening_apply", ["migration", "up", "--local"])

        # Verify migration timestamp using the correct column: version, not name
        ts_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT version FROM supabase_migrations.schema_migrations "
                "WHERE version = '20240101000002'",
            ],
        )
        assert _row_returned(
            "SELECT 1 FROM supabase_migrations.schema_migrations "
            "WHERE version = '20240101000002'"
        ), "Hardening migration timestamp not registered"

        # Verify legacy data preserved
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

        # Verify hardening state
        TABLES = ["profiles", "chat_logs", "memories", "archival_extractions"]

        # Constraints on chat_logs
        assert _row_returned(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_role_check' AND conrelid = 'chat_logs'::regclass"
        ), "chat_logs_role_check not found"
        assert _row_returned(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_content_check' AND conrelid = 'chat_logs'::regclass"
        ), "chat_logs_content_check not found"

        # FK on chat_logs
        assert _row_returned(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'chat_logs_user_id_fkey' AND conrelid = 'chat_logs'::regclass"
        ), "chat_logs_user_id_fkey not found"

        # Composite index
        assert _row_returned(
            "SELECT 1 FROM pg_indexes "
            "WHERE indexname = 'chat_logs_user_id_created_at_id_idx' "
            "AND tablename = 'chat_logs'"
        ), "chat_logs_user_id_created_at_id_idx not found"

        # Grants for service_role
        for tbl in TABLES:
            assert _row_returned(
                f"SELECT 1 FROM information_schema.role_table_grants "
                f"WHERE grantee = 'service_role' "
                f"AND table_name = '{tbl}' "
                f"AND privilege_type = 'SELECT'"
            ), f"Missing SELECT for service_role on {tbl}"
            assert _row_returned(
                f"SELECT 1 FROM information_schema.role_table_grants "
                f"WHERE grantee = 'service_role' "
                f"AND table_name = '{tbl}' "
                f"AND privilege_type = 'INSERT'"
            ), f"Missing INSERT for service_role on {tbl}"
            assert _row_returned(
                f"SELECT 1 FROM information_schema.role_table_grants "
                f"WHERE grantee = 'service_role' "
                f"AND table_name = '{tbl}' "
                f"AND privilege_type = 'UPDATE'"
            ), f"Missing UPDATE for service_role on {tbl}"
            assert _row_returned(
                f"SELECT 1 FROM information_schema.role_table_grants "
                f"WHERE grantee = 'service_role' "
                f"AND table_name = '{tbl}' "
                f"AND privilege_type = 'DELETE'"
            ), f"Missing DELETE for service_role on {tbl}"

        # anon, authenticated, PUBLIC have no privileges
        for role in ["anon", "authenticated", "PUBLIC"]:
            for tbl in TABLES:
                assert not _row_returned(
                    f"SELECT 1 FROM information_schema.role_table_grants "
                    f"WHERE grantee = '{role}' AND table_name = '{tbl}'"
                ), f"Unexpected privileges for {role} on {tbl}"

        # Sequence privileges
        assert _row_returned(
            "SELECT 1 FROM information_schema.role_usage_grants "
            "WHERE grantee = 'service_role' "
            "AND object_name = 'chat_logs_id_seq' "
            "AND privilege_type = 'USAGE'"
        ), "Missing USAGE for service_role on chat_logs_id_seq"

        for role in ["anon", "authenticated", "PUBLIC"]:
            assert not _row_returned(
                f"SELECT 1 FROM information_schema.role_usage_grants "
                f"WHERE grantee = '{role}' AND object_name = 'chat_logs_id_seq'"
            ), f"Unexpected sequence privileges for {role}"

        # Function privileges for match_memories
        assert _row_returned(
            "SELECT 1 WHERE has_function_privilege('service_role', "
            "'public.match_memories(vector, double precision, integer, text)', 'EXECUTE')"
        ), "service_role missing EXECUTE on match_memories"

        for role in ["anon", "authenticated"]:
            assert not _row_returned(
                f"SELECT 1 WHERE has_function_privilege('{role}', "
                "'public.match_memories(vector, double precision, integer, text)', 'EXECUTE')"
            ), f"{role} should not have EXECUTE on match_memories"

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

        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_valid.sql"],
        )
        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_invalid.sql"],
        )

        _restore_hardening()

        # Attempt to apply hardening - should fail with SQLSTATE 23514
        res = _run_supabase("legacy_hardening_apply", ["migration", "up", "--local"], check=False)
        assert res.returncode != 0, "Expected hardening migration to fail with invalid data"
        # Verify the failure is specifically the preflight constraint check
        assert "23514" in res.stderr, "Expected SQLSTATE 23514 from preflight validation"

        # Verify hardening migration timestamp NOT registered
        assert not _row_returned(
            "SELECT 1 FROM supabase_migrations.schema_migrations "
            "WHERE version = '20240101000002'"
        ), "Hardening migration was registered despite invalid data"

        # Verify all data preserved
        svc = supabase_service_client

        assert _table_count("profiles") == 2, "Expected 2 profiles preserved"
        assert _table_count("chat_logs") == 2, "Expected 2 chat logs preserved"

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
