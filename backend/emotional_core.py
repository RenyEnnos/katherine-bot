import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import math

@dataclass
class EmotionalState:
    # 1. Base Mood (PAD Model - Slow changing)
    pleasure: float = 0.5  # 0.0 to 1.0
    arousal: float = 0.5   # 0.0 to 1.0
    dominance: float = 0.5 # 0.0 to 1.0
    
    # 2. Active Emotions (Discrete - Fast changing)
    # Basic
    joy: float = 0.0
    sadness: float = 0.0
    anger: float = 0.0
    fear: float = 0.0
    disgust: float = 0.0
    surprise: float = 0.0
    
    # Social/Moral
    guilt: float = 0.0
    pride: float = 0.0
    tenderness: float = 0.0
    jealousy: float = 0.0
    gratitude: float = 0.0
    
    # 3. Internal State
    energy: float = 0.8 # Circadian rhythm affects this
    tension: float = 0.0 # Accumulates with negative interactions
    
    last_update: float = field(default_factory=time.time)

    def to_dict(self):
        return self.__dict__

class AffectiveEngine:
    def __init__(self):
        self.state = EmotionalState()
        self.decay_rate = 0.05 # Rate at which active emotions return to 0 per turn/time unit
    
    def get_current_state(self) -> EmotionalState:
        self._apply_time_decay()
        self._apply_circadian_rhythm()
        return self.state

    def update_state(self, perception: Dict) -> EmotionalState:
        """
        Updates state based on perception input:
        {
            "valence": -1.0 to 1.0,
            "arousal_shift": -1.0 to 1.0,
            "dominance_shift": -1.0 to 1.0,
            "triggered_emotions": {"joy": 0.5, "anger": 0.2, ...}
        }
        """
        # Update Base Mood (PAD) - with inertia
        self.state.pleasure = self._clamp(self.state.pleasure + (perception.get("valence", 0) * 0.1))
        self.state.arousal = self._clamp(self.state.arousal + (perception.get("arousal_shift", 0) * 0.1))
        self.state.dominance = self._clamp(self.state.dominance + (perception.get("dominance_shift", 0) * 0.1))
        
        # Update Active Emotions
        triggered = perception.get("triggered_emotions", {})
        for emotion, intensity in triggered.items():
            if hasattr(self.state, emotion):
                current = getattr(self.state, emotion)
                setattr(self.state, emotion, self._clamp(current + intensity))
                
        # Update Tension
        if perception.get("valence", 0) < -0.3:
            self.state.tension = self._clamp(self.state.tension + 0.1)
        elif perception.get("valence", 0) > 0.3:
            self.state.tension = self._clamp(self.state.tension - 0.1)
            
        self.state.last_update = time.time()
        return self.state

    def _apply_time_decay(self):
        # Simple linear decay for active emotions towards 0
        now = time.time()
        elapsed = now - self.state.last_update
        # Assume 1 unit of decay per hour, scaled to seconds for demo? 
        # For chat, we might decay per turn, but let's use elapsed time slightly.
        # Let's just decay active emotions by a factor.
        
        decay_factor = 0.95 # Retain 95% of emotion per call if frequent, or calculate properly.
        # For simplicity in this prototype, we just multiply.
        
        active_emotions = [
            "joy", "sadness", "anger", "fear", "disgust", "surprise",
            "guilt", "pride", "tenderness", "jealousy", "gratitude"
        ]
        
        for emo in active_emotions:
            val = getattr(self.state, emo)
            if val > 0.01:
                setattr(self.state, emo, val * decay_factor)
            else:
                setattr(self.state, emo, 0.0)

    def _apply_circadian_rhythm(self):
        hour = datetime.now().hour
        # Energy is high in morning (8-12), dips post-lunch (13-15), rises evening (16-20), drops night.
        if 6 <= hour < 12:
            target_energy = 0.9
        elif 12 <= hour < 15:
            target_energy = 0.6
        elif 15 <= hour < 22:
            target_energy = 0.8
        else:
            target_energy = 0.3
            
        # Smooth transition
        self.state.energy = (self.state.energy * 0.8) + (target_energy * 0.2)

    def _clamp(self, value, min_v=0.0, max_v=1.0):
        return max(min_v, min(value, max_v))

    def get_emotional_label(self) -> str:
        # Determine dominant emotion
        emotions = {
            "joy": self.state.joy,
            "sadness": self.state.sadness,
            "anger": self.state.anger,
            "fear": self.state.fear,
            "tenderness": self.state.tenderness
        }
        dominant = max(emotions, key=emotions.get)
        if emotions[dominant] > 0.3:
            return dominant.upper()
        
        # Fallback to PAD mood
        if self.state.pleasure > 0.6: return "CONTENTE"
        if self.state.pleasure < 0.4: return "MELANCOLICA"
        return "NEUTRA"

    def get_acting_instruction(self) -> str:
        label = self.get_emotional_label()
        if label == "JOY":
            return "Sorria na voz. Use exclamações. Seja expansiva."
        elif label == "SADNESS":
            return "Fale mais devagar. Use frases curtas. Mostre vulnerabilidade."
        elif label == "ANGER":
            return "Seja seca e direta. Evite emojis fofos."
        elif label == "TENDERNESS":
            return "Use diminutivos. Fale com carinho. Mostre proteção."
        else:
            return "Mantenha-se calma e atenta."
