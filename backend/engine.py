import json
import asyncio
from .groq_manager import GroqClientManager
from .emotional_core import AffectiveEngine
from .memory import MemoryManager
from .meta_cognition import MetaCognition

class ConversationEngine:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.affective_engine = AffectiveEngine()
        self.memory_manager = MemoryManager()
        self.meta_cognition = MetaCognition()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"
        
        self.turn_count = 0

    async def process_turn(self, user_id: str, user_message: str):
        self.turn_count += 1
        
        # 1. Perception & Memory Retrieval
        context = self.memory_manager.get_context(user_id, user_message)
        
        # 2. Analyze Intent & Sentiment
        perception = self._perceive(user_message)
        
        # 3. Update Emotional State
        new_state = self.affective_engine.update_state(perception)
        
        # 4. Meta-Cognition (Periodic Check)
        adaptation_strategy = ""
        if self.turn_count % 3 == 0: # Check every 3 turns
            # Get recent history from memory
            history = self.memory_manager.short_term_memory.get(user_id, [])
            history_str = str(history[-5:])
            
            # Run analysis in background (simulated here as blocking for simplicity, but fast)
            analysis = self.meta_cognition.analyze_user_style(history_str)
            adaptation_strategy = analysis.get("suggested_adaptation", "")
            
            # Update Core Memory with profile
            self.memory_manager.core_memory.update_user_profile(analysis)
        
        # 5. Generate Response
        system_prompt = self._build_system_prompt(new_state, context, adaptation_strategy)
        
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
        
        # 6. Post-processing & Storage
        self.memory_manager.save_turn(user_id, user_message, response_text)
        
        return response_text, new_state.to_dict()

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

    def _build_system_prompt(self, emotion_state, context, adaptation_strategy=""):
        # Get dynamic acting instruction
        acting_instruction = self.affective_engine.get_acting_instruction()
        mood_label = self.affective_engine.get_emotional_label()
        
        prompt = f"""
        {context}
        
        === SEU ESTADO INTERNO AGORA ===
        HUMOR: {mood_label}
        Energia: {emotion_state.energy:.2f} | Tensão: {emotion_state.tension:.2f}
        Emoções Ativas: Joy={emotion_state.joy:.2f}, Sadness={emotion_state.sadness:.2f}, Anger={emotion_state.anger:.2f}, Fear={emotion_state.fear:.2f}, Disgust={emotion_state.disgust:.2f}, Guilt={emotion_state.guilt:.2f}, Jealousy={emotion_state.jealousy:.2f}
        
        === INSTRUÇÃO DE ATUAÇÃO (IMPORTANTE) ===
        {acting_instruction}
        
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
        """
        return prompt
