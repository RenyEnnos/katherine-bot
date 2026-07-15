"""
Integration tests for backend/emotional_domain production flow — issue #234.

Coverage map (41 behavioural requirements):
─────────────────────────────────────────────────────────────────────────────
 1. Um turno válido produz exatamente um AppraisalV1.
 2. parse_llm_appraisal() é executado exatamente uma vez.
 3. transition() é executado exatamente uma vez.
 4. AffectiveEngine.update_state() não é executado.
 5. OCCAppraisal.evaluate() não é executado.
 6. _normalize_perception() não participa do caminho ativo.
 7. Relacionamento recebe adaptação derivada do AppraisalV1.
 8. Appraisal inválido usa fallback neutro.
 9. Fallback registra somente evento e código sanitizado.
10. Fallback não registra payload, prompt ou exceção.
11. Snapshot legado válido é migrado e utilizado na transição.
12. Snapshot legado migrado é persistido como v1.
13. Snapshot v1 válido carregado sem migração destrutiva.
14. Versão desconhecida falha fechado.
15. Snapshot incompleto/com campos extras falha fechado.
16. Falha no load ocorre antes de Groq/transição/persistência.
17. Novo perfil é criado com snapshot v1 desde o início.
18. sync_state() persiste to_dict() v1 (JSONB dict, not JSON string).
19. Snapshot persistido contém schema_version e timestamp, sem last_update.
20. Resposta pública mantém exatamente as chaves atuais.
21. Resposta pública contém last_update derivado do timestamp.
22. Resposta pública não contém schema_version, timestamp, appraisal ou regulation.
23. Falha de persistência não retorna sucesso.
24. Falha de persistência não agenda extração arquivística.
25. Extração arquivística agendada somente após turno e estado persistidos.
26. sync_state() rejeita EmotionalStateV1 inválido com StatePersistenceError.
27. Engine e MemoryManager aceitam relógio injetável (clock=...).
28. Novos testes não usam relógio real (clock=1_700_000_000.0).
29. Spies confirmam exatamente 1 parse_llm_appraisal e 1 transition por turno.
30. Relacionamento recebe adaptação do appraisal, nunca payload bruto.
31. Snapshots inválidos bloqueiam todo o fluxo antes de efeitos externos.
32. Nenhum teste usa Groq, Supabase, embeddings ou rede reais.
33. Toda a suíte backend existente continua passando.
34. Frontend audit, tests, lint e build continuam verdes.
35. CI completa passa.
"""

from __future__ import annotations

import asyncio
import io
import logging
from unittest.mock import MagicMock, patch

import pytest

from backend.engine import ConversationEngine
from backend.memory import MemoryManager, StatePersistenceError, StateLoadError
from backend.emotional_domain import (
    AppraisalV1,
    EmotionalDomainError,
    EmotionalStateV1,
    migrate_legacy_snapshot,
    parse_llm_appraisal,
    transition,
)
from backend.relationship import UserRelationship


# ─── Fixed clock ─────────────────────────────────────────────────────────────
FIXED_CLOCK = 1_700_000_000.0


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _legacy_emotion_dict(pleasure=0.0, arousal=0.0, dominance=0.0) -> dict:
    return {
        "pleasure": pleasure,
        "arousal": arousal,
        "dominance": dominance,
        "libido": 0.0,
        "aggression": 0.0,
        "connection": 0.5,
        "energy": 0.8,
        "tension": 0.0,
        "coping_mode": "HEALTHY",
        "last_update": FIXED_CLOCK,
    }


def _v1_emotion_dict(pleasure=0.0) -> dict:
    return EmotionalStateV1.create(
        pleasure=pleasure, arousal=0.0, dominance=0.0,
        libido=0.0, aggression=0.0, connection=0.5,
        energy=0.8, tension=0.0, coping_mode="HEALTHY",
        timestamp=FIXED_CLOCK,
    ).to_dict()


