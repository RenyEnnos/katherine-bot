import pytest
from unittest.mock import MagicMock, patch
from backend.memory import MemoryManager, TurnPersistenceError
from backend.archival_memory import (
    PersistedTurnRef,
    ArchivalFact,
    ArchivalExtractionEnvelope,
    ArchivalValidationError
)

def test_save_turn_success():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_resp = MagicMock()
    mock_resp.data = [
        {"id": 100, "user_id": "u1", "role": "user", "content": "hi"},
        {"id": 101, "user_id": "u1", "role": "assistant", "content": "hello"}
    ]
    mock_resp.error = None
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    
    ref = mm.save_turn("u1", "hi", "hello")
    assert isinstance(ref, PersistedTurnRef)
    assert ref.user_id == "u1"
    assert ref.source_chat_log_id == 100
    assert ref.assistant_chat_log_id == 101

def test_save_turn_invalid_roles():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_resp = MagicMock()
    mock_resp.data = [
        {"id": 100, "user_id": "u1", "role": "user", "content": "hi"},
        {"id": 101, "user_id": "u1", "role": "user", "content": "hello"}  # two users
    ]
    mock_resp.error = None
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "hi", "hello")

def test_load_persisted_user_message_success():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_resp = MagicMock()
    mock_resp.data = [{"id": 100, "user_id": "u1", "role": "user", "content": "hi"}]
    mock_resp.error = None
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    
    msg = mm.load_persisted_user_message("u1", 100)
    assert msg == "hi"

def test_load_persisted_user_message_failure():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    # Mismatch user role (e.g. role is assistant instead of user)
    mock_resp = MagicMock()
    mock_resp.data = [{"id": 100, "user_id": "u1", "role": "assistant", "content": "hello"}]
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    with pytest.raises(KeyError):
        mm.load_persisted_user_message("u1", 100)

def test_store_archival_extraction_success():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_resp = MagicMock()
    mock_resp.data = [{"source_chat_log_id": 100}]
    mock_resp.error = None
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    
    env = ArchivalExtractionEnvelope(facts=[ArchivalFact(content="F1", importance=0.9, tags=["t1"])])
    # Should run without exception
    mm.store_archival_extraction("u1", 100, "key_abc", env)
    
    mm.supabase.table.assert_called_with("archival_extractions")

def test_store_archival_extraction_conflict():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    class PostgrestAPIError(Exception):
        def __init__(self):
            self.code = "23505"
            self.message = "Unique violation"

    mm.supabase.table.return_value.insert.return_value.execute.side_effect = PostgrestAPIError()
    
    env = ArchivalExtractionEnvelope(facts=[])
    # 23505 handled as success
    mm.store_archival_extraction("u1", 100, "key_abc", env)
