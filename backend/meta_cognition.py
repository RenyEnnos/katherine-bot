import json
from .groq_manager import GroqClientManager

class MetaCognition:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.model = "llama-3.1-8b-instant" # Fast model is sufficient for meta-analysis

    def analyze_user_style(self, history_str: str) -> dict:
        """
        Analyzes the user's communication style and emotional patterns.
        """
        prompt = f"""
        Analise o estilo de comunicação do USUÁRIO neste histórico.
        
        Retorne JSON:
        {{
            "emotional_style": "Ansioso / Lógico / Sarcástico / Carente / Agressivo / Neutro",
            "communication_traits": ["curto", "detalhado", "usa emojis", "formal", "gírias"],
            "suggested_adaptation": "Seja mais acolhedora / Seja mais direta / Use humor / Mantenha a calma"
        }}
        
        Histórico:
        {history_str}
        """
        
        try:
            completion = self.groq_manager.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"}
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"MetaCognition Error (User Style): {e}")
            return {"emotional_style": "Neutro", "suggested_adaptation": "Seja natural"}

    def reflect_on_performance(self, history_str: str, last_bot_response: str) -> str:
        """
        Katherine reflects on her own recent performance.
        """
        prompt = f"""
        Você é a "Consciência" da Katherine. Analise a última resposta dela.
        
        Última resposta: "{last_bot_response}"
        Contexto recente:
        {history_str}
        
        Critique:
        1. Ela foi empática o suficiente?
        2. Ela entendeu o subtexto?
        3. Ela soou robótica?
        
        Se houver falhas, gere um "Pensamento Corretivo" para a próxima vez. Se estiver bom, retorne null.
        
        Retorne JSON: {{ "critique": "...", "correction": "Na próxima vez, tente..." ou null }}
        """
        
        try:
            completion = self.groq_manager.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"}
            )
            data = json.loads(completion.choices[0].message.content)
            return data.get("correction")
        except Exception as e:
            print(f"MetaCognition Error (Reflection): {e}")
            return None
