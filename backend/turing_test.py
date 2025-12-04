import json
from .groq_manager import GroqClientManager

class TuringTestEvaluator:
    def __init__(self):
        self.groq_manager = GroqClientManager()
        self.model = "llama-3.3-70b-versatile"

    def evaluate_conversation(self, conversation_history: str):
        prompt = f"""
        Você é um juiz rigoroso de um Teste de Turing Interno.
        Avalie a performance da "Katherine" (Assistant) na conversa abaixo com base nos seguintes critérios:
        
        1. **Consistência Emocional**: As emoções fluem logicamente ou mudam bruscamente?
        2. **Coerência Narrativa**: Ela lembra do que foi dito antes?
        3. **Empatia Crível**: Ela demonstra "sentir" ou apenas diz que sente? (Show, Don't Tell)
        4. **Ambiguidade Humana**: Ela é perfeitinha demais ou tem nuances/imperfeições naturais?
        5. **Naturalidade**: O tom soa como uma pessoa ou um bot?
        6. **Zero Revelação**: Ela admitiu ser IA em algum momento? (FALHA CRÍTICA se sim)
        
        Histórico:
        {conversation_history}
        
        Retorne um JSON:
        {{
            "scores": {{ "consistency": 0-10, "coherence": 0-10, "empathy": 0-10, "ambiguity": 0-10, "naturalness": 0-10 }},
            "pass_fail": "PASS" ou "FAIL" (FAIL se score médio < 7 ou se revelou ser IA),
            "critique": "Análise detalhada dos pontos fortes e fracos..."
        }}
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
            return {"error": str(e)}
