import asyncio
import pytest
import time
import threading
import math
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch
from backend.engine import ConversationEngine
from backend.emotional_core import EmotionalState, AffectiveEngine
from backend.relationship import UserRelationship
from backend.memory import StatePersistenceError, StateLoadError

def test_deterministic_transition():
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1, arousal=0.2, dominance=0.3)
    current_time = 1000.0
    user_input = "Hello"
    res1, inst1 = engine.update_state(state, user_input, current_time)
    res2, inst2 = engine.update_state(state, user_input, current_time)
    assert res1 == res2
    assert inst1 == inst2

def test_no_mutation():
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1, arousal=0.2, dominance=0.3)
    initial_dict = state.to_dict()
    current_time = 1000.0
    new_state, _ = engine.update_state(state, "Hello", current_time)
    assert state.to_dict() == initial_dict
    assert new_state != state

def test_user_isolation():
    async def run_test():
        engine = ConversationEngine()
        m = MagicMock()
        m.choices = [MagicMock()]
        m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        states = {
            "A": {"emotional_state": EmotionalState(pleasure=0.5).to_dict()},
            "B": {"emotional_state": EmotionalState(pleasure=-0.5).to_dict()}
        }
        engine.memory_manager.load_user_state = MagicMock(side_effect=lambda uid: states.get(uid, {}))
        engine._perceive = MagicMock(return_value={})
        _, state_a = await engine.process_turn("A", "Msg A")
        _, state_b = await engine.process_turn("B", "Msg B")
        assert state_a["pleasure"] > 0
        assert state_b["pleasure"] < 0
    asyncio.run(run_test())

def test_identity_binding():
    async def run_test():
        engine = ConversationEngine()
        auth_id = "auth_user"
        engine.memory_manager.load_user_state = MagicMock(return_value={"relationship_state": {"user_id": "wrong"}})
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()
        sync_mock = MagicMock()
        engine.memory_manager.sync_state = sync_mock
        engine._perceive = MagicMock(return_value={})
        await engine.process_turn(auth_id, "Hello")
        args, _ = sync_mock.call_args
        assert args[0] == auth_id
        assert args[2].user_id == auth_id
    asyncio.run(run_test())

def test_fail_closed_load():
    async def run_test():
        engine = ConversationEngine()
        engine.memory_manager.supabase = MagicMock()
        engine.memory_manager.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("RAW")
        engine._perceive = MagicMock(return_value={})
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        with pytest.raises(StateLoadError) as exc:
            await engine.process_turn("user", "Msg")
        assert "RAW" not in str(exc.value)
    asyncio.run(run_test())

def test_persistence_failure_zero_rows():
    async def run_test():
        engine = ConversationEngine()
        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.supabase = MagicMock()
        engine.memory_manager.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={})
        with pytest.raises(StatePersistenceError):
            await engine.process_turn("user", "Msg")
    asyncio.run(run_test())

def test_perception_normalization():
    engine = ConversationEngine()
    assert engine._normalize_perception(None)["valence"] == 0.0
    raw = {"valence": "bad", "arousal_shift": math.inf, "triggered_emotions": {"joy": 2.0, "hate": 1.0}}
    norm = engine._normalize_perception(raw)
    assert norm["valence"] == 0.0
    assert norm["arousal_shift"] == 0.0
    assert norm["triggered_emotions"]["joy"] == 1.0
    assert "hate" not in norm["triggered_emotions"]

def test_concurrent_requests_serialization():
    async def run_test():
        engine = ConversationEngine()
        user_id = "test_user"
        db = {user_id: {"emotional_state": {"pleasure": 0.0}}}
        engine.memory_manager.load_user_state = MagicMock(side_effect=lambda uid: db[uid].copy())
        def mock_sync(uid, state, rel, profile=None): db[uid]["emotional_state"] = state.to_dict()
        engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={"valence": 0.1})

        loop = asyncio.get_running_loop()
        req1_in = asyncio.Event()
        def sync_chat_mock(*args, **kwargs):
            loop.call_soon_threadsafe(req1_in.set)
            time.sleep(0.2)
            m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
            return m
        engine.groq_manager.chat_completion = MagicMock(side_effect=sync_chat_mock)

        t1 = asyncio.create_task(engine.process_turn(user_id, "T1"))
        await req1_in.wait()
        t2 = asyncio.create_task(engine.process_turn(user_id, "T2"))
        await asyncio.gather(t1, t2)
        assert db[user_id]["emotional_state"]["pleasure"] > 0.15
    asyncio.run(run_test())

def test_no_global_lock():
    async def run_test():
        engine = ConversationEngine()
        barrier = threading.Barrier(2)
        def sync_chat_mock(*args, **kwargs):
            barrier.wait(timeout=2)
            m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
            return m
        engine.groq_manager.chat_completion = MagicMock(side_effect=sync_chat_mock)
        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={})
        await asyncio.gather(engine.process_turn("A", "M"), engine.process_turn("B", "M"))
    asyncio.run(run_test())

def test_lock_cleanup():
    async def run_test():
        engine = ConversationEngine()
        user_id = "cleanup_user"
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)
        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={})

        await engine.process_turn(user_id, "Msg")
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

        engine.memory_manager.sync_state.side_effect = Exception("Fail")
        try: await engine.process_turn(user_id, "Msg")
        except Exception: pass
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks
    asyncio.run(run_test())

