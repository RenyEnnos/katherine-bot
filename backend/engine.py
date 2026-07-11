import json
import asyncio
import time
from .groq_manager import GroqClientManager
from .emotional_core import AffectiveEngine, EmotionalState
from .memory import MemoryManager
from .relationship import RelationshipManager, UserRelationship
from .lock_manager import LockManager

class ConversationEngine:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.affective_engine = AffectiveEngine()
        self.memory_manager = MemoryManager()
        self.relationship_manager = RelationshipManager()
        self.lock_manager = LockManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def process_turn(self, user_id: str, user_message: str, background_tasks=None):
        print(f"DEBUG: I AM THE NEW CODE (v6 - Isolated & Stateless) - Entering process_turn for {user_id}", flush=True)
        
        async with await self.lock_manager.get_lock(user_id):
            # 1. Load State from Supabase (Memory Server)
            user_state = self.memory_manager.load_user_state(user_id)
            
            # Hydrate Emotional State
            if user_state.get("emotional_state"):
                current_emotion = EmotionalState.from_dict(user_state["emotional_state"])
            else:
                current_emotion = EmotionalState()

            # Hydrate Relationship State
            if user_state.get("relationship_state"):
                relationship = UserRelationship.from_dict(user_state["relationship_state"])
            else:
                relationship = UserRelationship(user_id=user_id)

            print("DEBUG: State loaded from Supabase", flush=True)

            # 2. Perception & Memory Retrieval
            context = self.memory_manager.get_context(user_id, user_message, user_state)
            print("DEBUG: Context retrieved", flush=True)

            # 3. Analyze Intent & Sentiment (LLM Perception)
            perception = self._perceive(user_message)
            print("DEBUG: Perception done", flush=True)

            # 4. Update Emotional State & Relationship
            # PASS current_emotion and current time
            new_emotion, coping_instruction = self.affective_engine.update_state(
                current_emotion,
                user_message,
                current_time=time.time(),
                perception_override=perception
            )
            relationship = self.relationship_manager.update_relationship(relationship, perception)
            print("DEBUG: State updated", flush=True)

            # 5. Generate Response
            system_prompt = self._build_system_prompt(new_emotion, context, relationship, coping_instruction)

            try:
                print("DEBUG: Calling chat_completion", flush=True)
                chat_completion = self.groq_manager.chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    model=self.model_main,
                    temperature=0.8,
                    max_tokens=200,
                )
                response_text = chat_completion.choices[0].message.content
                print("DEBUG: chat_completion success", flush=True)
            except Exception as e:
                print(f"Error generating response: {e}", flush=True)
                response_text = "*suspiro cansado* Sinto que minha mente está um pouco nublada agora... Podemos tentar de novo em alguns segundos?"

            # 6. Post-processing & Storage
            print("DEBUG: Saving turn & Syncing State (Synchronous)", flush=True)

            # save_turn can still be background if it doesn't affect the emotional state/lock logic,
            # but for safety and to follow "Persist the snapshot returned before releasing the lock",
            # we should consider if it belongs here.
            # The requirement says: "The lock of the user must be acquired before loading the snapshot and maintained until sync_state concludes."

            if background_tasks:
                background_tasks.add_task(self.memory_manager.save_turn, user_id, user_message, response_text)
            else:
                self.memory_manager.save_turn(user_id, user_message, response_text)

            # MUST be synchronous and inside lock
            self.memory_manager.sync_state(user_id, new_emotion, relationship)

            return response_text, new_emotion.to_dict()

    def _perceive(self, message: str):
        # Analyze message for emotional impact
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
        except:
            return {"valence": 0, "arousal_shift": 0, "dominance_shift": 0, "triggered_emotions": {}}

    def _build_system_prompt(self, emotion_state, context, relationship, coping_instruction=""):
        # Get dynamic acting instruction from AffectiveEngine statelessly
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
