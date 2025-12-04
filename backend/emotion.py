class EmotionalStateManager:
    def __init__(self):
        # In a real app, this would load from a DB. For now, in-memory dict.
        self.states = {} 

    def get_state(self, user_id: str):
        if user_id not in self.states:
            self.states[user_id] = {
                "pleasure": 0.5,
                "arousal": 0.5,
                "dominance": 0.5,
                "mood_label": "Calma",
                "acting_instruction": "Seja receptiva e tranquila."
            }
        return self.states[user_id]

    def update_state(self, user_id: str, perception: dict):
        current = self.get_state(user_id)
        
        # Simple PAD dynamics based on perception
        # Sentiment affects Pleasure
        if perception['sentiment'] == 'positive':
            current['pleasure'] = min(1.0, current['pleasure'] + 0.1 * perception['intensity'])
        elif perception['sentiment'] == 'negative':
            current['pleasure'] = max(0.0, current['pleasure'] - 0.1 * perception['intensity'])
            
        # Intent affects Arousal/Dominance
        if perception['intent'] in ['question', 'vent']:
            # Engagement goes up
            current['arousal'] = min(1.0, current['arousal'] + 0.05)
        elif perception['intent'] == 'joke':
            current['pleasure'] = min(1.0, current['pleasure'] + 0.15)
            current['arousal'] = min(1.0, current['arousal'] + 0.1)

        # Decay (return to neutral over time) - simplified here
        # current['arousal'] = current['arousal'] * 0.95
        
        # Derive Label
        current['mood_label'] = self._derive_label(current['pleasure'], current['arousal'])
        current['acting_instruction'] = self._derive_instruction(current['mood_label'])
        
        self.states[user_id] = current
        return current

    def _derive_label(self, p, a):
        if p > 0.7 and a > 0.6: return "Entusiasmada"
        if p > 0.7 and a <= 0.6: return "Feliz/Relaxada"
        if p < 0.4 and a > 0.6: return "Irritada/Ansiosa"
        if p < 0.4 and a <= 0.4: return "Triste/Melancólica"
        return "Neutra/Atenta"

    def _derive_instruction(self, label):
        instructions = {
            "Entusiasmada": "Use exclamações! Mostre energia. Seja contagiante.",
            "Feliz/Relaxada": "Seja doce e calma. Use emojis suaves.",
            "Irritada/Ansiosa": "Seja curta e um pouco defensiva, mas sem ser rude.",
            "Triste/Melancólica": "Fale menos. Mostre empatia mas com tom baixo.",
            "Neutra/Atenta": "Seja objetiva e prestativa. Oça atentamente."
        }
        return instructions.get(label, "Aja normalmente.")
