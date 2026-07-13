import sys
from unittest.mock import MagicMock

# Mock external dependencies before importing any backend modules
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['supabase'] = MagicMock()

import pytest
from unittest.mock import patch
from backend.memory import MemoryManager, TurnPersistenceError
from backend.archival_memory import (
    PersistedTurnRef,
    ArchivalFact,
    ArchivalExtractionEnvelope,
    ArchivalValidationError,
    ArchivalDuplicateError
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
    # 23505 raises ArchivalDuplicateError
    with pytest.raises(ArchivalDuplicateError):
        mm.store_archival_extraction("u1", 100, "key_abc", env)

def test_load_persisted_user_message_db_uninitialized():
    mm = MemoryManager()
    mm.supabase = None
    with pytest.raises(RuntimeError) as exc_info:
        mm.load_persisted_user_message("u1", 100)
    assert "Serviço de persistência indisponível." in str(exc_info.value)

def test_load_persisted_user_message_db_failure():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.side_effect = Exception("DB Connection Error")
    
    with pytest.raises(RuntimeError) as exc_info:
        mm.load_persisted_user_message("u1", 100)
    assert "Serviço de persistência indisponível." in str(exc_info.value)


# save_turn validation tests
def test_save_turn_invalid_records_count():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[{"id": 100}])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_invalid_record_type():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[{"id": 100}, "invalid_type"])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_missing_keys():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[
        {"id": 100, "role": "user"},
        {"id": 101, "role": "assistant"}  # missing user_id
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_invalid_ids():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    # Negative ID
    mock_resp_neg = MagicMock(data=[
        {"id": -1, "role": "user", "user_id": "u1", "content": "user msg"},
        {"id": 101, "role": "assistant", "user_id": "u1", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp_neg
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")
        
    # Non-integer ID
    mock_resp_float = MagicMock(data=[
        {"id": 100.5, "role": "user", "user_id": "u1", "content": "user msg"},
        {"id": 101, "role": "assistant", "user_id": "u1", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp_float
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")
        
    # Equal IDs
    mock_resp_equal = MagicMock(data=[
        {"id": 100, "role": "user", "user_id": "u1", "content": "user msg"},
        {"id": 100, "role": "assistant", "user_id": "u1", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp_equal
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_wrong_user_id():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[
        {"id": 100, "role": "user", "user_id": "u1", "content": "user msg"},
        {"id": 101, "role": "assistant", "user_id": "another_user", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_wrong_roles():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[
        {"id": 100, "role": "user", "user_id": "u1", "content": "user msg"},
        {"id": 101, "role": "user", "user_id": "u1", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")

def test_save_turn_mismatched_content():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[
        {"id": 100, "role": "user", "user_id": "u1", "content": "divergent user msg"},
        {"id": 101, "role": "assistant", "user_id": "u1", "content": "bot msg"}
    ])
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError):
        mm.save_turn("u1", "user msg", "bot msg")


# load_persisted_user_message validation tests
def test_load_persisted_user_message_multiple_rows():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[
        {"id": 100, "role": "user", "user_id": "u1", "content": "hi"},
        {"id": 100, "role": "user", "user_id": "u1", "content": "double"}
    ])
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    with pytest.raises(KeyError):
        mm.load_persisted_user_message("u1", 100)

def test_load_persisted_user_message_wrong_id():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[{"id": 999, "role": "user", "user_id": "u1", "content": "hi"}])
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    with pytest.raises(KeyError):
        mm.load_persisted_user_message("u1", 100)

def test_load_persisted_user_message_wrong_user():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[{"id": 100, "role": "user", "user_id": "another_user", "content": "hi"}])
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    with pytest.raises(KeyError):
        mm.load_persisted_user_message("u1", 100)

def test_load_persisted_user_message_non_str_content():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(data=[{"id": 100, "role": "user", "user_id": "u1", "content": 12345}])
    mm.supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = mock_resp
    with pytest.raises(KeyError):
        mm.load_persisted_user_message("u1", 100)


# store_archival_extraction validation tests
def test_store_archival_extraction_none_response():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mm.supabase.table.return_value.insert.return_value.execute.return_value = None
    env = ArchivalExtractionEnvelope(facts=[])
    with pytest.raises(RuntimeError) as exc_info:
        mm.store_archival_extraction("u1", 100, "key_abc", env)
    assert "Sem resposta do banco" in str(exc_info.value)

def test_store_archival_extraction_error_in_response():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(error="Database error message")
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    env = ArchivalExtractionEnvelope(facts=[])
    with pytest.raises(RuntimeError) as exc_info:
        mm.store_archival_extraction("u1", 100, "key_abc", env)
    assert "Erro retornado pelo banco" in str(exc_info.value)

def test_store_archival_extraction_invalid_data():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock(error=None)
    mock_resp.data = None
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    env = ArchivalExtractionEnvelope(facts=[])
    with pytest.raises(RuntimeError) as exc_info:
        mm.store_archival_extraction("u1", 100, "key_abc", env)
    assert "Resposta estruturalmente inválida" in str(exc_info.value)
