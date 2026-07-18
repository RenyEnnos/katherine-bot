import subprocess
import pytest
import os

@pytest.fixture(scope="module")
def run_supabase_cli():
    def _run(cmd):
        # Never echo secrets: capture output and only surface the command name on failure.
        res = subprocess.run(f"supabase {cmd}", shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            raise Exception(f"Supabase CLI failed ({cmd}): {res.stderr[:500]}")
        return res.stdout
    return _run

@pytest.mark.database_integration
def test_legacy_upgrade(run_supabase_cli):
    if not os.path.exists("supabase/migrations/20240101000000_baseline.sql"):
        pytest.skip("Not running in project root with migrations")

    hardening = "supabase/migrations/20240101000002_secure_server_owned_tables.sql"
    hardening_tmp = "supabase/20240101000002_secure_server_owned_tables.sql.tmp"

    # Move the hardening migration aside so `db reset` only applies the baseline (legacy schema).
    os.rename(hardening, hardening_tmp)

    try:
        run_supabase_cli("db reset")

        # Seed legacy data using the supported `db query` interface (not `db execute`).
        run_supabase_cli("db query --file supabase/tests/legacy_upgrade_fixture.sql")

        # Restore and apply the pending hardening migration explicitly (hermetic, local).
        os.rename(hardening_tmp, hardening)
        run_supabase_cli(f"db query --file {hardening}")

        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not key:
            key_out = run_supabase_cli("status -o env")
            for line in key_out.split("\n"):
                if line.startswith("SERVICE_ROLE_KEY="):
                    key = line.split("=", 1)[1].strip('"')
                    break

        client = create_client(url, key)
        res = client.table("profiles").select("*").eq("user_id", "legacy_user_1").execute()
        assert len(res.data) == 1, "Legacy data not preserved"

        # Now simulate incompatible legacy data that must fail the hardening migration.
        os.rename(hardening, hardening_tmp)
        run_supabase_cli("db reset")
        run_supabase_cli(
            "db query --query \"INSERT INTO public.profiles (user_id) VALUES ('legacy_user_invalid'); "
            "INSERT INTO public.chat_logs (user_id, role, content) VALUES ('legacy_user_invalid', 'user', '');\""
        )
        os.rename(hardening_tmp, hardening)

        with pytest.raises(Exception) as exc:
            run_supabase_cli(f"db query --file {hardening}")

        msg = str(exc.value).lower()
        assert "23514" in str(exc.value) or "check constraint" in msg

    finally:
        # Restore the hardening migration file if it was moved aside.
        if os.path.exists(hardening_tmp):
            os.rename(hardening_tmp, hardening)
        # Put it aside so `db reset` applies only the baseline (avoids re-applying an
        # already-applied hardening migration, which would error on existing constraints).
        if os.path.exists(hardening):
            os.rename(hardening, hardening_tmp)
        try:
            run_supabase_cli("db reset")
        finally:
            if os.path.exists(hardening_tmp):
                os.rename(hardening_tmp, hardening)
