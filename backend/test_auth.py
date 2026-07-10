import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY
from backend.main import app, engine

client = TestClient(app)

class MockUser:
    def __init__(self, id):
        self.id = id

class MockAuthResponse:
    def __init__(self, user):
        self.user = user

@pytest.fixture
def mock_supabase():
    with patch.object(engine.memory_manager, 'supabase', MagicMock()) as mock_sb:
        yield mock_sb

@pytest.fixture
def mock_engine_process():
    with patch.object(engine, 'process_turn', return_value=("Mock response", {})) as mock_process:
        yield mock_process

def test_missing_token(mock_supabase):
    response = client.post("/chat", json={"message": "Hello"})
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]

    response = client.get("/history")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]

def test_invalid_token(mock_supabase):
    mock_supabase.auth.get_user.side_effect = Exception("Invalid JWT")

    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"

def test_user_is_none(mock_supabase):
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=None)
    response = client.get("/history", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"

def test_service_unavailable():
    with patch.object(engine.memory_manager, 'supabase', None):
        response = client.post("/chat", json={"message": "Hi"}, headers={"Authorization": "Bearer t"})
        assert response.status_code == 503
        assert response.json()["detail"] == "Authentication service unavailable"

def test_valid_token(mock_supabase, mock_engine_process):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Mock response"
    mock_engine_process.assert_called_once_with("user123", "Hello", ANY)

def test_spoofing_user_id_in_chat(mock_supabase, mock_engine_process):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client.post(
        "/chat",
        json={"user_id": "other_user", "message": "Hello"},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    # ensure it was called with 'user123', the ID from the token, not 'other_user'
    mock_engine_process.assert_called_once_with("user123", "Hello", ANY)

def test_history_valid_token(mock_supabase):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    # Mocking the supabase table response
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_eq = MagicMock()
    mock_select.eq.return_value = mock_eq
    mock_order = MagicMock()
    mock_eq.order.return_value = mock_order
    mock_limit = MagicMock()
    mock_order.limit.return_value = mock_limit

    class MockData:
        def __init__(self, data):
            self.data = data

    mock_limit.execute.return_value = MockData(data=[{"content": "msg1"}])

    response = client.get(
        "/history",
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    # It returns data[::-1] so msg1 is still the first
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "msg1"

    # check that we queried for "user123"
    mock_select.eq.assert_called_once_with("user_id", "user123")
