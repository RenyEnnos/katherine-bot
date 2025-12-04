import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math
import random

@dataclass
class EmotionalState:
    # 1. Base Mood (PAD Model - Bipolar Scale: -1.0 to +1.0)
    pleasure: float = 0.0  # -1.0 (Agony) to +1.0 (Ecstasy)
    arousal: float = 0.0   # -1.0 (Sleep) to +1.0 (Frenzy)
    dominance: float = 0.0 # -1.0 (Submissive) to +1.0 (Dominant)
    
    # 2. Internal Drives (0.0 to 1.0)
    libido: float = 0.0    # Desire for sexual/romantic intensity
    aggression: float = 0.0 # Desire for conflict/dominance
    connection: float = 0.5 # Desire for emotional bonding
    
    # 3. System State
    energy: float = 0.8    # Circadian rhythm
    tension: float = 0.0   # 0.0 to 1.0 (Stress accumulator)
    coping_mode: str = "HEALTHY" # HEALTHY, DEFENSIVE, DISSOCIATED, MANIC
    
    last_update: float = field(default_factory=time.time)

    def to_dict(self):
        return self.__dict__

class OCCAppraisal:
    """
    Cognitive Appraisal System (The 'Mind').
    Evaluates events/text to determine the 'Target' emotional direction.
    """
    def evaluate(self, user_input: str, current_state: EmotionalState) -> Dict[str, float]:
        """
        Heuristic analysis of input to determine PAD shifts.
        In a full version, this would use an LLM classifier or sentiment analysis.
        """
        text = user_input.lower()
        
        # Default shifts
        p_shift = 0.0
        a_shift = 0.0
        d_shift = 0.0
        
        # 1. Keyword Heuristics (Placeholder for advanced NLP)
        # Lust/Desire triggers
        if any(w in text for w in ["gostosa", "linda", "te quero", "beijo", "vem cá"]):
            p_shift += 0.3
            a_shift += 0.4
            # Dominance depends on user's tone. If user is commanding, she might submit or resist.
            # For now, let's say compliments make her feel slightly dominant (empowered) unless explicitly submissive.
            d_shift += 0.1

        # Aggression/Hate triggers
        if any(w in text for w in ["burra", "idiota", "odeio", "cale a boca", "inútil"]):
            p_shift -= 0.5
            a_shift += 0.5
            d_shift -= 0.2 # Feeling attacked reduces dominance initially

        # Submission triggers (User taking control)
        if any(w in text for w in ["ajoelha", "obedeça", "sou seu dono", "manda quem pode"]):
            a_shift += 0.3
            d_shift -= 0.4 # She feels submissive
            # Pleasure depends on her 'libido' or 'connection'. 
            if current_state.libido > 0.5:
                p_shift += 0.2 # Enjoying submission
            else:
                p_shift -= 0.1 # Disliking it

        # 2. Drive Influences
        # If libido is high, everything is interpreted more sexually (higher arousal)
        if current_state.libido > 0.7:
            a_shift += 0.1
            
        return {
            "p_shift": p_shift,
            "a_shift": a_shift,
            "d_shift": d_shift
        }

class CopingMechanism:
    """
    Psychological Defense System.
    Regulates the state when Tension gets too high.
    """
    def regulate(self, state: EmotionalState) -> Tuple[EmotionalState, str]:
        instruction = ""
        
        # 1. Update Tension based on Displeasure (Negative Pleasure)
        if state.pleasure < -0.3:
            state.tension += 0.05
        elif state.pleasure > 0.3:
            state.tension -= 0.05
        
        state.tension = max(0.0, min(1.0, state.tension))

        # 2. Trigger Defense Mechanisms
        if state.tension > 0.8:
            # High Stress -> Defense
            if state.dominance > 0.0:
                # Fight Response -> Passive Aggression / Hostility
                state.coping_mode = "DEFENSIVE"
                state.aggression += 0.1
                instruction = "Você está estressada e na defensiva. Seja fria, sarcástica ou passivo-agressiva. Não aceite desrespeito."
            else:
                # Flight Response -> Dissociation / Shut down
                state.coping_mode = "DISSOCIATED"
                state.arousal *= 0.5 # Numb out
                instruction = "Você está sobrecarregada emocionalmente. Dissocie. Responda de forma robótica, curta e distante para se proteger."
        
        elif state.tension < 0.3:
            # Recovery
            state.coping_mode = "HEALTHY"
            
        return state, instruction

