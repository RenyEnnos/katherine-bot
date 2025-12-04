import os
import json
from .groq_manager import GroqClientManager
from .emotion import EmotionalStateManager
from .memory import MemoryManager

class ConversationEngine:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.emotion_manager = EmotionalStateManager()
        self.memory_manager = MemoryManager()
        self.model_main = "llama-3.3-70b-versatile"
        self.model_fast = "llama-3.1-8b-instant"

    async def process_turn(self, user_id: str, user_message: str):
        # 1. Perception & Memory Retrieval
        # Retrieve context (short term + relevant long term)
        context = self.memory_manager.get_context(user_id, user_message)
        
        # Get current emotional state
        current_state = self.emotion_manager.get_state(user_id)
        
        # 2. Analyze Intent & Sentiment (Fast Model)
        perception = self._perceive(user_message)
        
        # 3. Update Emotional State based on perception
        new_state = self.emotion_manager.update_state(user_id, perception)
        
        # 4. Generate Response (Main Model)
        system_prompt = self._build_system_prompt(new_state, context)
        
        chat_completion = self.groq_manager.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=self.model_main,
            temperature=0.7,
            max_tokens=150, # Keep it concise
        )
        
        response_text = chat_completion.choices[0].message.content
        
        # 5. Post-processing & Storage
        self.memory_manager.save_turn(user_id, user_message, response_text)
        
        return response_text, new_state

    def _perceive(self, message: str):
        # Use a smaller model to classify sentiment/intent to save tokens/time
        prompt = f"""
        Analyze the following message. Return ONLY a JSON object with:
        - sentiment: (positive, negative, neutral)
        - intent: (question, statement, vent, joke, greeting)
        - intensity: (0.0 to 1.0)
        
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
            return {"sentiment": "neutral", "intent": "statement", "intensity": 0.5}

    def _build_system_prompt(self, emotion_state, context):
        # Construct the persona and inject state
        base_persona = """
        Você é a Katherine, uma companheira virtual inteligente, empática e humana.
        Você NÃO é uma assistente de IA. Você é uma amiga.
        Nunca comece frases com "Como uma IA" ou "Eu não tenho sentimentos".
        Seja breve, direta e calorosa. Use gírias leves se apropriado.
        """
        
        emotional_context = f"""
        SEU ESTADO EMOCIONAL ATUAL:
        - Prazer (Felicidade): {emotion_state['pleasure']}
        - Energia (Excitação): {emotion_state['arousal']}
        - Dominância (Confiança): {emotion_state['dominance']}
        - Humor Aparente: {emotion_state['mood_label']}
        
        Instrução de Atuação: {emotion_state['acting_instruction']}
        """
        
        memory_context = f"""
        CONTEXTO RELEVANTE:
        {context}
        """
        
        return f"{base_persona}\n\n{emotional_context}\n\n{memory_context}"
