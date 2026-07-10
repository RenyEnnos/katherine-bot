import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, ANY

import sys
from unittest.mock import MagicMock


import os
os.environ['GROQ_API_KEY'] = 'mock_key'
os.environ['SUPABASE_URL'] = 'http://mock'
os.environ['SUPABASE_KEY'] = 'mock_key'

sys.modules['sentence_transformers'] = MagicMock()
# Mock Supabase directly to prevent local init without keys
sys.modules['supabase'] = MagicMock()

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

def test_missing_token(mock_supabase, mock_engine_process):
    response = client.post("/chat", json={"message": "Hello"})
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]
    assert response.headers.get("WWW-Authenticate") == "Bearer"

    response = client.get("/history")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    mock_engine_process.assert_not_called()

def test_invalid_scheme(mock_supabase):
    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Basic x"}
    )
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"

def test_invalid_token(mock_supabase, mock_engine_process):
    mock_supabase.auth.get_user.side_effect = AuthApiError("Internal Mock JWT SDK Error", 400, "")

    response = client.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    # Ensure raw message is not leaked
    assert "Internal Mock JWT SDK Error" not in response.text
    mock_engine_process.assert_not_called()

def test_user_is_none(mock_supabase, mock_engine_process):
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=None)
    response = client.get("/history", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    mock_engine_process.assert_not_called()

def test_service_unavailable(mock_engine_process):
    with patch.object(engine.memory_manager, 'supabase', None):
        response = client.post("/chat", json={"message": "Hi"}, headers={"Authorization": "Bearer t"})
        assert response.status_code == 503
        assert response.json()["detail"] == "Authentication service unavailable"
        mock_engine_process.assert_not_called()

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

    assert response.status_code == 422
    mock_engine_process.assert_not_called()

def test_history_valid_token(mock_supabase):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

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
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "msg1"

    # Verify that it strictly uses current_user.id
    mock_select.eq.assert_called_once_with("user_id", "user123")

def test_history_legacy_route_removed(mock_supabase):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client.get(
        "/history/outro-usuario",
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 404


from gotrue.errors import AuthApiError, AuthRetryableError
import logging

def test_credential_rejection_401(mock_supabase, mock_engine_process, caplog):
    # Simulate an AuthApiError with status 400 (e.g. invalid token format)
    # AuthApiError expects message, status in constructor
    error = AuthApiError("SENSITIVE_AUTH_MARKER", 400, "error_code")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer invalid_token"}
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"
    # Ensure sensitive marker isn't logged for 401 standard validation failures
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()

def test_transport_timeout_503(mock_supabase, mock_engine_process, caplog):
    error = AuthRetryableError("SENSITIVE_AUTH_MARKER_TIMEOUT", 503)
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    # Even if logged, the marker shouldn't be exposed
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()

def test_service_error_5xx(mock_supabase, mock_engine_process, caplog):
    error = AuthApiError("SENSITIVE_AUTH_MARKER_500", 500, "error_code")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()

def test_unexpected_error_503(mock_supabase, mock_engine_process, caplog):
    error = Exception("SENSITIVE_AUTH_MARKER_UNKNOWN")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()
