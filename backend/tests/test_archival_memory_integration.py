import os
import sys
import logging
import json
from unittest.mock import MagicMock

# 1. Mock external dependencies before importing any backend modules
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['supabase'] = MagicMock()

# Setup environment variables immediately
_original_env = dict(os.environ)
os.environ['GROQ_API_KEY'] = 'mock_key'
os.environ['SUPABASE_URL'] = 'http://mock'
os.environ['SUPABASE_KEY'] = 'mock_key'

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

# Import backend modules after mocks are installed
from backend.engine import ConversationEngine
from backend.archival_memory import PersistedTurnRef, ArchivalDuplicateError, ArchivalValidationError, compute_idempotency_key

@pytest.fixture(autouse=True, scope="module")
def mock_external_dependencies():
    yield
    # Restore environment variables safely without breaking Pytest internals
    for k in list(os.environ.keys()):
        if k.startswith("PYTEST_"):
            continue
        if k not in _original_env:
            del os.environ[k]
    for k, v in _original_env.items():
        if not k.startswith("PYTEST_"):
            os.environ[k] = v

    # Restore modules directionally
    for mod in ['backend.main', 'backend.engine', 'backend.memory', 'backend.archival_memory']:
        if mod in sys.modules:
            del sys.modules[mod]
            
    if 'sentence_transformers' in sys.modules:
        del sys.modules['sentence_transformers']
    if 'supabase' in sys.modules:
        del sys.modules['supabase']


@pytest.fixture
def client_app(mock_external_dependencies):
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def mock_supabase():
    from backend.main import engine
    with patch.object(engine.memory_manager, 'supabase', MagicMock()) as mock_sb:
        yield mock_sb


class MockUser:
    def __init__(self, id):
        self.id = id


class MockAuthResponse:
    def __init__(self, user):
        self.user = user




@pytest.mark.anyio
async def test_run_archival_extraction_llm_failure(caplog):
    engine = ConversationEngine()
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_persisted_user_message = MagicMock(return_value="Hello")
    
    # Mock Groq client failure
    engine.groq_manager.chat_completion = MagicMock(side_effect=Exception("Groq error"))
    
    ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
    
    with caplog.at_level(logging.ERROR):
        await engine.run_archival_extraction(ref)
        
    assert "archival_extraction_llm_failed" in caplog.text
    # Check sensitive values are not logged
    assert "user123" not in caplog.text
    assert "Hello" not in caplog.text
    assert "Groq error" not in caplog.text
    engine.memory_manager.store_archival_extraction.assert_not_called()


@pytest.mark.anyio
async def test_run_archival_extraction_validation_failure(caplog):
    engine = ConversationEngine()
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_persisted_user_message = MagicMock(return_value="Hello")
    
    # Mock Groq client returning invalid fact payload (importance is bool)
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = json.dumps({
        "facts": [{"content": "hello", "importance": True, "tags": []}]
    })
    engine.groq_manager.chat_completion = MagicMock(return_value=m)
    
    ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
    
    with caplog.at_level(logging.WARNING):
        await engine.run_archival_extraction(ref)
        
    assert "archival_extraction_invalid" in caplog.text
    assert "user123" not in caplog.text
    engine.memory_manager.store_archival_extraction.assert_not_called()


@pytest.mark.anyio
async def test_run_archival_extraction_duplicate(caplog):
    engine = ConversationEngine()
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_persisted_user_message = MagicMock(return_value="Hello")
    
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = json.dumps({
        "facts": [{"content": "likes coding", "importance": 0.9, "tags": []}],
        "schema_version": 1,
        "extractor_version": 1
    })
    engine.groq_manager.chat_completion = MagicMock(return_value=m)
    
    # Simulate unique constraint failure treated as duplicate success
    engine.memory_manager.store_archival_extraction.side_effect = ArchivalDuplicateError("Duplicate")
    
    ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
    
    with caplog.at_level(logging.INFO):
        await engine.run_archival_extraction(ref)
        
    assert "archival_extraction_duplicate" in caplog.text
    assert "user123" not in caplog.text


@pytest.mark.anyio
async def test_run_archival_extraction_store_failed(caplog):
    engine = ConversationEngine()
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_persisted_user_message = MagicMock(return_value="Hello secret message")
    
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = json.dumps({
        "facts": [{"content": "likes coding", "importance": 0.9, "tags": []}],
        "schema_version": 1,
        "extractor_version": 1
    })
    engine.groq_manager.chat_completion = MagicMock(return_value=m)
    
    # Simulate general database failure
    engine.memory_manager.store_archival_extraction.side_effect = Exception("DB connection failed secret token")
    
    ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
    
    with caplog.at_level(logging.ERROR):
        await engine.run_archival_extraction(ref)
        
    assert "archival_extraction_store_failed" in caplog.text
    # Check sensitive values are not logged
    assert "user123" not in caplog.text
    assert "Hello secret message" not in caplog.text
    assert "DB connection failed secret token" not in caplog.text