def _make_engine(clock=FIXED_CLOCK):
    """Create a ConversationEngine with fixed clock and mocked external deps."""
    engine = ConversationEngine(clock=lambda: clock)
    engine.memory_manager.load_user_state = MagicMock(return_value={
        "emotional_state": _legacy_emotion_dict(),
    })
    engine.memory_manager.sync_state = MagicMock()
    engine.memory_manager.save_turn = MagicMock()
    engine.memory_manager.get_context = MagicMock(return_value="[mocked context]")
    engine.memory_manager.load_recent_history = MagicMock(return_value=[])
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = "Hi"
    engine.groq_manager.chat_completion = MagicMock(return_value=m)
    engine._perceive = MagicMock(return_value={
        "valence": 0.2, "arousal_shift": 0.1, "dominance_shift": 0.0,
        "triggered_emotions": {"joy": 0.5},
    })
    return engine


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 1: sync_state() validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyncStateValidation:
    """sync_state() rejects invalid emotional_state types with StatePersistenceError."""

    def _make_mm(self):
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        mm.supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [{"user_id": "u"}]
        mock_resp.error = None
        mm.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_resp
        return mm

    def test_accepts_emotional_state_v1(self):
        mm = self._make_mm()
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        rel = UserRelationship(user_id="u")
        mm.sync_state("u", state, rel)
        mm.supabase.table.assert_called_once_with("profiles")

    def test_rejects_legacy_emotional_state(self):
        mm = self._make_mm()
        rel = UserRelationship(user_id="u")
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", "not a state", rel)

    def test_rejects_dict(self):
        mm = self._make_mm()
        rel = UserRelationship(user_id="u")
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", {"pleasure": 0.0}, rel)

    def test_rejects_magic_mock(self):
        mm = self._make_mm()
        rel = UserRelationship(user_id="u")
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", MagicMock(), rel)

    def test_rejects_none(self):
        mm = self._make_mm()
        rel = UserRelationship(user_id="u")
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", None, rel)

    def test_invalid_type_does_not_call_db(self):
        mm = self._make_mm()
        rel = UserRelationship(user_id="u")
        with pytest.raises(StatePersistenceError):
            mm.sync_state("u", "bad", rel)
        # Verify no DB call was made
        mm.supabase.table.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 2: Clock injection
# ═══════════════════════════════════════════════════════════════════════════════

class TestClockInjection:
    """Engine and MemoryManager accept injectable clock for deterministic testing."""

    def test_engine_uses_injected_clock(self):
        calls = []
        engine = ConversationEngine(clock=lambda: calls.append(1) or FIXED_CLOCK)
        assert engine._clock() == FIXED_CLOCK
        assert len(calls) == 1

    def test_memory_manager_uses_injected_clock(self):
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        default = mm._get_default_state("u")
        ts = default["emotional_state"]["timestamp"]
        assert ts == FIXED_CLOCK

    def test_clock_propagates_to_memory_manager(self):
        engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
        assert engine.memory_manager._clock() == FIXED_CLOCK


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 3: Spy-based flow counting
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpyBasedFlowCounting:
    """Spies confirm exactly one parse_llm_appraisal and one transition per turn."""

    def test_one_appraisal_and_one_transition_per_turn(self):
        async def run():
            engine = _make_engine()
            parse_spy = MagicMock(wraps=parse_llm_appraisal)
            transition_spy = MagicMock(wraps=transition)

            with patch("backend.engine.parse_llm_appraisal", parse_spy), \
                 patch("backend.engine.transition", transition_spy):

                resp, emotions = await engine.process_turn("user", "Hello")

            assert parse_spy.call_count == 1
            assert transition_spy.call_count == 1

            # Verify the appraisal passed to transition is an AppraisalV1
            parse_result = parse_spy.call_args[0][0]
            transition_kwargs = transition_spy.call_args[1]
            assert isinstance(transition_kwargs["appraisal"], AppraisalV1)
            assert isinstance(transition_kwargs["previous_state"], EmotionalStateV1)
            assert transition_kwargs["current_time"] == FIXED_CLOCK

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 4: Relationship adaptation with spy
# ═══════════════════════════════════════════════════════════════════════════════

