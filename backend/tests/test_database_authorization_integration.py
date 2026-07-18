import os
import pytest
from supabase import create_client
from postgrest.exceptions import APIError

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

    from gotrue.errors import AuthApiError
    try:
        users = service_client.auth.admin.list_users()
        for u in users:
            if u.email == email:
                service_client.auth.admin.delete_user(u.id)
    except AuthApiError:
        pass

    client.auth.sign_up({"email": email, "password": password})
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, res.user.id

@pytest.fixture(scope="module")
def auth_client_b(supabase_url, anon_key, service_client):
    email = "user_b@test.com"
    password = "password123"
    client = create_client(supabase_url, anon_key)

    from gotrue.errors import AuthApiError
    try:
        users = service_client.auth.admin.list_users()
        for u in users:
            if u.email == email:
                service_client.auth.admin.delete_user(u.id)
    except AuthApiError:
        pass

    client.auth.sign_up({"email": email, "password": password})
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    return client, res.user.id

# The matrix: anon, a, b across all 4 tables for select/insert/update/delete
def assert_denied(op, *args, **kwargs):
    with pytest.raises(APIError) as exc:
        op(*args, **kwargs).execute()
    # PostgREST typically returns 401 or 403 or 42501 for RLS / permission denied.
    assert exc.value.code in ("42501", "PGRST301") or "401" in str(exc.value) or "403" in str(exc.value)


def get_valid_payload(table, uid, id_suffix="1", source_log_id=1):
    if table == "profiles":
        return {"user_id": uid, "persona_config": "test"}
    if table == "chat_logs":
        return {"user_id": uid, "role": "user", "content": "test_msg"}
    if table == "memories":
        return {"user_id": uid, "content": "mem"}
    if table == "archival_extractions":
        return {"user_id": uid, "source_chat_log_id": source_log_id, "extractor_version": 1, "schema_version": 1, "idempotency_key": f"{uid}_{id_suffix}", "facts": []}
    return {}

def test_anon_matrix(anon_client):
    tables = ["profiles", "chat_logs", "memories", "archival_extractions"]
    for table in tables:
        assert_denied(anon_client.table(table).select, "*")
        assert_denied(anon_client.table(table).insert, get_valid_payload(table, "anon", "1"))
        assert_denied(anon_client.table(table).update, {"content": "2"})
        assert_denied(anon_client.table(table).delete)

def test_auth_a_matrix(auth_client_a, auth_client_b, service_client):
    client_a, uid_a = auth_client_a
    _, uid_b = auth_client_b

    # Prepare dependencies
    service_client.table("profiles").upsert([{"user_id": uid_a}, {"user_id": uid_b}]).execute()
    log_a = service_client.table("chat_logs").insert({"user_id": uid_a, "role": "user", "content": "a"}).execute()
    log_b = service_client.table("chat_logs").insert({"user_id": uid_b, "role": "user", "content": "b"}).execute()
    log_id_a = log_a.data[0]['id']
    log_id_b = log_b.data[0]['id']

    tables = ["profiles", "chat_logs", "memories", "archival_extractions"]

    for table in tables:
        # Own data
        assert_denied(client_a.table(table).select("*").eq, "user_id", uid_a)
        assert_denied(client_a.table(table).insert, get_valid_payload(table, uid_a, "a1", log_id_a))
        assert_denied(client_a.table(table).update({"content": "2"}).eq, "user_id", uid_a)
        assert_denied(client_a.table(table).delete().eq, "user_id", uid_a)

        # B's data
        assert_denied(client_a.table(table).select("*").eq, "user_id", uid_b)
        assert_denied(client_a.table(table).insert, get_valid_payload(table, uid_b, "a2", log_id_b))
        assert_denied(client_a.table(table).update({"content": "2"}).eq, "user_id", uid_b)
        assert_denied(client_a.table(table).delete().eq, "user_id", uid_b)

def test_auth_b_matrix(auth_client_a, auth_client_b, service_client):
    client_b, uid_b = auth_client_b
    _, uid_a = auth_client_a

    res_a = service_client.table("chat_logs").select("id").eq("user_id", uid_a).limit(1).execute()
    log_id_a = res_a.data[0]['id'] if res_a.data else 1
    res_b = service_client.table("chat_logs").select("id").eq("user_id", uid_b).limit(1).execute()
    log_id_b = res_b.data[0]['id'] if res_b.data else 1

    tables = ["profiles", "chat_logs", "memories", "archival_extractions"]

    for table in tables:
        # Own data
        assert_denied(client_b.table(table).select("*").eq, "user_id", uid_b)
        assert_denied(client_b.table(table).insert, get_valid_payload(table, uid_b, "b1", log_id_b))
        assert_denied(client_b.table(table).update({"content": "2"}).eq, "user_id", uid_b)
        assert_denied(client_b.table(table).delete().eq, "user_id", uid_b)

        # A's data
        assert_denied(client_b.table(table).select("*").eq, "user_id", uid_a)
        assert_denied(client_b.table(table).insert, get_valid_payload(table, uid_a, "b2", log_id_a))
        assert_denied(client_b.table(table).update({"content": "2"}).eq, "user_id", uid_a)
        assert_denied(client_b.table(table).delete().eq, "user_id", uid_a)

def test_service_role_capabilities(service_client):
    uid = "service_test_user_1"
    service_client.table("profiles").delete().eq("user_id", uid).execute()

    res = service_client.table("profiles").insert({"user_id": uid}).execute()
    assert len(res.data) == 1

    res = service_client.table("profiles").update({"persona_config": "test"}).eq("user_id", uid).execute()
    assert len(res.data) == 1

    res1 = service_client.table("chat_logs").insert({"user_id": uid, "role": "user", "content": "hello"}).execute()
    res2 = service_client.table("chat_logs").insert({"user_id": uid, "role": "assistant", "content": "hi"}).execute()
    assert len(res1.data) == 1
    assert len(res2.data) == 1

    res = service_client.table("chat_logs").select("*").eq("user_id", uid).execute()
    assert len(res.data) == 2

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

    service_client.table("archival_extractions").delete().eq("user_id", uid).execute()
    service_client.table("chat_logs").delete().eq("user_id", uid).execute()
    res = service_client.table("profiles").delete().eq("user_id", uid).execute()
    assert len(res.data) == 1

def test_match_memories_access(anon_client, auth_client_a, service_client):
    params = {"query_embedding": [0]*384, "match_threshold": 0.5, "match_count": 5, "filter_user_id": "test"}

    assert_denied(anon_client.rpc, "match_memories", params)

    client_a, _ = auth_client_a
    assert_denied(client_a.rpc, "match_memories", params)

    # Service Role
    res = service_client.rpc("match_memories", params).execute()
    assert type(res.data) == list

def test_configuration_failures_sanitized(monkeypatch, caplog):
    import sys
    from unittest.mock import MagicMock
    sys.modules['sentence_transformers'] = MagicMock()

    # Ensure missing SUPABASE_SERVICE_ROLE_KEY behaves gracefully
    from backend.memory import MemoryManager, StateLoadError

    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_KEY", "dummy_client_key")
    monkeypatch.setenv("SUPABASE_URL", "http://dummy")

    mm = MemoryManager()

    assert mm.supabase is None, "MemoryManager should fail closed without service role key"

    with pytest.raises(StateLoadError) as exc:
        mm.load_user_state("test")

    assert "indisponível" in str(exc.value)

    # Check that secrets are not in logs
    assert "dummy_client_key" not in caplog.text
