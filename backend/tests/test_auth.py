import os
import sys
import logging
import pytest
from unittest.mock import patch, MagicMock, ANY

@pytest.fixture(autouse=True, scope="module")
def mock_external_dependencies():
    _original_modules = dict(sys.modules)
    _original_env = dict(os.environ)

    mock_env = {
        'GROQ_API_KEY': 'mock_key',
        'SUPABASE_URL': 'http://mock',
        'SUPABASE_KEY': 'mock_key'
    }
    os.environ.update(mock_env)

    # Mock modules before importing
    sys.modules['sentence_transformers'] = MagicMock()
    sys.modules['supabase'] = MagicMock()

    yield

    # Restore environment and modules directionally
    if 'backend.main' in sys.modules:
        del sys.modules['backend.main']
    if 'sentence_transformers' in sys.modules:
        del sys.modules['sentence_transformers']
    if 'supabase' in sys.modules:
        del sys.modules['supabase']

    # Restore what was actually added during the test (avoid deleting modules
    # that were imported by other test files before this module ran)
    for k in list(sys.modules.keys()):
        if k.startswith('backend.') and k not in _original_modules:
            del sys.modules[k]

    os.environ.clear()
    os.environ.update(_original_env)


@pytest.fixture
def client_app(mock_external_dependencies):
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)

@pytest.fixture
def mock_supabase():
    from backend.main import engine
    with patch.object(engine.memory_manager, 'supabase', MagicMock()) as mock_sb:
        yield mock_sb

@pytest.fixture
def mock_engine_process():
    from backend.main import engine
    with patch.object(engine, 'process_turn', return_value=("Mock response", {})) as mock_process:
        yield mock_process

class MockUser:
    def __init__(self, id):
        self.id = id

class MockAuthResponse:
    def __init__(self, user):
        self.user = user

from supabase_auth.errors import AuthApiError, AuthRetryableError

def test_missing_token(client_app, mock_supabase, mock_engine_process):
    response = client_app.post("/chat", json={"message": "Hello"})
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]
    assert response.headers.get("WWW-Authenticate") == "Bearer"

    response = client_app.get("/history")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_invalid_scheme(client_app, mock_supabase, mock_engine_process):
    response = client_app.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Basic x"}
    )
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_invalid_token(client_app, mock_supabase, mock_engine_process):
    mock_supabase.auth.get_user.side_effect = AuthApiError("Internal Mock JWT SDK Error", 400, "")

    response = client_app.post(
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
    mock_supabase.table.assert_not_called()

def test_user_is_none(client_app, mock_supabase, mock_engine_process):
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=None)
    response = client_app.get("/history", headers={"Authorization": "Bearer token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_service_unavailable(client_app, mock_supabase, mock_engine_process):
    from backend.main import engine
    with patch.object(engine.memory_manager, 'supabase', None):
        response = client_app.post("/chat", json={"message": "Hi"}, headers={"Authorization": "Bearer t"})
        assert response.status_code == 503
        assert response.json()["detail"] == "Authentication service unavailable"
        mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_valid_token(client_app, mock_supabase, mock_engine_process):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client_app.post(
        "/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Mock response"
    mock_engine_process.assert_called_once_with("user123", "Hello", ANY)

def test_spoofing_user_id_in_chat(client_app, mock_supabase, mock_engine_process):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client_app.post(
        "/chat",
        json={"user_id": "other_user", "message": "Hello"},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 422
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_history_valid_token(client_app, mock_supabase):
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

    response = client_app.get(
        "/history",
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "msg1"

    # Verify that it strictly uses current_user.id
    mock_select.eq.assert_called_once_with("user_id", "user123")

def test_history_legacy_route_removed(client_app, mock_supabase, mock_engine_process):
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client_app.get(
        "/history/outro-usuario",
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 404

def test_credential_rejection_401(client_app, mock_supabase, mock_engine_process, caplog):
    error = AuthApiError("SENSITIVE_AUTH_MARKER", 400, "error_code")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer invalid_token"}
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_transport_timeout_503(client_app, mock_supabase, mock_engine_process, caplog):
    error = AuthRetryableError("SENSITIVE_AUTH_MARKER_TIMEOUT", 503)
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_service_error_5xx(client_app, mock_supabase, mock_engine_process, caplog):
    error = AuthApiError("SENSITIVE_AUTH_MARKER_500", 500, "error_code")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_unexpected_error_503(client_app, mock_supabase, mock_engine_process, caplog):
    error = Exception("SENSITIVE_AUTH_MARKER_UNKNOWN")
    mock_supabase.auth.get_user.side_effect = error

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authentication service unavailable"
    assert "SENSITIVE_AUTH_MARKER" not in caplog.text
    assert "SENSITIVE_AUTH_MARKER" not in response.text
    mock_engine_process.assert_not_called()
    mock_supabase.table.assert_not_called()

def test_http_chat_load_failure_sanitization(client_app, mock_supabase, caplog):
    from backend.main import engine
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=MockUser("user123"))

    # Mock supabase select call to raise a sensitive exception
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("SENSITIVE_DB_LOAD_ERROR")

    # Mock LLM calls just in case
    engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = "Response"
    engine.groq_manager.chat_completion = MagicMock(return_value=m)

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal Server Error"
    assert "SENSITIVE_DB_LOAD_ERROR" not in response.text
    assert "SENSITIVE_DB_LOAD_ERROR" not in caplog.text
    assert "user123" not in response.text
    assert "user123" not in caplog.text

def test_http_chat_persistence_failure_sanitization(client_app, mock_supabase, caplog):
    from backend.main import engine
    from backend.emotional_core import EmotionalState
    from backend.relationship import UserRelationship
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=MockUser("user123"))

    # Mock load_user_state to succeed
    engine.memory_manager.load_user_state = MagicMock(return_value={
        "emotional_state": EmotionalState().to_dict(),
        "relationship_state": UserRelationship(user_id="user123").to_dict()
    })

    # Mock sync_state (update) to raise a sensitive exception
    mock_supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception("SENSITIVE_DB_SYNC_ERROR")

    # Mock LLM calls
    engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = "Response"
    engine.groq_manager.chat_completion = MagicMock(return_value=m)

    with caplog.at_level(logging.ERROR):
        response = client_app.post(
            "/chat",
            json={"message": "Hello"},
            headers={"Authorization": "Bearer some_token"}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal Server Error"
    assert "SENSITIVE_DB_SYNC_ERROR" not in response.text
    assert "SENSITIVE_DB_SYNC_ERROR" not in caplog.text
    assert "user123" not in response.text
    assert "user123" not in caplog.text

def test_chat_message_exactly_at_limit(client_app, mock_supabase, mock_engine_process):
    from backend.memory import MAX_MESSAGE_LENGTH
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client_app.post(
        "/chat",
        json={"message": "a" * MAX_MESSAGE_LENGTH},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Mock response"
    mock_engine_process.assert_called_once_with("user123", "a" * MAX_MESSAGE_LENGTH, ANY)

def test_chat_message_exceeds_limit(client_app, mock_supabase, mock_engine_process):
    from backend.memory import MAX_MESSAGE_LENGTH
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)

    response = client_app.post(
        "/chat",
        json={"message": "a" * (MAX_MESSAGE_LENGTH + 1)},
        headers={"Authorization": "Bearer valid_token"}
    )

    assert response.status_code == 422
    mock_engine_process.assert_not_called()