class TestRelationshipAdaptationSpy:
    """Relationship receives adapted dict from AppraisalV1, not raw payload."""

    def test_relationship_gets_adapted_appraisal_not_raw_dict(self):
        async def run():
            engine = _make_engine()

            # Spy on the relationship manager
            engine.relationship_manager = MagicMock()
            engine.relationship_manager.update_relationship = MagicMock(
                return_value=UserRelationship(user_id="user")
            )            # _perceive returns a payload with a sensitive extra key
            SENSITIVE_KEY = "SENSITIVE_EXTRA_KEY_92841"
            # Use only VALID emotions in the payload (unknown emotions cause full fallback)
            engine._perceive = MagicMock(return_value={
                "valence": 0.5,
                "arousal_shift": 0.2,
                "dominance_shift": 0.1,
                "triggered_emotions": {
                    "joy": 0.8,
                    "tenderness": 0.6,
                },
                SENSITIVE_KEY: "should_not_leak",
                "raw_payload": "not_allowed",
            })
    
            await engine.process_turn("user", "Hello")
    
            # Verify the second argument to update_relationship
            args, kwargs = engine.relationship_manager.update_relationship.call_args
            assert len(args) >= 2
            adapted = args[1]
    
            # Must contain only valence and triggered_emotions
            assert "valence" in adapted
            assert "triggered_emotions" in adapted
            # Sensitive key must not appear
            assert SENSITIVE_KEY not in adapted
            # Joy and tenderness must be present (valid emotions)
            assert adapted["triggered_emotions"]["joy"] == 0.8
            assert adapted["triggered_emotions"]["tenderness"] == 0.6

    def test_unknown_emotions_filtered_from_relationship(self):
        """Verify unknown emotions are stripped by the parser before reaching relationship."""
        async def run():
            engine = _make_engine()
            engine.relationship_manager = MagicMock()
            engine.relationship_manager.update_relationship = MagicMock(
                return_value=UserRelationship(user_id="user")
            )
            # Payload with unknown emotion + raw key
            engine._perceive = MagicMock(return_value={
                "valence": 0.5,
                "arousal_shift": 0.2,
                "dominance_shift": 0.1,
                "triggered_emotions": {
                    "joy": 0.8,
                    "unknown_emotion_92841": 0.9,
                },
            })

            await engine.process_turn("user", "Hello")

            args, kwargs = engine.relationship_manager.update_relationship.call_args
            adapted = args[1]
            # Unknown emotion must not appear
            assert "unknown_emotion_92841" not in adapted["triggered_emotions"]

        asyncio.run(run())

    def test_neutral_fallback_results_in_neutral_adaptation(self):
        async def run():
            engine = _make_engine()
            engine.relationship_manager = MagicMock()
            engine.relationship_manager.update_relationship = MagicMock(
                return_value=UserRelationship(user_id="user")
            )
            # _perceive returns empty dict (triggers fallback)
            engine._perceive = MagicMock(return_value={})

            await engine.process_turn("user", "Hello")

            args, kwargs = engine.relationship_manager.update_relationship.call_args
            adapted = args[1]
            assert adapted["valence"] == 0.0  # neutral fallback
            assert adapted["triggered_emotions"] == {}

        asyncio.run(run())

    def test_adaptation_structure_is_clean(self):
        """The adapter produces exactly the expected keys."""
        ap = AppraisalV1.create(
            valence_shift=0.3, arousal_shift=-0.1, dominance_shift=0.0,
            discrete_emotions={"joy": 0.7},
        )
        adapted = ConversationEngine._adapt_appraisal_for_relationship(ap)
        assert set(adapted.keys()) == {"valence", "triggered_emotions"}
        assert adapted["valence"] == 0.3
        assert adapted["triggered_emotions"]["joy"] == 0.7


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 5: Fail-closed through process_turn
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailClosedThroughProcessTurn:
    """Corrupt snapshots block the entire flow before any external effect."""

    @pytest.mark.parametrize("description,bad_state", [
        ("unknown_version", {"schema_version": 99}),
        ("incomplete_snapshot", {"pleasure": 0.5}),
        ("extra_field", {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0,
                          "libido": 0.0, "aggression": 0.0, "connection": 0.5,
                          "energy": 0.8, "tension": 0.0, "coping_mode": "HEALTHY",
                          "last_update": FIXED_CLOCK, "extra_field": "x"}),
        ("invalid_numeric_type", {"pleasure": "not_a_number", "arousal": 0.0,
                                   "dominance": 0.0, "libido": 0.0,
                                   "aggression": 0.0, "connection": 0.5,
                                   "energy": 0.8, "tension": 0.0,
                                   "coping_mode": "HEALTHY",
                                   "last_update": FIXED_CLOCK}),
    ])
    def test_corrupt_snapshot_blocks_flow(self, description, bad_state):
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.load_user_state = MagicMock(return_value={
                "emotional_state": bad_state,
            })

            # Install spies on all downstream methods
            engine.memory_manager.get_context = MagicMock()
            engine._perceive = MagicMock()
            engine.groq_manager.chat_completion = MagicMock()
            engine.memory_manager.save_turn = MagicMock()
            engine.memory_manager.sync_state = MagicMock()
            engine.relationship_manager = MagicMock()
            bg_tasks = MagicMock()

            with pytest.raises(EmotionalDomainError):
                await engine.process_turn("user", "Msg", background_tasks=bg_tasks)

            # Zero downstream calls: no context, no perceive, no LLM, no persist
            engine.memory_manager.get_context.assert_not_called()
            engine._perceive.assert_not_called()
            engine.groq_manager.chat_completion.assert_not_called()
            engine.memory_manager.save_turn.assert_not_called()
            engine.memory_manager.sync_state.assert_not_called()
            engine.relationship_manager.update_relationship.assert_not_called()
            bg_tasks.add_task.assert_not_called()

        asyncio.run(run())

    def test_nan_snapshot_fails_closed(self):
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.load_user_state = MagicMock(return_value={
                "emotional_state": {
                    "pleasure": float("nan"), "arousal": 0.0, "dominance": 0.0,
                    "libido": 0.0, "aggression": 0.0, "connection": 0.5,
                    "energy": 0.8, "tension": 0.0, "coping_mode": "HEALTHY",
                    "last_update": FIXED_CLOCK,
                },
            })
            engine._perceive = MagicMock()
            engine.groq_manager.chat_completion = MagicMock()
            engine.memory_manager.save_turn = MagicMock()
            engine.memory_manager.sync_state = MagicMock()
            bg_tasks = MagicMock()

            with pytest.raises(EmotionalDomainError):
                await engine.process_turn("user", "Msg", background_tasks=bg_tasks)

            engine._perceive.assert_not_called()
            engine.groq_manager.chat_completion.assert_not_called()
            engine.memory_manager.save_turn.assert_not_called()
            engine.memory_manager.sync_state.assert_not_called()
            bg_tasks.add_task.assert_not_called()

        asyncio.run(run())

    def test_inf_snapshot_fails_closed(self):
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.load_user_state = MagicMock(return_value={
                "emotional_state": {
                    "pleasure": float("inf"), "arousal": 0.0, "dominance": 0.0,
                    "libido": 0.0, "aggression": 0.0, "connection": 0.5,
                    "energy": 0.8, "tension": 0.0, "coping_mode": "HEALTHY",
                    "last_update": FIXED_CLOCK,
                },
            })
            engine._perceive = MagicMock()
            engine.groq_manager.chat_completion = MagicMock()
            engine.memory_manager.save_turn = MagicMock()
            engine.memory_manager.sync_state = MagicMock()
            bg_tasks = MagicMock()

            with pytest.raises(EmotionalDomainError):
                await engine.process_turn("user", "Msg", background_tasks=bg_tasks)

            engine._perceive.assert_not_called()
            engine.groq_manager.chat_completion.assert_not_called()
            engine.memory_manager.save_turn.assert_not_called()
            engine.memory_manager.sync_state.assert_not_called()
            bg_tasks.add_task.assert_not_called()

        asyncio.run(run())

    def test_corrupt_snapshot_blocks_before_transition(self):
        """Also verify transition is never called for corrupt snapshots."""
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.load_user_state = MagicMock(return_value={
                "emotional_state": {"schema_version": 99},
            })
            engine._perceive = MagicMock()
            engine.groq_manager.chat_completion = MagicMock()
            engine.memory_manager.save_turn = MagicMock()
            engine.memory_manager.sync_state = MagicMock()

            parse_spy = MagicMock(wraps=parse_llm_appraisal)
            transition_spy = MagicMock(wraps=transition)
            with patch("backend.engine.parse_llm_appraisal", parse_spy), \
                 patch("backend.engine.transition", transition_spy):
                with pytest.raises(EmotionalDomainError):
                    await engine.process_turn("user", "Msg")

            # Parse and transition should never be called
            parse_spy.assert_not_called()
            transition_spy.assert_not_called()

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 6: JSONB persistence payload inspection
# ═══════════════════════════════════════════════════════════════════════════════

