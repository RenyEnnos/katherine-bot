import json
import asyncio
import time
import logging
from typing import Optional
from fastapi import BackgroundTasks
from .groq_manager import GroqClientManager
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
from .memory import MemoryManager
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

logger = logging.getLogger(__name__)

class ConversationEngine:
    def __init__(self, clock=time.time):
        self._clock = clock
        self.groq_manager = GroqClientManager()
        self.presentation = AffectiveEngine()  # read-only presentation helpers
        self.transition_config = TransitionConfig.defaults()  # immutable, stateless
        self.memory_manager = MemoryManager(clock=clock)
        self.relationship_config = RelationshipTransitionConfig.defaults()
        self.lock_manager = UserLockManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def run_archival_extraction(self, turn_ref: PersistedTurnRef):
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

    async def process_turn(self, user_id: str, user_message: str, background_tasks: Optional[BackgroundTasks] = None):
        async def run_under_lock():
            current_time = self._clock()

            # 1. Load State from Supabase (Offloaded to thread)
            # Raises StateLoadError on DB failure
            user_state = await asyncio.to_thread(self.memory_manager.load_user_state, user_id)

            # Migration boundary: legacy or v1 snapshot → EmotionalStateV1
            raw_emotional_state = user_state.get("emotional_state", {})
            emotional_state = migrate_legacy_snapshot(raw_emotional_state)

            # Hydrate Relationship State - Enforce authenticated user_id
            # Identity comes from the authenticated user_id passed to load_user_state
            rel_data = user_state.get("relationship_state")
            if rel_data:
                relationship = migrate_legacy_relationship_snapshot(rel_data)
            else:
                relationship = RelationshipStateV1.neutral(timestamp=current_time)

            # 2. Perception & Memory Retrieval
            context = await asyncio.to_thread(self.memory_manager.get_context, user_id, user_message, user_state)

            # 3. Analyze Intent & Sentiment (LLM Perception)
            raw_perception = await asyncio.to_thread(self._perceive, user_message)

            # Parse raw LLM output into a validated AppraisalV1 (may be neutral fallback)
            parse_result = parse_llm_appraisal(raw_perception)
            appraisal = parse_result.appraisal

            # Observability: log sanitised fallback code without raw payload
            if parse_result.is_fallback:
                logger.info(
                    f"event=emotional_appraisal_fallback code={parse_result.error_code.value}"
                )

            # 4. Update Emotional State & Relationship (Local computations)
            # Exactly one transition call per successful turn
            transition_result = transition(
                previous_state=emotional_state,
                appraisal=appraisal,
                current_time=current_time,
                config=self.transition_config,
            )
            new_state = transition_result.state

            # Feed relationship from validated AppraisalV1 directly
            relationship = transition_relationship(
                previous_state=relationship,
                appraisal=appraisal,
                current_time=current_time,
                config=self.relationship_config,
            )

            # 5. Meta-Cognition: DEACTIVATED as per P0 instructions
            adaptation_strategy = ""

            # 6. Generate Response (LLM call offloaded to thread)
            system_prompt = self._build_system_prompt(new_state, context, relationship, adaptation_strategy)

            try:
                chat_completion = await asyncio.to_thread(
                    self.groq_manager.chat_completion,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    model=self.model_main,
                    temperature=0.8,
                    max_tokens=200,
                )
                response_text = chat_completion.choices[0].message.content
            except Exception:
                response_text = "*suspiro cansado* Sinto que minha mente está um pouco nublada agora... Podemos tentar de novo em alguns segundos?"

            # 7. Post-processing & Storage (Offloaded to thread)
            # Await critical turn persistence synchronously inside the lock (do not use BackgroundTasks)
            turn_ref = await asyncio.to_thread(self.memory_manager.save_turn, user_id, user_message, response_text)

            # CRITICAL: sync_state MUST complete before releasing lock.
            # Persist v1 emotional state via .to_dict() (JSONB column expects a dict, not a JSON string).
            # Raises StatePersistenceError on failure.
            await asyncio.to_thread(self.memory_manager.sync_state, user_id, new_state, relationship)

            # Schedule background task only after save_turn and sync_state have successfully completed
            if background_tasks:
                background_tasks.add_task(self.run_archival_extraction, turn_ref)

            # Return projected public format (typed DTO, no internal fields)
            return response_text, self._project_emotion_state(new_state, appraisal)

        async with self.lock_manager.lock(user_id):
            task = asyncio.create_task(run_under_lock())
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # If we get CancelledError, the caller cancelled process_turn.
                # We must wait for task to complete, shielding it even against subsequent cancellations.
                while not task.done():
                    try:
                        # Shield the task again to prevent cancellations from stopping this await
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        # A second/subsequent cancel arrived. Consume it, but keep waiting until task is done.
                        pass
                    except Exception:
                        # Other exceptions from the task are caught and ignored here because we want to propagate CancelledError
                        break
                raise


    def _perceive(self, message: str):
        # Analyze message for emotional impact (Synchronous Groq call)
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
            completion = self.groq_manager.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                temperature=0,
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception:
            return {}

    def _build_system_prompt(self, emotion_state: EmotionalStateV1, context, relationship, adaptation_strategy=""):
        acting_instruction = self.presentation.get_acting_instruction(emotion_state)
        mood_label = self.presentation.get_emotional_label(emotion_state)

        # Regulation effects (coping instruction) are no longer produced by
        # the emotional transition — the emotion prompt directives handle this.
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