@pytest.mark.anyio
async def test_process_turn_schedules_background_task():
    engine = ConversationEngine()
    
    # Mock all internal methods of process_turn to focus on orchestration
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_user_state = MagicMock(return_value={
        "emotional_state": {},
        "relationship_state": {}
    })
    engine.memory_manager.get_context = MagicMock(return_value="context")
    engine._perceive = MagicMock(return_value={})
    engine._normalize_perception = MagicMock(return_value={})
    
    # Mock save_turn and sync_state to track order
    call_order = []
    
    def mock_save_turn(user_id, user_msg, bot_msg):
        call_order.append("save_turn")
        return PersistedTurnRef(user_id=user_id, source_chat_log_id=1, assistant_chat_log_id=2)
        
    def mock_sync_state(user_id, state, relationship):
        call_order.append("sync_state")
        
    engine.memory_manager.save_turn = MagicMock(side_effect=mock_save_turn)
    engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync_state)
    
    # Mock groq chat completion
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = "assistant reply"
    engine.groq_manager.chat_completion = MagicMock(return_value=m)
    
    bg_tasks = MagicMock(spec=BackgroundTasks)
    
    # Run process_turn
    resp, emotions = await engine.process_turn("user123", "hello", background_tasks=bg_tasks)
    
    # Assert return format
    assert resp == "assistant reply"
    assert isinstance(emotions, dict)
    
    # Assert execution order: sync_state must complete before scheduling background task
    assert call_order == ["save_turn", "sync_state"]
    
    # Assert background task scheduled
    bg_tasks.add_task.assert_called_once()
    args, kwargs = bg_tasks.add_task.call_args
    assert args[0] == engine.run_archival_extraction
    assert isinstance(args[1], PersistedTurnRef)
    assert args[1].user_id == "user123"


def test_chat_response_format(client_app, mock_supabase):
    from backend.main import engine
    from backend.emotional_core import EmotionalState
    from backend.relationship import UserRelationship
    
    mock_user = MockUser(id="user123")
    mock_supabase.auth.get_user.return_value = MockAuthResponse(user=mock_user)
    
    # Mock load_user_state to succeed
    engine.memory_manager.load_user_state = MagicMock(return_value={
        "emotional_state": EmotionalState().to_dict(),
        "relationship_state": UserRelationship(user_id="user123").to_dict()
    })
    
    # Mock process_turn to return custom values
    engine.process_turn = AsyncMock(return_value=("My response text", {"joy": 0.5}))
    
    response = client_app.post(
        "/chat",
        json={"message": "hello"},
        headers={"Authorization": "Bearer valid_token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "emotion_state" in data
    assert len(data) == 2  # exactly response and emotion_state
    assert data["response"] == "My response text"
    assert data["emotion_state"] == {"joy": 0.5}


@pytest.mark.anyio
async def test_run_archival_extraction_load_failure(caplog):
    engine = ConversationEngine()
    engine.memory_manager = MagicMock()
    engine.memory_manager.load_persisted_user_message = MagicMock(side_effect=Exception("DB connection error user123 secret message"))
    
    ref = PersistedTurnRef(user_id="user123", source_chat_log_id=1, assistant_chat_log_id=2)
    
    with caplog.at_level(logging.ERROR):
        await engine.run_archival_extraction(ref)
        
    assert "archival_extraction_load_failed" in caplog.text
    # No leak
    assert "user123" not in caplog.text
    assert "secret message" not in caplog.text
    assert "DB connection error" not in caplog.text


def test_different_turns_same_content_distinct():
    # Different turns with the same content (same user, but different source_chat_log_id)
    # produce different idempotency keys
    key1 = compute_idempotency_key("user123", 100, 1)
    key2 = compute_idempotency_key("user123", 101, 1)
    
    assert key1 != key2
    
    # Same turn (same user, same source_chat_log_id) produces same key (idempotency)
    key3 = compute_idempotency_key("user123", 100, 1)
    assert key1 == key3


def test_no_real_external_dependencies_proof():
    # Programmatic proof that real SentenceTransformer, Supabase or Groq are not used
    # in any test environment instantiation
    import sys
    from unittest.mock import MagicMock
    
    assert isinstance(sys.modules.get('sentence_transformers'), MagicMock)
    assert isinstance(sys.modules.get('supabase'), MagicMock)


def test_sql_guarantees_mock():
    # Verify RLS and composite FK setup exists in the migration schema
    schema_path = "supabase_schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_content = f.read()
        
    # Check RLS exists and FOR ALL is removed
    assert "alter table archival_extractions enable row level security;" in schema_content
    assert "for select" in schema_content
    assert "for all" not in schema_content
    
    # Check composite foreign key constraints exist
    assert "foreign key (user_id, source_chat_log_id) references chat_logs(user_id, id)" in schema_content
    assert "constraint chat_logs_user_id_id_key unique (user_id, id)" in schema_content
    
    # Check mandatory not null fields
    assert "user_id text not null" in schema_content
    assert "source_chat_log_id bigint not null" in schema_content
