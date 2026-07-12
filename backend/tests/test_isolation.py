import asyncio
import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from backend.engine import ConversationEngine
from backend.emotional_core import EmotionalState, AffectiveEngine
from backend.relationship import UserRelationship
from backend.memory import StatePersistenceError

def test_deterministic_transition():
    """
    The transition with same inputs and same time produces the same result.
    """
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1, arousal=0.2, dominance=0.3)
    current_time = 1000.0
    user_input = "Hello"

    res1, inst1 = engine.update_state(state, user_input, current_time)
    res2, inst2 = engine.update_state(state, user_input, current_time)

    assert res1 == res2
    assert inst1 == inst2

def test_no_mutation():
    """
    The previous state is not mutated.
    """
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1, arousal=0.2, dominance=0.3)
    initial_dict = state.to_dict()
    current_time = 1000.0

    new_state, _ = engine.update_state(state, "Hello", current_time)

    assert state.to_dict() == initial_dict
    assert new_state != state

def test_user_isolation():
    """
    Interleaved messages from A and B don't contaminate each other.
    """
    async def run_test():
        engine = ConversationEngine()

        # Mock everything external
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()

        # Custom load_user_state to return different states for A and B
        states = {
            "A": {"emotional_state": EmotionalState(pleasure=0.5).to_dict(), "relationship_state": {}},
            "B": {"emotional_state": EmotionalState(pleasure=-0.5).to_dict(), "relationship_state": {}}
        }
        engine.memory_manager.load_user_state = MagicMock(side_effect=lambda uid: states.get(uid, {}))

        # Mock perceive to be neutral
        engine._perceive = MagicMock(return_value={"valence": 0, "arousal_shift": 0, "dominance_shift": 0})

        # Process A
        _, state_a_dict = await engine.process_turn("A", "Hello A")
        # Process B
        _, state_b_dict = await engine.process_turn("B", "Hello B")

        assert state_a_dict["pleasure"] > 0
        assert state_b_dict["pleasure"] < 0
        assert not hasattr(engine.affective_engine, 'state')

    asyncio.run(run_test())

def test_concurrent_requests_serialization():
    """
    Two simultaneous calls from the same user serialize load -> transition -> persist and preserve both updates.
    """
    async def run_test():
        engine = ConversationEngine()
        user_id = "test_user"

        db = {
            user_id: {
                "emotional_state": EmotionalState(pleasure=0.0).to_dict(),
                "relationship_state": UserRelationship(user_id=user_id).to_dict()
            }
        }

        def mock_load(uid):
            return db[uid].copy()

        def mock_sync(uid, state, rel, profile=None):
            db[uid]["emotional_state"] = state.to_dict()
            db[uid]["relationship_state"] = rel.to_dict()

        engine.memory_manager.load_user_state = MagicMock(side_effect=mock_load)
        engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
        engine.memory_manager.save_turn = MagicMock()

        # For the SAME user, requests are serialized by the lock.
        # Request 1 enters lock, Request 2 blocks.
        # We'll use an event to coordinate.
        req1_in_critical = threading.Event()
        req2_waiting = threading.Event()

        def sync_chat_mock(*args, **kwargs):
            req1_in_critical.set()
            # Wait for Request 2 to at least have started and be waiting for the lock
            # We can't easily detect Request 2 waiting, but we can give it time.
            time.sleep(0.5)
            m = MagicMock()
            m.choices = [MagicMock()]
            m.choices[0].message.content = "Response"
            return m

        engine.groq_manager.chat_completion = MagicMock(side_effect=sync_chat_mock)
        engine._perceive = MagicMock(return_value={"valence": 0.1, "arousal_shift": 0, "dominance_shift": 0})

        # Trigger two concurrent turns
        t1 = asyncio.create_task(engine.process_turn(user_id, "Turn 1"))
        # Ensure T1 starts first
        await asyncio.sleep(0.1)
        t2 = asyncio.create_task(engine.process_turn(user_id, "Turn 2"))

        await asyncio.gather(t1, t2)

        # If serialized, it should be > 0.15 (0.0 -> 0.1 -> 0.2 approx)
        final_pleasure = db[user_id]["emotional_state"]["pleasure"]
        assert final_pleasure > 0.15

    asyncio.run(run_test())

def test_no_global_lock():
    """
    Different users can perform blocking work concurrently.
    """
    async def run_test():
        engine = ConversationEngine()

        # Barrier to ensure both threads reach the blocking work concurrently
        barrier = threading.Barrier(2)

        def slow_chat(*args, **kwargs):
            barrier.wait(timeout=2) # Will fail if they don't reach here concurrently
            return MagicMock(choices=[MagicMock(message=MagicMock(content="Done"))])

        engine.groq_manager.chat_completion = MagicMock(side_effect=slow_chat)
        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={})

        # Run two different users concurrently
        t1 = asyncio.create_task(engine.process_turn("User_A", "Msg A"))
        t2 = asyncio.create_task(engine.process_turn("User_B", "Msg B"))

        await asyncio.gather(t1, t2)

    asyncio.run(run_test())

