import subprocess
import pytest
import os
import shutil

@pytest.fixture(scope="module")
def run_supabase_cli():
    def _run(cmd):
        res = subprocess.run(f"supabase {cmd}", shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            raise Exception(f"Supabase CLI failed: {res.stderr}")
        return res.stdout
    return _run

def test_legacy_upgrade(run_supabase_cli):
    # This must be run from the root where `supabase` is configured, but tests run in root via CI.
    if not os.path.exists("supabase/migrations/20240101000000_baseline.sql"):
        pytest.skip("Not running in project root with migrations")

    os.rename("supabase/migrations/20240101000002_secure_server_owned_tables.sql", "supabase/20240101000002_secure_server_owned_tables.sql.tmp")

    try:
        run_supabase_cli("db reset")
        run_supabase_cli("db execute --file supabase/tests/legacy_upgrade_fixture.sql")

        os.rename("supabase/20240101000002_secure_server_owned_tables.sql.tmp", "supabase/migrations/20240101000002_secure_server_owned_tables.sql")

        run_supabase_cli("migration up")

        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "http://127.0.0.1:54321")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not key:
            key_out = run_supabase_cli("status -o env")
            for line in key_out.split('\n'):
                if line.startswith('SERVICE_ROLE_KEY='):
                    key = line.split('=')[1].strip('"')

        client = create_client(url, key)
        res = client.table("profiles").select("*").eq("user_id", "legacy_user_1").execute()
        assert len(res.data) == 1, "Legacy data not preserved"

        os.rename("supabase/migrations/20240101000002_secure_server_owned_tables.sql", "supabase/20240101000002_secure_server_owned_tables.sql.tmp")
        run_supabase_cli("db reset")

        run_supabase_cli("db execute --query \"INSERT INTO public.profiles (user_id) VALUES ('legacy_user_invalid'); INSERT INTO public.chat_logs (user_id, role, content) VALUES ('legacy_user_invalid', 'user', '');\"")

        os.rename("supabase/20240101000002_secure_server_owned_tables.sql.tmp", "supabase/migrations/20240101000002_secure_server_owned_tables.sql")

        with pytest.raises(Exception) as exc:
            run_supabase_cli("migration up")

        assert "23514" in str(exc.value) or "check constraint" in str(exc.value).lower()

    finally:
        if os.path.exists("supabase/20240101000002_secure_server_owned_tables.sql.tmp"):
            os.rename("supabase/20240101000002_secure_server_owned_tables.sql.tmp", "supabase/migrations/20240101000002_secure_server_owned_tables.sql")
        try:
            run_supabase_cli("db reset")
        except:
            pass
