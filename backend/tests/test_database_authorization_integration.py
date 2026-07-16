import os
import pytest
from supabase import create_client

@pytest.fixture(scope="module")
def supabase_url():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        pytest.skip("SUPABASE_URL not set. Run inside CI or with local Supabase.")
    return url

@pytest.fixture(scope="module")
def service_role_key():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY not set.")
    return key

@pytest.fixture(scope="module")
def anon_key():
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        pytest.skip("SUPABASE_ANON_KEY not set.")
    return key

@pytest.fixture(scope="module")
def service_client(supabase_url, service_role_key):
    return create_client(supabase_url, service_role_key)

@pytest.fixture(scope="module")
def anon_client(supabase_url, anon_key):
    return create_client(supabase_url, anon_key)

@pytest.fixture(scope="module")
def auth_client_a(supabase_url, anon_key, service_client):
    email = "user_a@test.com"
    password = "password123"
    client = create_client(supabase_url, anon_key)

    # Try to clean up first
    try:
        users = service_client.auth.admin.list_users()
        for u in users:
            if u.email == email:
                service_client.auth.admin.delete_user(u.id)
    except Exception:
        pass

    client.auth.sign_up({"email": email, "password": password})
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, res.user.id

@pytest.fixture(scope="module")
def auth_client_b(supabase_url, anon_key, service_client):
    email = "user_b@test.com"
    password = "password123"
    client = create_client(supabase_url, anon_key)

    # Try to clean up first
    try:
        users = service_client.auth.admin.list_users()
        for u in users:
            if u.email == email:
                service_client.auth.admin.delete_user(u.id)
    except Exception:
        pass

    client.auth.sign_up({"email": email, "password": password})
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, res.user.id

# Tests for ANON client
def test_anon_cannot_access_tables(anon_client):
    tables = ["profiles", "chat_logs", "memories", "archival_extractions"]
    for table in tables:
        # Select
        res = anon_client.table(table).select("*").execute()
        assert len(res.data) == 0, f"Anon should not select from {table}"

        # Insert
        try:
            anon_client.table(table).insert({"id": "test"}).execute()
            assert False, f"Anon should not be able to insert into {table}"
        except Exception:
            pass

# Tests for AUTH clients
def test_auth_a_cannot_access_own_data(auth_client_a, service_client):
    client, uid = auth_client_a
    # Ensure a profile exists for A
    service_client.table("profiles").insert({"user_id": uid}).execute()

    # Select
    res = client.table("profiles").select("*").execute()
    assert len(res.data) == 0, "Auth User A should not select own profile"

def test_auth_a_cannot_access_b_data(auth_client_a, auth_client_b, service_client):
    client_a, uid_a = auth_client_a
    _, uid_b = auth_client_b

    # Ensure profile for B
    try:
        service_client.table("profiles").insert({"user_id": uid_b}).execute()
    except Exception:
        pass

    res = client_a.table("profiles").select("*").eq("user_id", uid_b).execute()
    assert len(res.data) == 0, "Auth User A should not select B's profile"

# Forging user_id
def test_forging_user_id_blocked(auth_client_a, auth_client_b):
    client_a, uid_a = auth_client_a
    _, uid_b = auth_client_b

    try:
        client_a.table("profiles").insert({"user_id": uid_b}).execute()
        assert False, "Auth User A should not insert with B's id"
    except Exception:
        pass

# Tests for SERVICE ROLE
def test_service_role_capabilities(service_client):
    # 7. Create profile
    uid = "service_test_user_1"
    try:
        service_client.table("profiles").delete().eq("user_id", uid).execute()
    except Exception:
        pass

    res = service_client.table("profiles").insert({"user_id": uid}).execute()
    assert len(res.data) == 1

    # 8. Update snapshots
    res = service_client.table("profiles").update({"persona_config": "test"}).eq("user_id", uid).execute()
    assert len(res.data) == 1

    # 9. Save turn
    res1 = service_client.table("chat_logs").insert({"user_id": uid, "role": "user", "content": "hello"}).execute()
    res2 = service_client.table("chat_logs").insert({"user_id": uid, "role": "assistant", "content": "hi"}).execute()
    assert len(res1.data) == 1
    assert len(res2.data) == 1

    # 10. Load history
    res = service_client.table("chat_logs").select("*").eq("user_id", uid).execute()
    assert len(res.data) == 2

    # 11. Persist/Load extraction
    log_id = res1.data[0]['id']
    ext_data = {
        "user_id": uid,
        "source_chat_log_id": log_id,
        "extractor_version": 1,
        "schema_version": 1,
        "idempotency_key": "test_idem",
        "facts": [{"content": "fact1"}]
    }
    res = service_client.table("archival_extractions").insert(ext_data).execute()
    assert len(res.data) == 1

    res = service_client.table("archival_extractions").select("*").eq("user_id", uid).execute()
    assert len(res.data) == 1

def test_match_memories_access(anon_client, auth_client_a, service_client):
    params = {"query_embedding": [0]*384, "match_threshold": 0.5, "match_count": 5, "filter_user_id": "test"}

    # 12. Anon
    try:
        anon_client.rpc("match_memories", params).execute()
        assert False, "Anon should not execute match_memories"
    except Exception:
        pass

    # 12. Auth A
    client_a, _ = auth_client_a
    try:
        client_a.rpc("match_memories", params).execute()
        assert False, "Auth A should not execute match_memories"
    except Exception:
        pass

    # 13. Service Role
    try:
        res = service_client.rpc("match_memories", params).execute()
        assert type(res.data) == list
    except Exception as e:
        assert False, f"Service role should execute match_memories: {e}"