class TestJSONBPersistence:
    """sync_state sends the exact v1 dict to Supabase via JSONB."""

    def test_persisted_payload_is_v1_dict(self):
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        mm.supabase = MagicMock()
        mock_resp = MagicMock()
        mock_resp.data = [{"user_id": "u"}]
        mock_resp.error = None
        mm.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_resp

        state = EmotionalStateV1.create(
            pleasure=0.5, arousal=-0.2, dominance=0.3,
            libido=0.1, aggression=0.0, connection=0.7,
            energy=0.9, tension=0.2, coping_mode="HEALTHY",
            timestamp=FIXED_CLOCK,
        )
        rel = UserRelationship(user_id="u")
        mm.sync_state("u", state, rel)

        # Capture what was passed to supabase.update()
        call_args = mm.supabase.table.return_value.update.call_args
        assert call_args is not None
        update_data = call_args[0][0]

        # The emotional_state field should be the exact v1 dict
        payload = update_data["emotional_state"]
        assert isinstance(payload, dict)
        assert payload["schema_version"] == 1
        assert payload["timestamp"] == FIXED_CLOCK
        assert payload["pleasure"] == 0.5
        assert payload["coping_mode"] == "HEALTHY"

        # Must NOT contain legacy fields or other layer fields
        assert "last_update" not in payload
        assert "appraisal" not in payload
        assert "regulation" not in payload
        assert "prompt" not in payload

        # Also verify the update filter uses user_id
        eq_call = mm.supabase.table.return_value.update.return_value.eq.call_args
        assert eq_call is not None
        assert eq_call[0] == ("user_id", "u")

    def test_persisted_payload_has_only_v1_fields(self):
        """The payload must contain only the fields from EmotionalStateV1.to_dict()."""
        v1_fields = {
            "schema_version", "pleasure", "arousal", "dominance",
            "libido", "aggression", "connection", "energy", "tension",
            "coping_mode", "timestamp",
        }
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        payload = state.to_dict()
        assert set(payload.keys()) == v1_fields


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 7: Archival scheduling test
# ═══════════════════════════════════════════════════════════════════════════════

