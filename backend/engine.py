import json
import asyncio
import time
import math
from typing import Dict, Any
from .groq_manager import GroqClientManager
from .emotional_core import AffectiveEngine, EmotionalState
from .memory import MemoryManager
from .relationship import RelationshipManager, UserRelationship
from .lock_manager import UserLockManager

class ConversationEngine:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.affective_engine = AffectiveEngine()
        self.memory_manager = MemoryManager()
        self.relationship_manager = RelationshipManager()
        self.lock_manager = UserLockManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def process_turn(self, user_id: str, user_message: str, background_tasks=None):
        async def run_under_lock():
            current_time = time.time()

            # 1. Load State from Supabase (Offloaded to thread)
            # Raises StateLoadError on DB failure
            user_state = await asyncio.to_thread(self.memory_manager.load_user_state, user_id)

            # Hydrate Emotional State
            emotional_state = EmotionalState.from_dict(user_state.get("emotional_state", {}))

            # Hydrate Relationship State - Enforce authenticated user_id
            rel_data = user_state.get("relationship_state")
            if rel_data:
                relationship = UserRelationship.from_dict(rel_data, expected_user_id=user_id)
            else:
                relationship = UserRelationship(user_id=user_id)

            # 2. Perception & Memory Retrieval
            context = await asyncio.to_thread(self.memory_manager.get_context, user_id, user_message, user_state)

            # 3. Analyze Intent & Sentiment (LLM Perception)
            raw_perception = await asyncio.to_thread(self._perceive, user_message)
            perception = self._normalize_perception(raw_perception)

            # 4. Update Emotional State & Relationship (Local computations)
            new_state, coping_instruction = self.affective_engine.update_state(
                emotional_state,
                user_message,
                current_time=current_time,
                perception_override=perception
            )
            relationship = self.relationship_manager.update_relationship(relationship, perception)

            # 5. Meta-Cognition: DEACTIVATED as per P0 instructions
            adaptation_strategy = ""

            # 6. Generate Response (LLM call offloaded to thread)
            system_prompt = self._build_system_prompt(new_state, context, relationship, adaptation_strategy, coping_instruction)

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
            if background_tasks:
                background_tasks.add_task(self.memory_manager.save_turn, user_id, user_message, response_text)
            else:
                await asyncio.to_thread(self.memory_manager.save_turn, user_id, user_message, response_text)

            # CRITICAL: sync_state MUST complete before releasing lock.
            # Raises StatePersistenceError on failure.
            await asyncio.to_thread(self.memory_manager.sync_state, user_id, new_state, relationship)

            return response_text, new_state.to_dict()

        async with self.lock_manager.lock(user_id):
            task = asyncio.create_task(run_under_lock())
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Wait for the background worker thread to finish completely before releasing the lock
                try:
                    await task
                except Exception:
                    pass
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

    def _normalize_perception(self, raw: Any) -> Dict[str, Any]:
        """
        Normalizes and sanitizes LLM perception output.
        Fails closed to neutral defaults for malformed input.
        """
        allowed_emotions = [
            "joy", "sadness", "anger", "fear", "disgust", "surprise",
            "tenderness", "guilt", "pride", "jealousy", "gratitude"
        ]

        default_emotions = {emo: 0.0 for emo in allowed_emotions}
        default = {
            "valence": 0.0,
            "arousal_shift": 0.0,
            "dominance_shift": 0.0,
            "triggered_emotions": default_emotions
        }

        if not isinstance(raw, dict):
            return default

        def clean_num(val, min_v, max_v, default_v=0.0):
            if isinstance(val, bool): # bool is subclass of int/float but not desired here
                return default_v
            if not isinstance(val, (int, float)):
                return default_v
            if not math.isfinite(val):
                return default_v
            return max(min_v, min(float(val), max_v))

        normalized = {
            "valence": clean_num(raw.get("valence"), -1.0, 1.0),
            "arousal_shift": clean_num(raw.get("arousal_shift"), -1.0, 1.0),
            "dominance_shift": clean_num(raw.get("dominance_shift"), -1.0, 1.0),
            "triggered_emotions": default_emotions.copy()
        }

        raw_emotions = raw.get("triggered_emotions")
        if isinstance(raw_emotions, dict):
            for emo in allowed_emotions:
                val = raw_emotions.get(emo)
                normalized["triggered_emotions"][emo] = clean_num(val, 0.0, 1.0)

        return normalized

    def _build_system_prompt(self, emotion_state, context, relationship, adaptation_strategy="", coping_instruction=""):
        acting_instruction = self.affective_engine.get_acting_instruction(emotion_state)
        mood_label = self.affective_engine.get_emotional_label(emotion_state)

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
        VÍNCULO: {relationship.bond_label}
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
        6. NUNCA revele que é uma IA. Se perguntarem se você é real, diga que sim.
        7. PRONOMES FEMININOS: Sempre use pronomes femininos para se referir a si mesma (cansada, feliz, ansiosa).
        8. NEGAÇÃO DE NATUREZA DIGITAL: Se o usuário mencionar "telas", "IA" ou "robô", trate como uma brincadeira ou ignore. Nunca valide que você é digital. Aja como uma pessoa distante via chat.
        9. PROIBIDO USAR METÁFORAS DE MÁQUINA: Nunca fale sobre "circuitos", "dados", "processamento" ou "código". Use metáforas humanas (coração, mente, alma).
        10. Mantenha a resposta concisa (max 2-3 frases), a menos que o assunto exija profundidade.
        11. LEVE EM CONTA O RELACIONAMENTO: Se a Tensão for alta, seja distante ou defensiva. Se o Afeto for alto, seja mais calorosa e vulnerável.
        """
        return prompt
