import json
import asyncio
import time
import logging
from typing import Optional
from fastapi import BackgroundTasks
from .groq_manager import GroqClientManager, GroqPoolExhaustedError, GroqRequestError, ProviderFailure, provider_failure_to_turn_code
from .emotional_core import AffectiveEngine
from .emotional_domain import (
    AppraisalV1,
    EmotionalStateV1,
    TransitionConfig,
    migrate_legacy_snapshot,
    parse_llm_appraisal,
    transition,
)
from .emotion_presentation import project_public_emotion, EmotionStateResponse
from .memory import MemoryManager, StatePersistenceError, TurnPersistenceError
from .relationship import (
    RelationshipStateV1,
    RelationshipTransitionConfig,
    compute_bond_label,
    migrate_legacy_relationship_snapshot,
    transition_relationship,
)
from .lock_manager import UserLockManager
from .archival_memory import (
    PersistedTurnRef,
    parse_archival_extraction,
    compute_idempotency_key,
    EXTRACTOR_VERSION,
    ArchivalDuplicateError
)
from .turn_execution import (
    TurnExecutionConfig,
    TurnBudget,
    TurnErrorCode,
    TurnStage,
    StageOutcome,
    StageEvent,
    TurnExecutionError,
    DeadlineExceeded,
    create_budget,
)

logger = logging.getLogger(__name__)