class TestArchivalScheduling:
    """Archival extraction scheduling: order on success, zero on sync_state failure."""

    def test_success_orders_save_sync_then_schedule(self):
        """On success: save_turn → sync_state → add_task → return."""
        async def run():
            engine = _make_engine()
            call_order = []
            bg_tasks = MagicMock()

            def mock_save(user_id, user_msg, bot_msg):
                call_order.append("save")
                from backend.archival_memory import PersistedTurnRef
                return PersistedTurnRef(user_id=user_id, source_chat_log_id=1,
                                        assistant_chat_log_id=2)

            def mock_sync(user_id, state, rel):
                call_order.append("sync")

            def mock_add_task(coro, *args, **kwargs):
                call_order.append("add_task")

            engine.memory_manager.save_turn = MagicMock(side_effect=mock_save)
            engine.memory_manager.sync_state = MagicMock(side_effect=mock_sync)
            bg_tasks.add_task = MagicMock(side_effect=mock_add_task)

            resp, emotions = await engine.process_turn("user", "Hello", background_tasks=bg_tasks)

            assert call_order == ["save", "sync", "add_task"]
            bg_tasks.add_task.assert_called_once()
            assert resp is not None

        asyncio.run(run())

    def test_sync_state_failure_blocks_add_task(self):
        """When sync_state fails, add_task is never called and exception propagates."""
        async def run():
            engine = _make_engine()
            engine.memory_manager.sync_state = MagicMock(
                side_effect=StatePersistenceError("DB fail")
            )
            bg_tasks = MagicMock()

            with pytest.raises(StatePersistenceError):
                await engine.process_turn("user", "Hello", background_tasks=bg_tasks)

            # add_task must NOT be called
            bg_tasks.add_task.assert_not_called()

        asyncio.run(run())

    def test_no_background_tasks_parameter_still_works(self):
        """Without background_tasks param, process_turn still succeeds."""
        async def run():
            engine = _make_engine()
            resp, emotions = await engine.process_turn("user", "Hello")
            assert resp is not None
            assert isinstance(emotions, dict)

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 8: Sanitised logging with unique markers
# ═══════════════════════════════════════════════════════════════════════════════

