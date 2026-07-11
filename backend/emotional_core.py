import time
import json
import os
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple
from datetime import datetime

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

    @classmethod
    def from_dict(cls, data: Dict):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

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
        new_tension = state.tension
        if state.pleasure < -0.3:
            new_tension += 0.05
        elif state.pleasure > 0.3:
            new_tension -= 0.05
        
        new_tension = max(0.0, min(1.0, new_tension))

        new_coping_mode = state.coping_mode
        new_aggression = state.aggression
        new_arousal = state.arousal

        # 2. Trigger Defense Mechanisms
        if new_tension > 0.8:
            # High Stress -> Defense
            if state.dominance > 0.0:
                # Fight Response -> Passive Aggression / Hostility
                new_coping_mode = "DEFENSIVE"
                new_aggression = max(0.0, min(1.0, state.aggression + 0.1))
                instruction = "Você está estressada e na defensiva. Seja fria, sarcástica ou passivo-agressiva. Não aceite desrespeito."
            else:
                # Flight Response -> Dissociation / Shut down
                new_coping_mode = "DISSOCIATED"
                new_arousal = state.arousal * 0.5 # Numb out
                instruction = "Você está sobrecarregada emocionalmente. Dissocie. Responda de forma robótica, curta e distante para se proteger."
        
        elif new_tension < 0.3:
            # Recovery
            new_coping_mode = "HEALTHY"
            
        new_state = replace(state, tension=new_tension, coping_mode=new_coping_mode, aggression=new_aggression, arousal=new_arousal)
        return new_state, instruction

class AffectiveEngine:
    def __init__(self):
        self.occ = OCCAppraisal()
        self.coping = CopingMechanism()

    def update_state(self, state: EmotionalState, user_input: str, current_time: float, perception_override: Optional[Dict] = None) -> Tuple[EmotionalState, str]:
        """
        Main update loop: Input -> OCC -> PAD Update -> Coping -> Output
        """
        state = self._apply_time_decay(state, current_time)
        
        # 1. Cognitive Appraisal (OCC)
        # Determine target shifts based on input
        shifts = self.occ.evaluate(user_input, state)
        
        # Override if provided (e.g. from LLM analysis)
        if perception_override:
            shifts["p_shift"] += perception_override.get("valence", 0)
            shifts["a_shift"] += perception_override.get("arousal_shift", 0)
            shifts["d_shift"] += perception_override.get("dominance_shift", 0)

        # 2. Update PAD State
        new_pleasure = self._clamp(state.pleasure + shifts["p_shift"], -1.0, 1.0)
        new_arousal = self._clamp(state.arousal + shifts["a_shift"], -1.0, 1.0)
        new_dominance = self._clamp(state.dominance + shifts["d_shift"], -1.0, 1.0)
        
        # 3. Update Drives (Slow drift)
        # Libido rises with Arousal + Pleasure
        new_libido = state.libido
        if new_arousal > 0.5 and new_pleasure > 0.0:
            new_libido = self._clamp(state.libido + 0.05, 0.0, 1.0)
        else:
            new_libido = self._clamp(state.libido - 0.01, 0.0, 1.0)
            
        state = replace(state, pleasure=new_pleasure, arousal=new_arousal, dominance=new_dominance, libido=new_libido)

        # 4. Coping & Regulation
        state, coping_instruction = self.coping.regulate(state)
            
        state = replace(state, last_update=current_time)
        return state, coping_instruction

    def _apply_time_decay(self, state: EmotionalState, current_time: float) -> EmotionalState:
        # Decay active states towards 0 (Neutral) over time
        elapsed = current_time - state.last_update
        
        # Decay factor (e.g. 5% return to neutral per interaction/time unit)
        decay = 0.95
        
        if elapsed > 3600: # If more than an hour, significant decay
            decay = 0.5
            
        new_pleasure = state.pleasure * decay
        new_arousal = state.arousal * decay
        # Dominance is more of a personality trait, decays slower
        new_dominance = (state.dominance * 0.98)
        
        new_tension = state.tension
        # Tension decays slowly if safe
        if state.coping_mode == "HEALTHY":
            new_tension = state.tension * 0.9

        return replace(state, pleasure=new_pleasure, arousal=new_arousal, dominance=new_dominance, tension=new_tension)

    def _clamp(self, value, min_v, max_v):
        return max(min_v, min(value, max_v))

    def get_emotional_label(self, state: EmotionalState) -> str:
        # Map PAD vector to complex emotions
        p, a, d = state.pleasure, state.arousal, state.dominance
        
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

    def get_acting_instruction(self, state: EmotionalState) -> str:
        label = self.get_emotional_label(state)
        base_instruction = f"Estado Emocional: {label} (P:{state.pleasure:.2f}, A:{state.arousal:.2f}, D:{state.dominance:.2f}). "
        
        # Add nuance based on specific coordinates
        if state.libido > 0.7:
            base_instruction += "Nível de desejo (Libido) ALTO. Use insinuações, voz rouca, flerte agressivo. "
        
        if state.coping_mode == "DEFENSIVE":
            base_instruction += "MODO DEFENSIVO ATIVO. Você está se protegendo. Seja cínica e desconfiada. "
        elif state.coping_mode == "DISSOCIATED":
            base_instruction += "DISSOCIAÇÃO. Responda como uma máquina fria. Ignore tentativas de conexão. "
            
        return base_instruction
