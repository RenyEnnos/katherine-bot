"""Test the legacy-to-hardened upgrade path using real Supabase migrations.

This test verifies that:
1. A baseline-only database can be seeded with valid legacy data and then hardened
   via ``supabase migration up --local``, preserving the legacy data.
2. Invalid legacy data causes the hardening migration to fail without destroying data.

The test manipulates migration files to create these scenarios and always restores
them in ``finally`` blocks.
"""

import os
import pytest

from backend.supabase_cli import run_supabase_op


@pytest.fixture(scope="module")
def supabase_service_client():
    """Create a Supabase service-role client for querying state after upgrade."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        # Fallback: extract from supabase status
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
    """Run a Supabase CLI command via the sanitized helper.

    Args:
        op_id: A constant operation identifier from ALLOWED_OPS.
        args: The real subprocess arguments (e.g. ["db", "reset"]).
        check: If True, assert returncode == 0; if False, return CompletedProcess.

    Returns:
        subprocess.CompletedProcess

    Raises:
        AssertionError: If check=True and returncode != 0. Message is sanitized.
    """
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
    """Rename the hardening migration so it is not discovered by the CLI."""
    if os.path.exists(HARDENING) and not os.path.exists(HARDENING_TMP):
        os.rename(HARDENING, HARDENING_TMP)


def _restore_hardening():
    """Restore the hardening migration file."""
    if os.path.exists(HARDENING_TMP) and not os.path.exists(HARDENING):
        os.rename(HARDENING_TMP, HARDENING)


def _ensure_hardening_present():
    """Make sure the hardening file is in place (no tmp artifact)."""
    if os.path.exists(HARDENING_TMP):
        if os.path.exists(HARDENING):
            os.remove(HARDENING_TMP)
        else:
            os.rename(HARDENING_TMP, HARDENING)


def _rls_status(tbl: str) -> tuple[bool, bool]:
    """Query pg_class for RLS and FORCE RLS status on a table.

    Returns (relrowsecurity, relforcerowsecurity) as booleans.
    """
    res = _run_supabase(
        "legacy_state_query",
        [
            "db", "query", "--query",
            f"SELECT relrowsecurity, relforcerowsecurity "
            f"FROM pg_class WHERE oid = '{tbl}'::regclass",
        ],
    )
    # Output format: "t|t\n" or "f|f\n" etc.
    parts = res.stdout.strip().split("|")
    if len(parts) == 2:
        return (parts[0].strip() == "t", parts[1].strip() == "t")
    return (False, False)


# ---------------------------------------------------------------------------
# SCENARIO 1: Valid legacy upgrade
# ---------------------------------------------------------------------------
@pytest.mark.database_integration
def test_valid_legacy_upgrade(supabase_service_client):
    _move_hardening_aside()
    try:
        # 1. Apply only the baseline
        _run_supabase("legacy_baseline_reset", ["db", "reset"])

        # 2. Seed valid legacy data
        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_valid.sql"],
        )

        # 3. Restore hardening migration
        _restore_hardening()

        # 4. Apply via real migration mechanism
        _run_supabase("legacy_hardening_apply", ["migration", "up", "--local"])

        # 5. Verify the hardening migration timestamp was recorded
        ts_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT version FROM supabase_migrations.schema_migrations "
                "WHERE name = '20240101000002_secure_server_owned_tables'",
            ],
        )
        assert "20240101000002" in ts_res.stdout, (
            "Hardening migration timestamp not registered"
        )

        # 6. Verify legacy data preserved
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

        # 7. Verify hardening state after upgrade
        TABLES = ["profiles", "chat_logs", "memories", "archival_extractions"]

        # RLS and FORCE RLS
        for tbl in TABLES:
            rls_enabled, force_rls = _rls_status(tbl)
            assert rls_enabled, f"RLS not enabled for {tbl}"
            assert force_rls, f"FORCE RLS not enabled for {tbl}"

        # Constraints on chat_logs
        for constraint in ["chat_logs_role_check", "chat_logs_content_check"]:
            cr_res = _run_supabase(
                "legacy_state_query",
                [
                    "db", "query", "--query",
                    f"SELECT 1 FROM pg_constraint "
                    f"WHERE conname = '{constraint}' AND conrelid = 'chat_logs'::regclass",
                ],
            )
            assert "(1 row)" in cr_res.stdout, f"Constraint {constraint} not found"

        # FK on chat_logs
        fk_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT 1 FROM pg_constraint "
                "WHERE conname = 'chat_logs_user_id_fkey' AND conrelid = 'chat_logs'::regclass",
            ],
        )
        assert "(1 row)" in fk_res.stdout, "FK chat_logs_user_id_fkey not found"

        # Composite index
        idx_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT 1 FROM pg_indexes "
                "WHERE indexname = 'chat_logs_user_id_created_at_id_idx' "
                "AND tablename = 'chat_logs'",
            ],
        )
        assert "(1 row)" in idx_res.stdout, "Composite index not found"

        # Grants for service_role
        for tbl in TABLES:
            grant_res = _run_supabase(
                "legacy_state_query",
                [
                    "db", "query", "--query",
                    f"SELECT privilege_type FROM information_schema.role_table_grants "
                    f"WHERE grantee = 'service_role' "
                    f"AND table_name = '{tbl}' "
                    f"ORDER BY privilege_type",
                ],
            )
            assert "SELECT" in grant_res.stdout
            assert "INSERT" in grant_res.stdout
            assert "UPDATE" in grant_res.stdout
            assert "DELETE" in grant_res.stdout

        # anon, authenticated, PUBLIC have no privileges
        for role in ["anon", "authenticated", "PUBLIC"]:
            for tbl in TABLES:
                priv_res = _run_supabase(
                    "legacy_state_query",
                    [
                        "db", "query", "--query",
                        f"SELECT privilege_type FROM information_schema.role_table_grants "
                        f"WHERE grantee = '{role}' AND table_name = '{tbl}'",
                    ],
                )
                # Should return 0 rows
                assert "(0 rows)" in priv_res.stdout, (
                    f"Unexpected privileges for {role} on {tbl}: {priv_res.stdout}"
                )

        # Sequence privileges
        seq_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT privilege_type FROM information_schema.role_usage_grants "
                "WHERE grantee = 'service_role' "
                "AND object_name = 'chat_logs_id_seq' "
                "ORDER BY privilege_type",
            ],
        )
        assert "USAGE" in seq_res.stdout
        # anon/authenticated/PUBLIC should have nothing on the sequence
        for role in ["anon", "authenticated", "PUBLIC"]:
            role_seq_res = _run_supabase(
                "legacy_state_query",
                [
                    "db", "query", "--query",
                    f"SELECT privilege_type FROM information_schema.role_usage_grants "
                    f"WHERE grantee = '{role}' AND object_name = 'chat_logs_id_seq'",
                ],
            )
            assert "(0 rows)" in role_seq_res.stdout, (
                f"Unexpected sequence privileges for {role}: {role_seq_res.stdout}"
            )

        # Function privileges for match_memories
        rpc_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT has_function_privilege('service_role', "
                "'public.match_memories(vector, double precision, integer, text)', 'EXECUTE')",
            ],
        )
        assert "t" in rpc_res.stdout

        # anon and authenticated have no execute on match_memories
        for role in ["anon", "authenticated"]:
            rpc_denied = _run_supabase(
                "legacy_state_query",
                [
                    "db", "query", "--query",
                    f"SELECT has_function_privilege('{role}', "
                    "'public.match_memories(vector, double precision, integer, text)', 'EXECUTE')",
                ],
            )
            assert "f" in rpc_denied.stdout, (
                f"{role} should not have EXECUTE on match_memories"
            )

    finally:
        _ensure_hardening_present()


# ---------------------------------------------------------------------------
# SCENARIO 2: Invalid legacy data → non-destructive failure
# ---------------------------------------------------------------------------
@pytest.mark.database_integration
def test_invalid_legacy_rejected(supabase_service_client):
    _move_hardening_aside()
    try:
        # 1. Baseline only
        _run_supabase("legacy_baseline_reset", ["db", "reset"])

        # 2. Seed both valid AND invalid data
        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_valid.sql"],
        )
        _run_supabase(
            "legacy_fixture_seed",
            ["db", "query", "--file", "supabase/fixtures/legacy_upgrade_invalid.sql"],
        )

        # 3. Restore hardening attempt
        _restore_hardening()

        # 4. Attempt to apply hardening - should fail
        res = _run_supabase("legacy_hardening_apply", ["migration", "up", "--local"], check=False)
        assert res.returncode != 0, (
            "Expected hardening migration to fail with invalid data"
        )

        # 5. Verify hardening migration timestamp NOT registered
        ts_res = _run_supabase(
            "legacy_state_query",
            [
                "db", "query", "--query",
                "SELECT version FROM supabase_migrations.schema_migrations "
                "WHERE name = '20240101000002_secure_server_owned_tables'",
            ],
        )
        assert "20240101000002" not in ts_res.stdout, (
            "Hardening migration was registered despite invalid data"
        )

        # 6. Verify all data preserved (nothing deleted, corrected, or truncated)
        svc = supabase_service_client

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

        # 7. Verify all rows still present
        all_profiles = svc.table("profiles").select("*").execute()
        assert len(all_profiles.data) == 2

        all_chats = svc.table("chat_logs").select("*").execute()
        assert len(all_chats.data) == 2

    finally:
        _ensure_hardening_present()
