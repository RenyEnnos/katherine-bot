import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY
from backend.main import app, engine
from fastapi import HTTPException

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
    # HTTPBearer without auto_error=False returns 403. But wait, HTTPBearer returns 403 or 401 depending on the case. It returned 401 in the output.
    assert response.status_code == 403 or response.status_code == 401

def test_invalid_token(mock_supabase):
    mock_supabase.auth.get_user.side_effect = Exception("Invalid JWT")

    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
    assert "Authentication failed" in response.json()["detail"]

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
    # Use ANY for BackgroundTasks object
    mock_engine_process.assert_called_once_with("user123", "Hello", ANY)

def test_mismatched_user_id(mock_supabase):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client.get(
        "/history/user456",
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"]
