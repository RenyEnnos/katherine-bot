import pytest
import asyncio
from unittest.mock import MagicMock, patch
from backend.memory import MemoryManager, ContextLoadError, TurnPersistenceError
from backend.engine import ConversationEngine

def test_memory_manager_has_no_short_term_memory():
    mm = MemoryManager()
    assert not hasattr(mm, 'short_term_memory')

def test_load_recent_history_validation_failures():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    # Mock None response
    mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = None
    with pytest.raises(ContextLoadError) as exc:
        mm.load_recent_history("user123")
    assert "user123" not in str(exc.value)

    # Mock error attribute
    mock_resp = MagicMock()
    mock_resp.error = "database error"
    mm.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value = mock_resp
    with pytest.raises(ContextLoadError) as exc:
        mm.load_recent_history("user123")
    assert "user123" not in str(exc.value)
    assert "database error" not in str(exc.value)

def test_save_turn_zero_inserted_rows():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    mock_resp = MagicMock()
    mock_resp.data = [] # zero inserted rows
    mock_resp.error = None
    mm.supabase.table.return_value.insert.return_value.execute.return_value = mock_resp
    with pytest.raises(TurnPersistenceError) as exc:
        mm.save_turn("user123", "hi", "hello")
    assert "user123" not in str(exc.value)
    assert "hi" not in str(exc.value)
    assert "hello" not in str(exc.value)

def test_user_history_isolation():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_select = mm.supabase.table.return_value.select
    mock_eq = mock_select.return_value.eq
    mock_order1 = mock_eq.return_value.order
    mock_order2 = mock_order1.return_value.order
    mock_limit = mock_order2.return_value.limit
    
    mock_resp = MagicMock()
    mock_resp.data = [{"role": "user", "content": "hello"}]
    mock_resp.error = None
    mock_limit.return_value.execute.return_value = mock_resp
    
    history = mm.load_recent_history("userA")
    
    # Assert query filters strictly by userA
    mock_select.assert_called_with("role, content")
    mock_eq.assert_called_with("user_id", "userA")
    assert len(history) == 1

def test_deterministic_ordering_calls():
    mm = MemoryManager()
    mm.supabase = MagicMock()
    
    mock_select = mm.supabase.table.return_value.select
    mock_eq = mock_select.return_value.eq
    mock_order1 = mock_eq.return_value.order
    mock_order2 = mock_order1.return_value.order
    mock_limit = mock_order2.return_value.limit
    
    mock_resp = MagicMock()
    mock_resp.data = [
        {"role": "assistant", "content": "reply2"},
        {"role": "user", "content": "msg2"},
        {"role": "assistant", "content": "reply1"},
        {"role": "user", "content": "msg1"}
    ]
    mock_resp.error = None
    mock_limit.return_value.execute.return_value = mock_resp
    
    history = mm.load_recent_history("userA", limit=4)
    
    # Assert query uses created_at and id as sorting tie-breakers in descending order
    mock_order1.assert_called_with("created_at", desc=True)
    mock_order2.assert_called_with("id", desc=True)
    
    # Assert returned history is reversed to chronological ascending order
    assert history == [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "reply1"},
        {"role": "user", "content": "msg2"},
        {"role": "assistant", "content": "reply2"}
    ]

def test_process_turn_awaits_save_turn_inside_lock():
    async def run_test():
        engine = ConversationEngine()
        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.sync_state = MagicMock()
        engine._perceive = MagicMock(return_value={})
        
        mock_chat = MagicMock()
        mock_chat.choices = [MagicMock()]
        mock_chat.choices[0].message.content = "Bot reply"
        engine.groq_manager.chat_completion = MagicMock(return_value=mock_chat)

        save_turn_called = False
        async def slow_save_turn(*args, **kwargs):
            nonlocal save_turn_called
            await asyncio.sleep(0.2)
            save_turn_called = True

        # Mock load_recent_history to return empty list
        engine.memory_manager.load_recent_history = MagicMock(return_value=[])

        with patch.object(engine.memory_manager, 'save_turn', side_effect=lambda *a, **kw: asyncio.run(slow_save_turn(*a, **kw))):
            t = asyncio.create_task(engine.process_turn("user123", "Hello"))
            
            # Check lock is held and save_turn is not yet complete but started/awaited
            await asyncio.sleep(0.05)
            async with engine.lock_manager._dict_lock:
                assert "user123" in engine.lock_manager._locks
            
            await t
            assert save_turn_called
    asyncio.run(run_test())

def test_recreate_engine_preserves_context():
    async def run_test():
        engine1 = ConversationEngine()
        engine1._perceive = MagicMock(return_value={})
        engine1.memory_manager.load_user_state = MagicMock(return_value={})
        engine1.memory_manager.sync_state = MagicMock()
        
        mock_chat = MagicMock()
        mock_chat.choices = [MagicMock()]
        mock_chat.choices[0].message.content = "Response"
        engine1.groq_manager.chat_completion = MagicMock(return_value=mock_chat)
        
        # Mock history returned from DB
        history_data = [{"role": "user", "content": "hi"}]
        engine1.memory_manager.load_recent_history = MagicMock(return_value=history_data)
        engine1.memory_manager.save_turn = MagicMock()
        
        context1 = await asyncio.to_thread(engine1.memory_manager.get_context, "user123", "new msg", {})
        
        # Recreate engine
        engine2 = ConversationEngine()
        engine2.memory_manager.load_recent_history = MagicMock(return_value=history_data)
        
        context2 = await asyncio.to_thread(engine2.memory_manager.get_context, "user123", "new msg", {})
        
        assert context1 == context2
    asyncio.run(run_test())