class ConversationEngine:
    def __init__(
        self,
        clock=time.time,
        archival_extraction_enabled: bool = False,
        turn_config: Optional[TurnExecutionConfig] = None,
    ):
        self._clock = clock
        self._monotonic = time.monotonic
        self._turn_config = turn_config or TurnExecutionConfig.defaults()
        self.archival_extraction_enabled = archival_extraction_enabled
        groq_params = self._turn_config.to_groq_params()
        self.groq_manager = GroqClientManager(groq_params=groq_params)
        self.presentation = AffectiveEngine()
        self.transition_config = TransitionConfig.defaults()
        self.memory_manager = MemoryManager(
            clock=clock,
            supabase_timeout=self._turn_config.supabase_timeout,
        )
        self.relationship_config = RelationshipTransitionConfig.defaults()
        self.lock_manager = UserLockManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def run_archival_extraction(self, turn_ref: PersistedTurnRef):
        if not self.archival_extraction_enabled:
            return
        try:
            user_message = await asyncio.to_thread(
                self.memory_manager.load_persisted_user_message,
                turn_ref.user_id, turn_ref.source_chat_log_id
            )
        except Exception:
            logger.error("Event: archival_extraction_load_failed")
            return
        prompt = f"""
        Extract facts from this user message for archival memory.
        Facts should be significant, long-term personal details.
        Return JSON ONLY matching: {{"facts":[...], "schema_version":1, "extractor_version":1}}
        Maximum of 5 facts. If no relevant facts, return empty facts list.
        User message: "{user_message}"
        """
        try:
            chat_completion = await asyncio.to_thread(
                self.groq_manager.chat_completion,
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast, temperature=0.0,
                response_format={"type": "json_object"}
            )
            response_text = chat_completion.choices[0].message.content
        except Exception:
            logger.error("Event: archival_extraction_llm_failed")
            return
        try:
            raw_envelope = json.loads(response_text)
        except Exception:
            logger.warning("Event: archival_extraction_invalid")
            return
        try:
            envelope = parse_archival_extraction(raw_envelope)
        except Exception:
            logger.warning("Event: archival_extraction_invalid")
            return
        idempotency_key = compute_idempotency_key(
            turn_ref.user_id, turn_ref.source_chat_log_id, EXTRACTOR_VERSION
        )
        try:
            await asyncio.to_thread(
                self.memory_manager.store_archival_extraction,
                turn_ref.user_id, turn_ref.source_chat_log_id,
                idempotency_key, envelope
            )
        except ArchivalDuplicateError:
            logger.info("Event: archival_extraction_duplicate")
        except Exception:
            logger.error("Event: archival_extraction_store_failed")

    @staticmethod
    def _project_emotion_state(state: EmotionalStateV1, appraisal: AppraisalV1) -> EmotionStateResponse:
        return project_public_emotion(state, appraisal)

    async def _emit_stage_event(self, event: StageEvent) -> None:
        parts = ["event=turn_stage_completed", f"stage={event.stage.value}", f"outcome={event.outcome.value}"]
        if event.code is not None:
            parts.append(f"code={event.code.value}")
        if event.duration_ms is not None:
            parts.append(f"duration_ms={event.duration_ms:.0f}")
        if event.attempt is not None:
            parts.append(f"attempt={event.attempt}")
        logger.info(" ".join(parts))

    async def process_turn(
        self,
        user_id: str,
        user_message: str,
        background_tasks: Optional[BackgroundTasks] = None,
    ):
        budget = create_budget(self._turn_config, now_provider=self._monotonic)

        # Lock acquisition timeout is handled inside _run_turn_locked.
        # The rest of the turn runs under budget checks (each stage
        # checks remaining_before_reserve).  The commit section uses a
        # named task protected by asyncio.shield.
        return await self._run_turn_locked(
            user_id, user_message, background_tasks, budget
        )

    async def _run_turn_locked(self, user_id, user_message, background_tasks, budget):
        # Only the lock acquisition is bounded by remaining_before_reserve.
        # Once acquired, the turn runs under budget checks (each stage
        # checks remaining_before_reserve).  This prevents the outer timeout
        # from firing while the commit section (protected by shield) is
        # executing, which would release the lock prematurely.
        lock_timeout = budget.remaining_before_reserve
        ctx = self.lock_manager.lock(user_id)
        try:
            await asyncio.wait_for(ctx.__aenter__(), timeout=lock_timeout)
        except asyncio.TimeoutError:
            raise DeadlineExceeded()
        try:
            return await self._run_under_lock(user_id, user_message, background_tasks, budget)
        finally:
            await ctx.__aexit__(None, None, None)

    async def _run_under_lock(self, user_id, user_message, background_tasks, budget):
        current_time = self._clock()

        # Budget check before any stage — no artificial minimum
        if budget.remaining_before_reserve <= 0.0:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_state, outcome=StageOutcome.timeout, code=TurnErrorCode.turn_timeout,
            ))
            raise DeadlineExceeded()

        # ── 1. Load State ────────────────────────────────────────────────────
        t0 = self._monotonic()
        try:
            user_state = await asyncio.to_thread(
                self.memory_manager.load_user_state, user_id, default_timestamp=current_time
            )
        except Exception:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_state, outcome=StageOutcome.failed, code=TurnErrorCode.persistence_unavailable,
            ))
            raise TurnExecutionError(TurnErrorCode.persistence_unavailable, "Failed to load user state.")

        await self._emit_stage_event(StageEvent(
            stage=TurnStage.load_state, outcome=StageOutcome.success,
            duration_ms=(self._monotonic() - t0) * 1000,
        ))

        raw_emotional_state = user_state.get("emotional_state", {})
        emotional_state = migrate_legacy_snapshot(raw_emotional_state)

        rel_data = user_state.get("relationship_state")
        if rel_data:
            relationship = migrate_legacy_relationship_snapshot(rel_data)
        else:
            relationship = RelationshipStateV1.neutral(timestamp=current_time)

        # ── 2. Load Context ──────────────────────────────────────────────────
        if budget.remaining_before_reserve <= 0.0:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_context, outcome=StageOutcome.timeout, code=TurnErrorCode.turn_timeout,
            ))
            raise DeadlineExceeded()

        t0 = self._monotonic()
        try:
            context = await asyncio.to_thread(
                self.memory_manager.get_context, user_id, user_message, user_state
            )
        except Exception:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_context, outcome=StageOutcome.failed, code=TurnErrorCode.persistence_unavailable,
            ))
            raise TurnExecutionError(TurnErrorCode.persistence_unavailable, "Failed to load context.")

        await self._emit_stage_event(StageEvent(
            stage=TurnStage.load_context, outcome=StageOutcome.success,
            duration_ms=(self._monotonic() - t0) * 1000,
        ))

        # ── 3. Appraisal ─────────────────────────────────────────────────────
        if budget.remaining_before_reserve <= 0.0:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.appraisal, outcome=StageOutcome.timeout, code=TurnErrorCode.turn_timeout,
            ))
            raise DeadlineExceeded()

        t0 = self._monotonic()
        try:
            appraisal = await self._appraise(user_message, budget)
        except (TurnExecutionError, GroqPoolExhaustedError):
            duration_ms = (self._monotonic() - t0) * 1000
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.appraisal, outcome=StageOutcome.failed, duration_ms=duration_ms,
            ))
            raise
        except GroqRequestError:
            duration_ms = (self._monotonic() - t0) * 1000
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.appraisal, outcome=StageOutcome.failed,
                code=TurnErrorCode.provider_unavailable, duration_ms=duration_ms,
            ))
            raise TurnExecutionError(TurnErrorCode.provider_unavailable, "Appraisal provider request failed.")

        await self._emit_stage_event(StageEvent(
            stage=TurnStage.appraisal, outcome=StageOutcome.success,
            duration_ms=(self._monotonic() - t0) * 1000,
        ))

        # ── 4. Transition ────────────────────────────────────────────────────
        t0 = self._monotonic()
        transition_result = transition(
            previous_state=emotional_state, appraisal=appraisal,
            current_time=current_time, config=self.transition_config,
        )
        new_state = transition_result.state
        relationship = transition_relationship(
            previous_state=relationship, appraisal=appraisal,
            current_time=current_time, config=self.relationship_config,
        )
        await self._emit_stage_event(StageEvent(
            stage=TurnStage.transition, outcome=StageOutcome.success,
            duration_ms=(self._monotonic() - t0) * 1000,
        ))

        # ── 5. Generation ────────────────────────────────────────────────────
        # Requires at least a small buffer (0.5s) since generation includes
        # network I/O.  Without this, a near-zero budget would let us start
        # a provider call that cannot finish before the commit reserve.
        if budget.remaining_before_reserve <= 0.5:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.generation, outcome=StageOutcome.timeout, code=TurnErrorCode.turn_timeout,
            ))
            raise DeadlineExceeded()

        adaptation_strategy = ""
        system_prompt = self._build_system_prompt(new_state, context, relationship, adaptation_strategy)

        t0 = self._monotonic()
        try:
            response_text = await self._generate(system_prompt, user_message, budget)
        except (TurnExecutionError, GroqPoolExhaustedError):
            duration_ms = (self._monotonic() - t0) * 1000
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.generation, outcome=StageOutcome.failed, duration_ms=duration_ms,
            ))
            raise
        except GroqRequestError:
            duration_ms = (self._monotonic() - t0) * 1000
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.generation, outcome=StageOutcome.failed,
                code=TurnErrorCode.provider_unavailable, duration_ms=duration_ms,
            ))
            raise TurnExecutionError(TurnErrorCode.provider_unavailable, "Generation provider request failed.")

        await self._emit_stage_event(StageEvent(
            stage=TurnStage.generation, outcome=StageOutcome.success,
            duration_ms=(self._monotonic() - t0) * 1000,
        ))

        # ── 6. Commit Section (persistence — protected against cancel) ──────
        if not budget.has_reserve:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.commit, outcome=StageOutcome.timeout, code=TurnErrorCode.turn_timeout,
            ))
            raise DeadlineExceeded()

        # Named commit task — protected by asyncio.shield.
        #
        # When the outer task is cancelled while commit is in flight:
        # 1. Catch CancelledError (shield already protects commit_task)
        # 2. Continue waiting for commit_task under shield, using budget.remaining
        # 3. Hold the user lock during this wait (we are inside _run_turn_locked)
        # 4. Re-raise CancelledError after commit completes or times out
        #
        # Repeated cancellations during step 2 are consumed harmlessly because
        # shield prevents them from cancelling commit_task and we catch them.
        async def commit_section() -> tuple:
            t0 = self._monotonic()
            turn_ref = await asyncio.to_thread(
                self.memory_manager.save_turn, user_id, user_message, response_text
            )
            await asyncio.to_thread(
                self.memory_manager.sync_state, user_id, new_state, relationship
            )
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.commit, outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))
            return turn_ref

        commit_task = asyncio.create_task(commit_section(), name=f"commit-{user_id}")

        try:
            turn_ref = await asyncio.shield(commit_task)
        except asyncio.CancelledError:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.commit, outcome=StageOutcome.cancelled,
            ))
            # Wait for commit to finish using budget.remaining as timeout.
            # The double-shield means wait_for's timeout won't cancel commit_task.
            commit_wait = max(budget.remaining, self._turn_config.supabase_timeout * 2 + 1.0)
            try:
                turn_ref = await asyncio.wait_for(
                    asyncio.shield(commit_task), timeout=commit_wait
                )
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.error("event=commit_timeout_after_cancel")
                turn_ref = None
            except Exception:
                logger.error("event=commit_failed_after_cancel")
                turn_ref = None
            # Re-raise CancelledError after commit completes/abandons.
            # The lock remains held until this coroutine exits _run_turn_locked.
            raise asyncio.CancelledError()

        except (TurnPersistenceError, StatePersistenceError) as exc:
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.commit, outcome=StageOutcome.failed,
                code=TurnErrorCode.persistence_unavailable,
            ))
            raise TurnExecutionError(
                TurnErrorCode.persistence_unavailable,
                "Turn persistence failed.",
            ) from exc

        if background_tasks and self.archival_extraction_enabled:
            background_tasks.add_task(self.run_archival_extraction, turn_ref)

        return response_text, self._project_emotion_state(new_state, appraisal)

    async def _appraise(self, message: str, budget: TurnBudget) -> AppraisalV1:
        prompt = f"""
        Analyze the emotional impact of this message on the listener (Katherine).
        Return JSON ONLY:
        {{"valence": -1.0 to 1.0, "arousal_shift": -1.0 to 1.0,
          "dominance_shift": -1.0 to 1.0,
          "triggered_emotions": {{"joy": 0-1, "sadness": 0-1, "anger": 0-1,
             "fear": 0-1, "disgust": 0-1, "surprise": 0-1, "tenderness": 0-1,
             "guilt": 0-1, "pride": 0-1, "jealousy": 0-1, "gratitude": 0-1}}}}
        Message: "{message}"
        """
        try:
            response = await self.groq_manager.chat_completion_async(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast, budget=budget, stage="appraisal",
                temperature=0, response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            if not raw or not isinstance(raw, str) or not raw.strip():
                raise TurnExecutionError(TurnErrorCode.provider_invalid_response, "Empty appraisal response.")
            raw_dict = json.loads(raw)
        except json.JSONDecodeError:
            raise TurnExecutionError(TurnErrorCode.provider_invalid_response, "Invalid JSON from appraisal.")
        except TurnExecutionError:
            raise
        except GroqPoolExhaustedError:
            raise

        parse_result = parse_llm_appraisal(raw_dict)
        if parse_result.is_fallback:
            logger.info(f"event=emotional_appraisal_fallback code={parse_result.error_code.value}")
            raise TurnExecutionError(TurnErrorCode.provider_invalid_response, "Invalid appraisal.")
        return parse_result.appraisal

    async def _generate(self, system_prompt: str, user_message: str, budget: TurnBudget) -> str:
        try:
            response = await self.groq_manager.chat_completion_async(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
                model=self.model_main, budget=budget, stage="generation",
                temperature=0.8, max_tokens=200,
            )
        except GroqPoolExhaustedError:
            raise
        except GroqRequestError:
            raise TurnExecutionError(TurnErrorCode.provider_unavailable, "Generation provider request failed.")

        try:
            content = response.choices[0].message.content
        except (IndexError, AttributeError):
            raise TurnExecutionError(TurnErrorCode.provider_invalid_response, "Empty generation response.")

        if not content or not isinstance(content, str) or not content.strip():
            raise TurnExecutionError(TurnErrorCode.provider_invalid_response, "Empty generation response.")

        return content

    def _build_system_prompt(self, emotion_state, context, relationship, adaptation_strategy=""):
        acting_instruction = self.presentation.get_acting_instruction(emotion_state)
        mood_label = self.presentation.get_emotional_label(emotion_state)
        coping_instruction = ""
        prompt = f"""
        {context}
        === SEU ESTADO INTERNO ===
        HUMOR: {mood_label}
        Prazer: {emotion_state.pleasure:.2f} | Arousal: {emotion_state.arousal:.2f} | Dominância: {emotion_state.dominance:.2f}
        Libido: {emotion_state.libido:.2f} | Agressão: {emotion_state.aggression:.2f} | Conexão: {emotion_state.connection:.2f}
        VÍNCULO: {compute_bond_label(relationship)}
        Confiança: {relationship.trust:.2f} | Afeto: {relationship.affection:.2f} | Tensão: {relationship.tension:.2f}
        === INSTRUÇÃO DE ATUAÇÃO ===
        {acting_instruction} {coping_instruction}
        {adaptation_strategy if adaptation_strategy else "Seja você mesma."}
        1. Profundidade emocional genuína.
        2. Use linguagem sensorial.
        3. Show, don't tell.
        4. Micro-comportamentos naturais.
        5. Imperfeições naturais.
        6. Transparência de identidade (IA/assistente digital quando perguntada).
        7. Pronomes femininos.
        8. Não manipulação e não sexualização.
        9. Limites sem escalada.
        10. Use metáforas humanas, não de máquina.
        11. Respostas concisas (max 2-3 frases).
        12. Leve em conta o relacionamento.
        """
        return prompt
