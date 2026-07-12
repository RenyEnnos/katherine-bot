import asyncio
import pytest
from unittest.mock import MagicMock
from backend.engine import ConversationEngine
from backend.emotional_core import EmotionalState
from backend.relationship import UserRelationship
from backend.memory import StateLoadError, StatePersistenceError

def test_relational_identity_adulterated_integration():
    async def run_test():
        engine = ConversationEngine()
        user_id = "user-A"

        # Load user state returns relationship state belonging to user-B
        engine.memory_manager.load_user_state = MagicMock(return_value={
            "emotional_state": EmotionalState().to_dict(),
            "relationship_state": {"user_id": "user-B", "trust": 0.8}
        })

        # Mock other external calls
        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()

        # Mock sync_state to assert that relationship.user_id is user-A
        def mock_sync(uid, state, rel):
            assert uid == "user-A"
            assert rel.user_id == "user-A"

        engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)

        await engine.process_turn(user_id, "hello")
        assert engine.memory_manager.sync_state.called

    asyncio.run(run_test())

def test_read_failure_integration():
    async def run_test():
        engine = ConversationEngine()
        user_id = "read_error_user"

        engine.memory_manager.supabase = MagicMock()
        # Mock select to throw exception containing sensitive info
        engine.memory_manager.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("SECRET_API_KEY_999")

        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        engine.memory_manager.sync_state = MagicMock()
        engine.groq_manager.chat_completion = MagicMock()

        with pytest.raises(StateLoadError) as excinfo:
            await engine.process_turn(user_id, "Hello")

        assert "SECRET_API_KEY_999" not in str(excinfo.value)
        assert user_id not in str(excinfo.value)
        assert not engine.memory_manager.sync_state.called
        assert not engine.groq_manager.chat_completion.called

        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_failed_default_profile_insert_raises_error():
    async def run_test():
        engine = ConversationEngine()
        user_id = "new_user"

        engine.memory_manager.supabase = MagicMock()

        # Mock select to return empty list (non-existent profile)
        mock_select = MagicMock()
        mock_select.data = []
        engine.memory_manager.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select

        # Mock insert to raise error
        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        engine.groq_manager.chat_completion = MagicMock()
        engine.memory_manager.supabase.table.return_value.insert.return_value.execute.side_effect = Exception("INSERT_FAILED_DB_ERROR")

        with pytest.raises(StateLoadError) as excinfo:
            await engine.process_turn(user_id, "Hello")

        assert "INSERT_FAILED_DB_ERROR" not in str(excinfo.value)

        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_zero_rows_updated_integration():
    async def run_test():
        engine = ConversationEngine()
        user_id = "update_error_user"

        engine.memory_manager.load_user_state = MagicMock(return_value={
            "emotional_state": EmotionalState().to_dict(),
            "relationship_state": UserRelationship(user_id=user_id).to_dict()
        })

        # Mock supabase client update returning data=[]
        engine.memory_manager.supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = []
        mock_response.error = None
        engine.memory_manager.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_response

        # Mock generate
        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()

        with pytest.raises(StatePersistenceError) as excinfo:
            await engine.process_turn(user_id, "Hello")

        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_lock_cleanup_after_success():
    async def run_test():
        engine = ConversationEngine()
        user_id = "success_user"

        engine.memory_manager.load_user_state = MagicMock(return_value={
            "emotional_state": EmotionalState().to_dict(),
            "relationship_state": UserRelationship(user_id=user_id).to_dict()
        })

        engine.memory_manager.supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [{"user_id": user_id}]
        mock_response.error = None
        engine.memory_manager.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_response

        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()

        await engine.process_turn(user_id, "Hello")

        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_lock_cleanup_on_cancellation_during_registration():
    async def run_test():
        from backend.lock_manager import UserLockManager
        import asyncio
        mgr = UserLockManager()
        user_id = "test_cancel_reg_user"

        # We hold dict_lock to block registration
        async with mgr._dict_lock:
            task = asyncio.create_task(mgr.lock(user_id).__aenter__())
            await asyncio.sleep(0.1) # Let task try to enter dict_lock
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Dict lock released, check that user_id is NOT in locks registry
        async with mgr._dict_lock:
            assert user_id not in mgr._locks

    asyncio.run(run_test())

def test_persistence_before_return():
    async def run_test():
        engine = ConversationEngine()
        user_id = "sync_check_user"

        engine.memory_manager.load_user_state = MagicMock(return_value={
            "emotional_state": EmotionalState().to_dict(),
            "relationship_state": UserRelationship(user_id=user_id).to_dict()
        })

        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()

        sync_called = asyncio.Event()
        lock_held_during_sync = False

        def slow_sync(uid, state, rel):
            # Check that the lock is held during sync
            nonlocal lock_held_during_sync
            if user_id in engine.lock_manager._locks:
                lock_held_during_sync = engine.lock_manager._locks[user_id][0].locked()
            sync_called.set()

        engine.memory_manager.sync_state = MagicMock(side_effect=slow_sync)

        await engine.process_turn(user_id, "Hello")

        assert sync_called.is_set()
        assert lock_held_during_sync

    asyncio.run(run_test())