def test_persistence_failure_sanitization():
    """
    Persistence failure propagates as sanitized exception and cleans up.
    """
    async def run_test():
        engine = ConversationEngine()
        user_id = "error_user"

        # Mock load_user_state to avoid falling back to default and calling execute
        engine.memory_manager.load_user_state = MagicMock(return_value={
            "emotional_state": EmotionalState().to_dict(),
            "relationship_state": UserRelationship(user_id=user_id).to_dict()
        })

        # Mock internal supabase client behavior
        engine.memory_manager.supabase = MagicMock()
        # Mock table().update().eq().execute()
        engine.memory_manager.supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception("SECRET_TOKEN_123")

        with pytest.raises(StatePersistenceError) as excinfo:
            await engine.process_turn(user_id, "Msg")

        # Verify sanitization
        assert "SECRET_TOKEN_123" not in str(excinfo.value)
        assert "error_user" not in str(excinfo.value)

        # Verify cleanup: entry should be removed from lock manager
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_lock_cleanup_on_cancellation():
    """
    Lock entries are cleaned after cancellation.
    """
    async def run_test():
        engine = ConversationEngine()
        user_id = "cancel_user"

        reached_point = asyncio.Event()

        def blocking_load(uid):
            reached_point.set()
            time.sleep(10)
            return {}

        engine.memory_manager.load_user_state = MagicMock(side_effect=blocking_load)

        task = asyncio.create_task(engine.process_turn(user_id, "Msg"))
        # wait_for to avoid hanging forever if it fails
        await asyncio.wait_for(reached_point.wait(), timeout=2)

        # Check that it exists in registry
        async with engine.lock_manager._dict_lock:
            assert user_id in engine.lock_manager._locks

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Check that it is removed
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_engine_structure():
    """
    Final checks on engine/affective state.
    """
    engine = ConversationEngine()
    assert not hasattr(engine, "turn_count")
    assert not hasattr(engine, "current_adaptation_strategy")
    assert not hasattr(engine.affective_engine, "state")

def test_relational_identity_adulterated():
    from backend.relationship import UserRelationship
    # Simulated state has B, but authenticated user is A
    raw_data = {"user_id": "user-B", "trust": 0.8, "affection": 0.9}
    rel = UserRelationship.from_dict(raw_data, user_id="user-A")
    assert rel.user_id == "user-A"
    assert rel.trust == 0.8

def test_read_failure_raises_stateloaderror():
    from backend.memory import MemoryManager, StateLoadError
    from unittest.mock import MagicMock
    import pytest
    
    mgr = MemoryManager()
    mgr.supabase = MagicMock()
    # Mock execute() to raise an exception with sensitive info
    mgr.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("SECRET_API_KEY_123_sensitive_data")
    
    with pytest.raises(StateLoadError) as excinfo:
        mgr.load_user_state("user-A")
        
    assert "SECRET_API_KEY_123_sensitive_data" not in str(excinfo.value)
    assert "user-A" not in str(excinfo.value)

def test_read_non_existent_profile_creates_default():
    from backend.memory import MemoryManager
    from unittest.mock import MagicMock
    
    mgr = MemoryManager()
    mgr.supabase = MagicMock()
    
    # Mock select response with data=[]
    mock_select = MagicMock()
    mock_select.data = []
    mgr.supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_select
    
    # Mock insert response
    mock_insert = MagicMock()
    mock_insert.data = [{"user_id": "user-A"}]
    mgr.supabase.table.return_value.insert.return_value.execute.return_value = mock_insert
    
    state = mgr.load_user_state("user-A")
    assert state["emotional_state"]["pleasure"] == 0.0
    assert state["relationship_state"]["user_id"] == "user-A"

def test_zero_rows_updated_raises_statepersistenceerror():
    from backend.memory import MemoryManager, StatePersistenceError
    from unittest.mock import MagicMock
    import pytest
    mgr = MemoryManager()
    mgr.supabase = MagicMock()
    
    # Mock update return with empty data list (data=[])
    mock_response = MagicMock()
    mock_response.data = []
    mock_response.error = None
    mgr.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_response
    
    from backend.emotional_core import EmotionalState
    from backend.relationship import UserRelationship
    with pytest.raises(StatePersistenceError):
        mgr.sync_state("user-123", EmotionalState(), UserRelationship(user_id="user-123"))

def test_normalize_perception():
    from backend.engine import _normalize_perception
    
    # None payload
    res = _normalize_perception(None)
    assert res["valence"] == 0.0
    assert res["triggered_emotions"]["joy"] == 0.0
    
    # Malformed valence types (bool, string, nan, inf)
    res = _normalize_perception({"valence": True, "arousal_shift": "invalid", "dominance_shift": float('nan')})
    assert res["valence"] == 0.0
    assert res["arousal_shift"] == 0.0
    assert res["dominance_shift"] == 0.0
    
    # Out of bounds
    res = _normalize_perception({"valence": 2.5, "triggered_emotions": {"joy": -0.5, "sadness": 1.5, "invalid_emotion": 0.5}})
    assert res["valence"] == 1.0
    assert res["triggered_emotions"]["joy"] == 0.0
    assert res["triggered_emotions"]["sadness"] == 1.0
    assert "invalid_emotion" not in res["triggered_emotions"]

def test_affective_engine_defensiveness():
    from backend.emotional_core import AffectiveEngine, EmotionalState
    engine = AffectiveEngine()
    state = EmotionalState()
    
    # Call update_state with unsafe override shifts (None, bool, NaN)
    override = {"valence": None, "arousal_shift": True, "dominance_shift": float('inf')}
    new_state, _ = engine.update_state(state, "Hello", 1000.0, perception_override=override)
    
    assert isinstance(new_state.pleasure, float)
    assert new_state.pleasure == 0.0
    assert new_state.arousal == 0.0
    assert new_state.dominance == 0.0






