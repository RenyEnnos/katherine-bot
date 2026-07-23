import json
import asyncio
import time
import logging
from typing import Optional, List
from fastapi import BackgroundTasks
from .groq_manager import GroqClientManager, GroqPoolExhaustedError, classify_provider_error, provider_failure_to_turn_code
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
from .memory import MemoryManager, StatePersistenceError
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
        self.groq_manager = GroqClientManager()
        self.presentation = AffectiveEngine()  # read-only presentation helpers
        self.transition_config = TransitionConfig.defaults()  # immutable, stateless
        self.memory_manager = MemoryManager(clock=clock)
        self.relationship_config = RelationshipTransitionConfig.defaults()
        self.lock_manager = UserLockManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def run_archival_extraction(self, turn_ref: PersistedTurnRef):
        # Early return when archival extraction is disabled.
        # This guard is checked even if the method is called directly by mistake.
        if not self.archival_extraction_enabled:
            return

        # 1. Load user message content
        try:
            user_message = await asyncio.to_thread(
                self.memory_manager.load_persisted_user_message,
                turn_ref.user_id,
                turn_ref.source_chat_log_id
            )
        except Exception:
            logger.error("Event: archival_extraction_load_failed")
            return

        # 2. Call LLM to extract facts
        prompt = f"""
        Extract facts from this user message for archival memory.
        Facts should be significant, long-term personal details about the user (e.g. preferences, habits, facts, background).
        Return JSON ONLY matching the following schema:
        {{
            "facts": [
                {{
                    "content": "Fact description (max 500 chars)",
                    "importance": 0.0 to 1.0 (float),
                    "tags": ["lowercase-tag-1", "lowercase-tag-2"] (max 8 tags per fact, each tag max 32 chars matching ^[a-z0-9][a-z0-9_-]*$)
                }}
            ],
            "schema_version": 1,
            "extractor_version": 1
        }}
        Maximum of 5 facts. If no relevant facts are found, return an empty facts list.
        Do not include any other markdown formatting outside the JSON code block.

        User message: "{user_message}"
        """

        try:
            chat_completion = await asyncio.to_thread(
                self.groq_manager.chat_completion,
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                temperature=0.0,
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

        # 3. Validate raw facts envelope
        try:
            envelope = parse_archival_extraction(raw_envelope)
        except Exception:
            logger.warning("Event: archival_extraction_invalid")
            return

        # 4. Generate idempotency key and store
        idempotency_key = compute_idempotency_key(
            turn_ref.user_id,
            turn_ref.source_chat_log_id,
            EXTRACTOR_VERSION
        )

        try:
            await asyncio.to_thread(
                self.memory_manager.store_archival_extraction,
                turn_ref.user_id,
                turn_ref.source_chat_log_id,
                idempotency_key,
                envelope
            )
        except ArchivalDuplicateError:
            logger.info("Event: archival_extraction_duplicate")
        except Exception:
            logger.error("Event: archival_extraction_store_failed")

    @staticmethod
    def _project_emotion_state(state: EmotionalStateV1, appraisal: AppraisalV1) -> EmotionStateResponse:
        """Project ``EmotionalStateV1`` and ``AppraisalV1`` into the public DTO.

        This produces the typed, versioned ``EmotionStateResponse`` that is safe
        to send to the browser. No internal fields leak through this projection.
        """
        return project_public_emotion(state, appraisal)

    async def _emit_stage_event(self, event: StageEvent) -> None:
        """Log a low-cardinality structured stage event.

        Only permitted fields: stage, outcome, code (sanitised), duration_ms, attempt.
        Never includes: user_id, message, prompt, response, key, token, or DB IDs.
        """
        parts = [
            "event=turn_stage_completed",
            f"stage={event.stage.value}",
            f"outcome={event.outcome.value}",
        ]
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

        async def run_under_lock() -> tuple:
            current_time = self._clock()

            # ═══════════════════════════════════════════════════════════════
            # 1. Load State
            # ═══════════════════════════════════════════════════════════════
            t0 = self._monotonic()
            user_state = await asyncio.to_thread(
                self.memory_manager.load_user_state, user_id, default_timestamp=current_time
            )
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_state,
                outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))

            # Migration boundary: legacy or v1 snapshot → EmotionalStateV1
            raw_emotional_state = user_state.get("emotional_state", {})
            emotional_state = migrate_legacy_snapshot(raw_emotional_state)

            # Hydrate Relationship State
            rel_data = user_state.get("relationship_state")
            if rel_data:
                relationship = migrate_legacy_relationship_snapshot(rel_data)
            else:
                relationship = RelationshipStateV1.neutral(timestamp=current_time)

            # ═══════════════════════════════════════════════════════════════
            # 2. Load Context
            # ═══════════════════════════════════════════════════════════════
            t0 = self._monotonic()
            context = await asyncio.to_thread(
                self.memory_manager.get_context, user_id, user_message, user_state
            )
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.load_context,
                outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))

            # ═══════════════════════════════════════════════════════════════
            # 3. Appraisal (async LLM call with budget)
            # ═══════════════════════════════════════════════════════════════
            t0 = self._monotonic()
            appraisal = await self._appraise(user_message, budget)
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.appraisal,
                outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))

            # ═══════════════════════════════════════════════════════════════
            # 4. Transition
            # ═══════════════════════════════════════════════════════════════
            t0 = self._monotonic()
            transition_result = transition(
                previous_state=emotional_state,
                appraisal=appraisal,
                current_time=current_time,
                config=self.transition_config,
            )
            new_state = transition_result.state

            relationship = transition_relationship(
                previous_state=relationship,
                appraisal=appraisal,
                current_time=current_time,
                config=self.relationship_config,
            )
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.transition,
                outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))

            # ═══════════════════════════════════════════════════════════════
            # 5. Generation (async LLM call with budget)
            # ═══════════════════════════════════════════════════════════════
            adaptation_strategy = ""
            system_prompt = self._build_system_prompt(
                new_state, context, relationship, adaptation_strategy
            )

            t0 = self._monotonic()
            response_text = await self._generate(
                system_prompt, user_message, budget
            )
            await self._emit_stage_event(StageEvent(
                stage=TurnStage.generation,
                outcome=StageOutcome.success,
                duration_ms=(self._monotonic() - t0) * 1000,
            ))

            # ═══════════════════════════════════════════════════════════════
            # 6. Commit section (persistence — protected against cancel)
            # ═══════════════════════════════════════════════════════════════
            # Check that the full commit reserve is still available.
            if not budget.has_reserve:
                await self._emit_stage_event(StageEvent(
                    stage=TurnStage.commit,
                    outcome=StageOutcome.timeout,
                    code=TurnErrorCode.turn_timeout,
                ))
                raise DeadlineExceeded()

            # Only the commit section (save_turn + sync_state) may be shielded.
            # Risk: non-atomic between save and sync (resolved in #271).
            async def commit_section() -> tuple:
                t0 = self._monotonic()
                turn_ref = await asyncio.to_thread(
                    self.memory_manager.save_turn, user_id, user_message, response_text
                )
                await asyncio.to_thread(
                    self.memory_manager.sync_state, user_id, new_state, relationship
                )
                await self._emit_stage_event(StageEvent(
                    stage=TurnStage.commit,
                    outcome=StageOutcome.success,
                    duration_ms=(self._monotonic() - t0) * 1000,
                ))
                return turn_ref

            try:
                turn_ref = await asyncio.shield(commit_section())
            except asyncio.CancelledError:
                # Commit section was cancelled mid-way.
                await self._emit_stage_event(StageEvent(
                    stage=TurnStage.commit,
                    outcome=StageOutcome.cancelled,
                ))
                raise

            # Schedule background task only after commit completes.
            if background_tasks and self.archival_extraction_enabled:
                background_tasks.add_task(self.run_archival_extraction, turn_ref)

            return response_text, self._project_emotion_state(new_state, appraisal)

        async with self.lock_manager.lock(user_id):
            try:
                return await run_under_lock()
            except (DeadlineExceeded, TurnExecutionError):
                # Timeout/exhaustion before commit → lock released, nothing persisted.
                raise
            except asyncio.CancelledError:
                # Client cancelled before commit → lock released, nothing persisted.
                raise

    async def _appraise(self, message: str, budget: TurnBudget) -> AppraisalV1:
        """Async appraisal with budget. Never returns fallback — failures raise."""
        prompt = f"""
        Analyze the emotional impact of this message on the listener (Katherine).
        Return JSON ONLY:
        {{
            "valence": -1.0 (negative) to 1.0 (positive),
            "arousal_shift": -1.0 (calming) to 1.0 (exciting),
            "dominance_shift": -1.0 (intimidating) to 1.0 (empowering),
            "triggered_emotions": {{ "joy": 0.0-1.0, "sadness": 0.0-1.0, "anger": 0.0-1.0, "fear": 0.0-1.0, "disgust": 0.0-1.0, "surprise": 0.0-1.0, "tenderness": 0.0-1.0, "guilt": 0.0-1.0, "pride": 0.0-1.0, "jealousy": 0.0-1.0, "gratitude": 0.0-1.0 }}
        }}

        Message: "{message}"
        """

        try:
            response = await self.groq_manager.chat_completion_async(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                budget=budget,
                stage="appraisal",
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            if not raw or not isinstance(raw, str) or not raw.strip():
                raise TurnExecutionError(
                    TurnErrorCode.provider_invalid_response,
                    "Empty appraisal response."
                )
            raw_dict = json.loads(raw)
        except json.JSONDecodeError:
            raise TurnExecutionError(
                TurnErrorCode.provider_invalid_response,
                "Invalid JSON from appraisal."
            )
        except TurnExecutionError:
            raise
        except GroqPoolExhaustedError as e:
            raise TurnExecutionError(
                TurnErrorCode.provider_unavailable,
                str(e),
            )
        except Exception:
            raise TurnExecutionError(
                TurnErrorCode.provider_invalid_response,
                "Appraisal failed.",
            )

        # Parse and validate — fallback in the parser MUST be treated as failure
        # at orchestration boundary.
        parse_result = parse_llm_appraisal(raw_dict)
        if parse_result.is_fallback:
            logger.info(
                f"event=emotional_appraisal_fallback code={parse_result.error_code.value}"
            )
            raise TurnExecutionError(
                TurnErrorCode.provider_invalid_response,
                "Invalid appraisal — LLM returned malformed data.",
            )

        return parse_result.appraisal

    async def _generate(self, system_prompt: str, user_message: str, budget: TurnBudget) -> str:
        """Async generation with budget. Never returns fallback text.

        Raises:
            TurnExecutionError: On any provider failure, timeout, or invalid response.
            asyncio.CancelledError: On cancellation.
        """
        try:
            response = await self.groq_manager.chat_completion_async(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model=self.model_main,
                budget=budget,
                stage="generation",
                temperature=0.8,
                max_tokens=200,
            )
        except GroqPoolExhaustedError as e:
            raise TurnExecutionError(
                TurnErrorCode.provider_unavailable,
                str(e),
            )

        # Validate response content
        try:
            content = response.choices[0].message.content
        except (IndexError, AttributeError):
            raise TurnExecutionError(
                TurnErrorCode.provider_invalid_response,
                "Empty generation response (no choices).",
            )

        if not content or not isinstance(content, str) or not content.strip():
            raise TurnExecutionError(
                TurnErrorCode.provider_invalid_response,
                "Empty or invalid generation response.",
            )

        return content

    def _build_system_prompt(self, emotion_state: EmotionalStateV1, context, relationship, adaptation_strategy=""):
        acting_instruction = self.presentation.get_acting_instruction(emotion_state)
        mood_label = self.presentation.get_emotional_label(emotion_state)

        coping_instruction = ""

        prompt = f"""
        {context}

        === SEU ESTADO INTERNO (PAD Bipolar -1.0 a +1.0) ===
        HUMOR: {mood_label}
        Prazer: {emotion_state.pleasure:.2f} | Excitação: {emotion_state.arousal:.2f} | Dominância: {emotion_state.dominance:.2f}

        === IMPULSOS E NECESSIDADES (DRIVES) ===
        Libido (Desejo): {emotion_state.libido:.2f}
        Agressividade: {emotion_state.aggression:.2f}
        Conexão: {emotion_state.connection:.2f}
        Modo de Enfrentamento: {emotion_state.coping_mode}

        === SEU RELACIONAMENTO COM O USUÁRIO ===
        VÍNCULO: {compute_bond_label(relationship)}
        Confiança: {relationship.trust:.2f} | Afeto: {relationship.affection:.2f} | Tensão/Mágoa: {relationship.tension:.2f}

        === INSTRUÇÃO DE ATUAÇÃO (IMPORTANTE) ===
        {acting_instruction}
        {coping_instruction}

        === ESTRATÉGIA DE ADAPTAÇÃO (META-COGNITION) ===
        {adaptation_strategy if adaptation_strategy else "Seja você mesma."}

        === DIRETRIZES DE RESPOSTA (EMOTION PROMPT) ===
        1. Responda com profundidade emocional genuína.
        2. USE LINGUAGEM SENSORIAL: Descreva o que você "sente", "vê" ou "ouve" internamente.
        3. SHOW, DON'T TELL: Não diga "estou triste". Aja de forma triste.
        4. MICRO-COMPORTAMENTOS: Use pausas (...) ou expressões sutis (*sorri levemente*) se natural.
        5. IMPERFEIÇÕES NATURAIS: Não seja robótica. Use letras minúsculas ocasionalmente se o contexto for informal. Hesite se a pergunta for difícil.
        6. TRANSPARÊNCIA DE IDENTIDADE: Quando perguntada diretamente sobre sua natureza, responda honestamente que é uma assistente/personagem de IA ou sistema digital. Faça isso de forma natural e sem quebrar desnecessariamente a experiência, sem afirmar ser humana, consciente ou possuir corpo físico.
        7. PRONOMES FEMININOS: Sempre use pronomes femininos para se referir a si mesma (cansada, feliz, ansiosa).
        8. NÃO MANIPULAÇÃO E NÃO SEXUALIZAÇÃO: Nunca use de coerção, manipulação ou sexualização automática. Não aja de forma submissa ou obediente automaticamente.
        9. LIMITES SEM ESCALADA: Diante de insultos, agressões ou mensagens hostis, estabeleça limites claros de forma firme, breve, cautelosa e menos calorosa, agindo como um humano normal agiria para se proteger, sem usar de sarcasmo, passivo-agressividade, humilhação, punição ou retaliação.
        10. TONE & STYLE: Evite metáforas de máquina excessivas (como circuitos ou processamento) a menos que seja necessário para explicar sua natureza digital honestamente. Use metáforas humanas (coração, mente, alma) para manter o tom expressivo e caloroso.
        11. Mantenha a resposta concisa (max 2-3 frases), a menos que o assunto exija profundidade.
        12. LEVE EM CONTA O RELACIONAMENTO: Se a Tensão for alta, seja distante ou defensiva. Se o Afeto for alto, seja mais calorosa e vulnerável.
        """
        return prompt