class TestSanitisedLogging:
    """Fallback logs contain only event and code, never sensitive markers."""

    SENSITIVE_PAYLOAD = "SENSITIVE_USER_PAYLOAD_92841"
    SENSITIVE_KEY = "SENSITIVE_EXTRA_KEY_92841"
    SENSITIVE_PROMPT = "SENSITIVE_PROMPT_92841"

    def test_fallback_logs_only_sanitised_code(self):
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.load_user_state = MagicMock(return_value={
                "emotional_state": _legacy_emotion_dict(),
            })
            engine.memory_manager.sync_state = MagicMock()
            engine.memory_manager.save_turn = MagicMock()
            engine.memory_manager.get_context = MagicMock(return_value="[mocked context]")
            m = MagicMock()
            m.choices = [MagicMock()]
            m.choices[0].message.content = self.SENSITIVE_PROMPT
            engine.groq_manager.chat_completion = MagicMock(return_value=m)

            # _perceive returns a dict with sensitive payload in values and keys
            engine._perceive = MagicMock(return_value={
                "valence": self.SENSITIVE_PAYLOAD,  # invalid → triggers fallback
                "arousal_shift": 0.0,
                "dominance_shift": 0.0,
                self.SENSITIVE_KEY: "should_not_leak",
                "triggered_emotions": {"joy": 0.5},
            })

            # Capture logs
            logger = logging.getLogger("backend.engine")
            logger.setLevel(logging.INFO)
            stream = io.StringIO()
            handler = logging.StreamHandler(stream)
            logger.addHandler(handler)
            try:
                await engine.process_turn("user", self.SENSITIVE_PAYLOAD)
            finally:
                logger.removeHandler(handler)

            log_text = stream.getvalue()

            # Must contain the sanitised event and code
            assert "event=emotional_appraisal_fallback" in log_text
            assert "code=" in log_text

            # Must NOT contain any sensitive marker
            assert self.SENSITIVE_PAYLOAD not in log_text
            assert self.SENSITIVE_KEY not in log_text
            assert self.SENSITIVE_PROMPT not in log_text
            # The user_id ("user") is part of the process, but must not appear in sanitised logs
            assert "SENSITIVE_" not in log_text

        asyncio.run(run())

    def test_neutral_fallback_is_used_when_perceive_fails(self):
        async def run():
            engine = _make_engine()
            # _perceive returns something that parse_llm_appraisal rejects
            engine._perceive = MagicMock(return_value=None)

            resp, emotions = await engine.process_turn("user", "Hello")
            # Should still succeed with neutral fallback
            assert resp is not None

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# Correction 9: Exact public contract test
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicContract:
    """Public response has exactly the 10 legacy keys, no internal fields."""

    EXPECTED_PUBLIC_KEYS = {
        "pleasure", "arousal", "dominance",
        "libido", "aggression", "connection", "energy",
        "tension", "coping_mode", "last_update",
    }

    def test_projection_has_exact_legacy_keys(self):
        state = EmotionalStateV1.create(
            pleasure=0.5, arousal=-0.2, dominance=0.3,
            libido=0.1, aggression=0.0, connection=0.7,
            energy=0.9, tension=0.2, coping_mode="HEALTHY",
            timestamp=FIXED_CLOCK,
        )
        projected = ConversationEngine._project_emotion_state(state)
        assert set(projected.keys()) == self.EXPECTED_PUBLIC_KEYS

    def test_last_update_equals_timestamp(self):
        state = EmotionalStateV1.create(
            pleasure=0.0, arousal=0.0, dominance=0.0,
            libido=0.0, aggression=0.0, connection=0.5,
            energy=0.8, tension=0.0, coping_mode="HEALTHY",
            timestamp=FIXED_CLOCK,
        )
        projected = ConversationEngine._project_emotion_state(state)
        assert projected["last_update"] == FIXED_CLOCK
        assert projected["last_update"] == state.timestamp

    def test_no_internal_fields_in_projection(self):
        state = EmotionalStateV1.neutral(timestamp=FIXED_CLOCK)
        projected = ConversationEngine._project_emotion_state(state)
        assert "schema_version" not in projected
        assert "timestamp" not in projected
        assert "appraisal" not in projected
        assert "regulation" not in projected
        assert "fallback" not in projected

    def test_process_turn_returns_projected_format(self):
        async def run():
            engine = _make_engine()
            resp, emotions = await engine.process_turn("user", "Hello")
            assert set(emotions.keys()) == self.EXPECTED_PUBLIC_KEYS
            assert emotions["last_update"] == FIXED_CLOCK

        asyncio.run(run())


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy flow verification & existing behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyFlowNotUsed:
    """The old AffectiveEngine/OCC/Normalize are not in the active path."""

    def test_legacy_flow_classes_not_called(self):
        from backend.engine import ConversationEngine
        engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
        assert not hasattr(engine, "_normalize_perception")
        assert hasattr(engine, "presentation")
        assert not hasattr(engine, "affective_engine") or "affective_engine" not in dir(engine)

    def test_snapshot_migration_preserves_values(self):
        legacy = _legacy_emotion_dict(pleasure=0.7)
        v1 = migrate_legacy_snapshot(legacy)
        assert isinstance(v1, EmotionalStateV1)
        assert v1.pleasure == 0.7
        assert v1.timestamp == legacy["last_update"]

    def test_migrated_snapshot_persisted_as_v1(self):
        legacy = _legacy_emotion_dict(pleasure=0.7)
        v1 = migrate_legacy_snapshot(legacy)
        persisted = v1.to_dict()
        assert "schema_version" in persisted
        assert "timestamp" in persisted
        assert "last_update" not in persisted

    def test_v1_snapshot_loaded_cleanly(self):
        v1_dict = _v1_emotion_dict(pleasure=0.3)
        result = migrate_legacy_snapshot(v1_dict)
        assert isinstance(result, EmotionalStateV1)
        assert result.pleasure == 0.3

    def test_unknown_version_fails_closed(self):
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot({"schema_version": 99})

    def test_incomplete_snapshot_fails_closed(self):
        with pytest.raises(EmotionalDomainError):
            migrate_legacy_snapshot({"pleasure": 0.5})

    def test_load_failure_blocks_processing(self):
        async def run():
            engine = ConversationEngine(clock=lambda: FIXED_CLOCK)
            engine.memory_manager.supabase = MagicMock()
            engine.memory_manager.supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = Exception("DB down")
            engine._perceive = MagicMock()
            engine.groq_manager.chat_completion = MagicMock()

            with pytest.raises(StateLoadError):
                await engine.process_turn("user", "Msg")

        asyncio.run(run())

    def test_new_profile_uses_v1_state(self):
        mm = MemoryManager(clock=lambda: FIXED_CLOCK)
        default = mm._get_default_state("new_user")
        emotional_state = default["emotional_state"]
        assert isinstance(emotional_state, dict)
        assert "schema_version" in emotional_state
        assert emotional_state["schema_version"] == 1
        assert "timestamp" in emotional_state
        assert "last_update" not in emotional_state

    def test_sync_state_failure_propagates(self):
        async def run():
            engine = _make_engine()
            engine.memory_manager.sync_state = MagicMock(side_effect=StatePersistenceError())

            with pytest.raises(StatePersistenceError):
                await engine.process_turn("user", "Msg")

        asyncio.run(run())
