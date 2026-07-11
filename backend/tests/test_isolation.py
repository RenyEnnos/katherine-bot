import asyncio
import pytest
import time
from unittest.mock import MagicMock, patch
from backend.emotional_core import EmotionalState, AffectiveEngine
from backend.engine import ConversationEngine
from backend.memory import MemoryManager
from backend.relationship import UserRelationship

@pytest.mark.asyncio
async def test_affective_engine_statelessness():
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1)
    original_dict = state.to_dict().copy()

    new_state, _ = engine.update_state(state, "test", time.time())

    assert new_state is not state
    assert state.to_dict() == original_dict
    assert new_state.pleasure != state.pleasure

@pytest.mark.asyncio
async def test_deterministic_transition():
    engine = AffectiveEngine()
    state1 = EmotionalState(pleasure=0.1, last_update=1000)
    state2 = EmotionalState(pleasure=0.1, last_update=1000)

    current_time = 2000
    res1, _ = engine.update_state(state1, "linda", current_time)
    res2, _ = engine.update_state(state2, "linda", current_time)

    assert res1.to_dict() == res2.to_dict()

@pytest.mark.asyncio
async def test_user_isolation():
    # We want to ensure that processing for user A doesn't affect user B's state in the engine
    # Since we removed self.state from AffectiveEngine and engine.turn_count, this should be true.
    with patch("backend.engine.GroqClientManager") as MockGroq:

        engine = ConversationEngine()

        # Mock responses for User A and User B
        engine.memory_manager = MagicMock()
        mock_mem = engine.memory_manager

        def load_user_state(user_id):
            if user_id == "A":
                return {"emotional_state": EmotionalState(pleasure=0.5).to_dict(), "relationship_state": {}}
            else:
                return {"emotional_state": EmotionalState(pleasure=-0.5).to_dict(), "relationship_state": {}}

        mock_mem.load_user_state.side_effect = load_user_state

        # Mock _perceive to be neutral
        engine._perceive = MagicMock(return_value={"valence": 0})

        # Mock Groq response
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Response"
        engine.groq_manager.chat_completion.return_value = mock_completion

        # Process User A then User B
        _, state_a = await engine.process_turn("A", "hello")
        _, state_b = await engine.process_turn("B", "hello")

        # Check that state_a was derived from User A's initial state (pleasure=0.5)
        # and state_b from User B's (pleasure=-0.5)
        assert state_a["pleasure"] > 0
        assert state_b["pleasure"] < 0

@pytest.mark.asyncio
async def test_concurrent_requests_serialization():
    # Two simultaneous requests for the same user should be serialized.
    # We can verify this by checking if the second request's load_user_state
    # happens after the first request's sync_state.

    with patch("backend.engine.GroqClientManager") as MockGroq:

        engine = ConversationEngine()
        engine.memory_manager = MagicMock()
        mock_mem = engine.memory_manager

        call_order = []

        def mock_load(user_id):
            call_order.append(f"load_{user_id}")
            return {"emotional_state": EmotionalState().to_dict(), "relationship_state": {}}

        def mock_sync(user_id, emotion, rel):
            call_order.append(f"sync_{user_id}")

        mock_mem.load_user_state.side_effect = mock_load
        mock_mem.sync_state.side_effect = mock_sync

        engine._perceive = MagicMock(return_value={"valence": 0})
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Response"

        # Mock chat_completion to be slow
        def slow_chat(*args, **kwargs):
            time.sleep(0.1) # Blocks current task, but since we are using asyncio,
                           # we should use something that allows switching if we want to test concurrency properly.
                           # However, process_turn calls it and it's NOT async in engine.py!
                           # Wait, I just realized engine.py calls:
                           # chat_completion = self.groq_manager.chat_completion(...)
                           # it is NOT awaited. It is a synchronous call.
            return mock_completion

        engine.groq_manager.chat_completion.side_effect = slow_chat

        # Run two tasks for the same user concurrently
        # Because we have an async lock in engine.py, even if chat_completion is sync,
        # the lock is awaited.

        await asyncio.gather(
            engine.process_turn("user1", "msg1"),
            engine.process_turn("user1", "msg2")
        )

        # Expected order: load, sync, load, sync (because of lock)
        assert call_order == ["load_user1", "sync_user1", "load_user1", "sync_user1"]

@pytest.mark.asyncio
async def test_different_users_not_locked():
    with patch("backend.engine.GroqClientManager") as MockGroq:

        engine = ConversationEngine()
        engine.memory_manager = MagicMock()
        mock_mem = engine.memory_manager

        call_order = []

        def mock_load(user_id):
            call_order.append(f"load_{user_id}")
            return {"emotional_state": EmotionalState().to_dict(), "relationship_state": {}}

        def mock_sync(user_id, emotion, rel):
            call_order.append(f"sync_{user_id}")

        mock_mem.load_user_state.side_effect = mock_load
        mock_mem.sync_state.side_effect = mock_sync

        engine._perceive = MagicMock(return_value={"valence": 0})
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Response"

        # To test that they are NOT locked, we need one to be able to start while another is running.
        # We need a point of suspension. process_turn has `async with await self.lock_manager.get_lock(user_id)`
        # and other awaits?
        # Actually, in ConversationEngine.process_turn:
        # async with await self.lock_manager.get_lock(user_id):
        #    ...
        #    chat_completion = self.groq_manager.chat_completion(...) # SYNC
        #    ...

        # If chat_completion is sync, it will block the event loop.
        # So even different users will be serialized if chat_completion is sync and doesn't yield.

        # Let's check if there are other awaits.
        # `await self.lock_manager.get_lock(user_id)` yields.

        # If I want to test that they are not locked by the SAME lock, I can use a mock for chat_completion that yields.
        # But wait, chat_completion in engine.py is NOT awaited.
        # If I make it a mock that returns a coroutine, engine.py will fail (as it did before).

        # If the real chat_completion is sync, then the whole engine is somewhat serialized per worker.
        # But the task is to ensure we don't have a GLOBAL lock.

        # If I use a side_effect that is a normal function but does something that allows other tasks to run?
        # No, a normal function blocks in the same thread.

        # Let's just verify that they use different lock objects.
        lock1 = await engine.lock_manager.get_lock("userA")
        lock2 = await engine.lock_manager.get_lock("userB")
        assert lock1 is not lock2

        lock3 = await engine.lock_manager.get_lock("userA")
        assert lock1 is lock3

@pytest.mark.asyncio
async def test_persistence_failure_raises():
    with patch("backend.engine.GroqClientManager") as MockGroq:

        engine = ConversationEngine()
        engine.memory_manager = MagicMock()
        mock_mem = engine.memory_manager

        mock_mem.load_user_state.return_value = {"emotional_state": {}, "relationship_state": {}}
        mock_mem.sync_state.side_effect = RuntimeError("Sync Failed")

        engine._perceive = MagicMock(return_value={"valence": 0})

        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Response"
        engine.groq_manager.chat_completion.return_value = mock_completion

        with pytest.raises(RuntimeError, match="Sync Failed"):
            await engine.process_turn("user1", "msg")

@pytest.mark.asyncio
async def test_engine_statelessness():
    engine = ConversationEngine()
    assert not hasattr(engine, "turn_count")
    assert not hasattr(engine, "current_adaptation_strategy")

    affective = AffectiveEngine()
    assert not hasattr(affective, "state")
