import asyncio
import pytest
import time
from unittest.mock import MagicMock, patch
from backend.engine import ConversationEngine
from backend.emotional_core import EmotionalState, AffectiveEngine
from backend.relationship import UserRelationship

@pytest.mark.asyncio
async def test_deterministic_transition():
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

@pytest.mark.asyncio
async def test_no_mutation():
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

@pytest.mark.asyncio
async def test_user_isolation():
    """
    Interleaved messages from A and B don't contaminate each other.
    """
    engine = ConversationEngine()

    # Mock everything external
    engine.groq_manager.chat_completion = MagicMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="Hi"))]))
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
    resp_a, state_a = await engine.process_turn("A", "Hello A")
    # Process B
    resp_b, state_b = await engine.process_turn("B", "Hello B")

    assert state_a["pleasure"] > 0
    assert state_b["pleasure"] < 0

    # Check that engine itself doesn't hold either state
    assert not hasattr(engine.affective_engine, 'state')

@pytest.mark.asyncio
async def test_concurrent_requests_serialization():
    """
    Two simultaneous calls from the same user accumulate both transitions without loss.
    """
    engine = ConversationEngine()
    user_id = "test_user"

    # We'll use a shared dictionary to simulate the DB
    db = {
        user_id: {
            "emotional_state": EmotionalState(pleasure=0.0).to_dict(),
            "relationship_state": UserRelationship(user_id=user_id).to_dict()
        }
    }

    def mock_load(uid):
        return db[uid].copy()

    def mock_sync(uid, state, rel, profile=None):
        # Simulate some delay to encourage race condition if no lock
        time.sleep(0.1)
        db[uid]["emotional_state"] = state.to_dict()
        db[uid]["relationship_state"] = rel.to_dict()

    engine.memory_manager.load_user_state = MagicMock(side_effect=mock_load)
    engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
    engine.memory_manager.save_turn = MagicMock()

    # Mock LLM to be slow and return positive valence
    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(0.2)
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Response"
        return m

    engine.groq_manager.chat_completion = MagicMock(side_effect=slow_chat)
    engine._perceive = MagicMock(return_value={"valence": 0.1, "arousal_shift": 0, "dominance_shift": 0})

    # Trigger two concurrent turns
    t1 = asyncio.create_task(engine.process_turn(user_id, "Turn 1"))
    t2 = asyncio.create_task(engine.process_turn(user_id, "Turn 2"))

    await asyncio.gather(t1, t2)

    # Each turn adds 0.1 valence. If serialized, total pleasure should be ~0.2
    # Note: there is some decay, so it might be slightly less than 0.2, but definitely > 0.1
    final_pleasure = db[user_id]["emotional_state"]["pleasure"]
    print(f"Final pleasure: {final_pleasure}")
    assert final_pleasure > 0.15

@pytest.mark.asyncio
async def test_no_global_lock():
    """
    Different users are NOT serialized by a global lock.
    """
    engine = ConversationEngine()

    # Mock LLM to be very slow
    async def slow_chat(*args, **kwargs):
        await asyncio.sleep(1.0)
        return MagicMock(choices=[MagicMock(message=MagicMock(content="Done"))])

    engine.groq_manager.chat_completion = MagicMock(side_effect=slow_chat)
    engine.memory_manager.load_user_state = MagicMock(return_value={})
    engine.memory_manager.sync_state = MagicMock()
    engine.memory_manager.save_turn = MagicMock()
    engine._perceive = MagicMock(return_value={})

    start_time = time.time()

    # Run two different users concurrently
    t1 = asyncio.create_task(engine.process_turn("User_A", "Msg A"))
    t2 = asyncio.create_task(engine.process_turn("User_B", "Msg B"))

    await asyncio.gather(t1, t2)

    duration = time.time() - start_time
    # If they were serialized, it would take > 2 seconds.
    # If concurrent, ~1 second.
    assert duration < 1.5

@pytest.mark.asyncio
async def test_persistence_before_return():
    """
    Persistence occurs before return.
    """
    engine = ConversationEngine()
    persistence_called = False

    def mock_sync(uid, state, rel, profile=None):
        nonlocal persistence_called
        persistence_called = True

    engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
    engine.memory_manager.load_user_state = MagicMock(return_value={})
    engine.memory_manager.save_turn = MagicMock()
    engine.groq_manager.chat_completion = MagicMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="Hi"))]))
    engine._perceive = MagicMock(return_value={})

    await engine.process_turn("User", "Msg")

    assert persistence_called is True

@pytest.mark.asyncio
async def test_persistence_failure():
    """
    Persistence failure raises explicit error.
    """
    engine = ConversationEngine()
    engine.memory_manager.sync_state = MagicMock(side_effect=Exception("DB DOWN"))
    engine.memory_manager.load_user_state = MagicMock(return_value={})
    engine.memory_manager.save_turn = MagicMock()
    engine.groq_manager.chat_completion = MagicMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="Hi"))]))
    engine._perceive = MagicMock(return_value={})

    with pytest.raises(Exception, match="DB DOWN"):
        await engine.process_turn("User", "Msg")

def test_engine_no_global_state():
    """
    ConversationEngine does not possess turn_count or current_adaptation_strategy.
    """
    engine = ConversationEngine()
    assert not hasattr(engine, "turn_count")
    assert not hasattr(engine, "current_adaptation_strategy")
    assert not hasattr(engine.affective_engine, "state")