def test_lock_cleanup_on_cancellation_during_thread_work():
    async def run_test():
        engine = ConversationEngine()
        user_id = "cancel_thread_user"

        import threading
        load_reached = threading.Event()
        load_release = threading.Event()
        load_finished = False

        def mock_load(uid):
            load_reached.set()
            load_release.wait(timeout=2)
            nonlocal load_finished
            load_finished = True
            return {
                "emotional_state": EmotionalState().to_dict(),
                "relationship_state": UserRelationship(user_id=uid).to_dict()
            }

        engine.memory_manager.load_user_state = MagicMock(side_effect=mock_load)
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={"valence": 0.0})
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)

        # 1. Start process_turn
        task1 = asyncio.create_task(engine.process_turn(user_id, "Msg 1"))

        # Wait for task1 to reach mock_load in the worker thread
        for _ in range(40):
            if load_reached.is_set():
                break
            await asyncio.sleep(0.05)
        assert load_reached.is_set()

        # 2. While task1 is blocked, start task2 for the same user
        task2_started = False
        task2_done = False
        async def run_task2():
            nonlocal task2_started, task2_done
            task2_started = True
            await engine.process_turn(user_id, "Msg 2")
            task2_done = True

        task2 = asyncio.create_task(run_task2())
        await asyncio.sleep(0.1) # Let task2 queue up on the lock

        # Cancel task1 while it is blocked inside mock_load
        task1.cancel()
        await asyncio.sleep(0.1)

        # task1 should NOT be completed yet because load_release is not set (it's waiting for thread)
        assert not task1.done()
        assert not task2_done

        # Release the thread block
        load_release.set()

        # Now task1 should complete and propagate CancelledError
        try:
            await task1
        except asyncio.CancelledError:
            pass

        # task2 can now acquire the lock and finish
        await task2
        assert task2_done
        assert load_finished

        # Lock entry is cleaned up
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_lock_cleanup_on_cancellation_during_sync_state():
    async def run_test():
        engine = ConversationEngine()
        user_id = "cancel_sync_user"

        import threading
        sync_reached = threading.Event()
        sync_release = threading.Event()
        sync_finished = False

        def mock_sync(uid, state, rel):
            sync_reached.set()
            sync_release.wait(timeout=2)
            nonlocal sync_finished
            sync_finished = True

        engine.memory_manager.load_user_state = MagicMock(return_value={})
        engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={"valence": 0.0})
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)

        # 1. Start process_turn
        task1 = asyncio.create_task(engine.process_turn(user_id, "Msg 1"))

        # Wait for task1 to reach mock_sync in the worker thread
        for _ in range(40):
            if sync_reached.is_set():
                break
            await asyncio.sleep(0.05)
        assert sync_reached.is_set()

        # Cancel task1 while it is blocked inside mock_sync
        task1.cancel()
        await asyncio.sleep(0.1)

        # task1 should NOT be completed yet
        assert not task1.done()

        # Release the thread block
        sync_release.set()

        # Now task1 should complete and propagate CancelledError
        try:
            await task1
        except asyncio.CancelledError:
            pass

        assert sync_finished

        # Lock entry is cleaned up
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())

def test_lock_cleanup_on_cancellation_during_waiting():
    async def run_test():
        engine = ConversationEngine()
        user_id = "waiter_cancel_user"

        import threading
        load_reached = threading.Event()
        load_release = threading.Event()

        def mock_load(uid):
            load_reached.set()
            load_release.wait(timeout=2)
            return {}

        engine.memory_manager.load_user_state = MagicMock(side_effect=mock_load)
        engine.memory_manager.sync_state = MagicMock()
        engine.memory_manager.save_turn = MagicMock()
        engine._perceive = MagicMock(return_value={})
        m = MagicMock(); m.choices = [MagicMock()]; m.choices[0].message.content = "Hi"
        engine.groq_manager.chat_completion = MagicMock(return_value=m)

        # Task 1 holds the lock and blocks on load
        task1 = asyncio.create_task(engine.process_turn(user_id, "Msg 1"))

        # Wait for Task 1 to enter load
        for _ in range(40):
            if load_reached.is_set():
                break
            await asyncio.sleep(0.05)
        assert load_reached.is_set()

        # Task 2 queues up on the lock (waiting)
        task2 = asyncio.create_task(engine.process_turn(user_id, "Msg 2"))
        await asyncio.sleep(0.1) # Let task2 wait

        # Check ref count is 2
        async with engine.lock_manager._dict_lock:
            assert engine.lock_manager._locks[user_id][1] == 2

        # Cancel Task 2 (the waiter) while Task 1 is still holding the lock
        task2.cancel()

        # Wait for task2 to propagate CancelledError
        try:
            await task2
        except asyncio.CancelledError:
            pass

        # Ref count should be decremented to 1, but entry must still exist because Task 1 holds it
        async with engine.lock_manager._dict_lock:
            assert user_id in engine.lock_manager._locks
            assert engine.lock_manager._locks[user_id][1] == 1

        # Release Task 1
        load_release.set()
        await task1

        # Lock entry should be completely removed now
        async with engine.lock_manager._dict_lock:
            assert user_id not in engine.lock_manager._locks

    asyncio.run(run_test())