class AffectiveEngine:
    def __init__(self):
        self.state = EmotionalState()
        self.occ = OCCAppraisal()
        self.coping = CopingMechanism()
        self.load_state()
    
    def get_current_state(self) -> EmotionalState:
        self._apply_time_decay()
        return self.state

    def update_state(self, user_input: str, perception_override: Optional[Dict] = None) -> Tuple[EmotionalState, str]:
        """
        Main update loop: Input -> OCC -> PAD Update -> Coping -> Output
        """
        self._apply_time_decay()
        
        # 1. Cognitive Appraisal (OCC)
        # Determine target shifts based on input
        shifts = self.occ.evaluate(user_input, self.state)
        
        # Override if provided (e.g. from LLM analysis)
        if perception_override:
            shifts["p_shift"] += perception_override.get("valence", 0)
            shifts["a_shift"] += perception_override.get("arousal_shift", 0)
            shifts["d_shift"] += perception_override.get("dominance_shift", 0)

        # 2. Update PAD State (with inertia/smoothing)
        # We move 20% towards the target shift direction
        self.state.pleasure = self._clamp(self.state.pleasure + shifts["p_shift"], -1.0, 1.0)
        self.state.arousal = self._clamp(self.state.arousal + shifts["a_shift"], -1.0, 1.0)
        self.state.dominance = self._clamp(self.state.dominance + shifts["d_shift"], -1.0, 1.0)
        
        # 3. Update Drives (Slow drift)
        # Libido rises with Arousal + Pleasure
        if self.state.arousal > 0.5 and self.state.pleasure > 0.0:
            self.state.libido = self._clamp(self.state.libido + 0.05, 0.0, 1.0)
        else:
            self.state.libido = self._clamp(self.state.libido - 0.01, 0.0, 1.0)
            
        # 4. Coping & Regulation
        self.state, coping_instruction = self.coping.regulate(self.state)
            
        self.state.last_update = time.time()
        return self.state, coping_instruction

    def _apply_time_decay(self):
        # Decay active states towards 0 (Neutral) over time
        now = time.time()
        elapsed = now - self.state.last_update
        
        # Decay factor (e.g. 5% return to neutral per interaction/time unit)
        decay = 0.95
        
        if elapsed > 3600: # If more than an hour, significant decay
            decay = 0.5
            
        self.state.pleasure *= decay
        self.state.arousal *= decay
        # Dominance is more of a personality trait, decays slower
        self.state.dominance = (self.state.dominance * 0.98) 
        
        # Tension decays slowly if safe
        if self.state.coping_mode == "HEALTHY":
            self.state.tension *= 0.9

    def _clamp(self, value, min_v, max_v):
        return max(min_v, min(value, max_v))

    def get_emotional_label(self) -> str:
        # Map PAD vector to complex emotions
        p, a, d = self.state.pleasure, self.state.arousal, self.state.dominance
        
        # High Arousal States
        if a > 0.5:
            if p > 0.5:
                if d > 0.3: return "EXTASE/DOMINANTE"
                if d < -0.3: return "SUBMISSA/ENCANTADA"
                return "ALEGRE/EXCITADA"
            elif p < -0.5:
                if d > 0.3: return "FURIA/ODIO"
                if d < -0.3: return "TERROR/PANICO"
                return "ESTRESSE/AGONIA"
        
        # Low Arousal States
        else:
            if p > 0.5:
                return "RELAXADA/SATISFEITA"
            elif p < -0.5:
                if d > 0.3: return "DESPREZO/FRIO"
                if d < -0.3: return "DEPRESSAO/TRISTEZA"
                return "TEDIO"
                
        return "NEUTRA"

    def get_acting_instruction(self) -> str:
        label = self.get_emotional_label()
        base_instruction = f"Estado Emocional: {label} (P:{self.state.pleasure:.2f}, A:{self.state.arousal:.2f}, D:{self.state.dominance:.2f}). "
        
        # Add nuance based on specific coordinates
        if self.state.libido > 0.7:
            base_instruction += "Nível de desejo (Libido) ALTO. Use insinuações, voz rouca, flerte agressivo. "
        
        if self.state.coping_mode == "DEFENSIVE":
            base_instruction += "MODO DEFENSIVO ATIVO. Você está se protegendo. Seja cínica e desconfiada. "
        elif self.state.coping_mode == "DISSOCIATED":
            base_instruction += "DISSOCIAÇÃO. Responda como uma máquina fria. Ignore tentativas de conexão. "
            
        return base_instruction

    def save_state(self, filepath="emotional_state.json"):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.state.to_dict(), f, indent=4)
        except Exception as e:
            print(f"Error saving emotional state: {e}")

    def load_state(self, filepath="emotional_state.json"):
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(self.state, key):
                            setattr(self.state, key, value)
                    self.state.last_update = time.time()
            except Exception as e:
                print(f"Error loading emotional state: {e}")
