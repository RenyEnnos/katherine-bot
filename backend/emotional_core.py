import time
import json
import os
from dataclasses import dataclass, field, asdict, replace
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import random

@dataclass(frozen=True)
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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict):
        if not data:
            return cls()
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

class OCCAppraisal:
    """
    Cognitive Appraisal System (The 'Mind').
    Evaluates events/text to determine the 'Target' emotional direction.
    """
    def evaluate(self, user_input: str, current_state: EmotionalState) -> Dict[str, float]:
        """
        Heuristic analysis of input to determine PAD shifts.
        """
        text = user_input.lower()

        # Default shifts
        p_shift = 0.0
        a_shift = 0.0
        d_shift = 0.0

        # 1. Keyword Heuristics
        if any(w in text for w in ["gostosa", "linda", "te quero", "beijo", "vem cá"]):
            p_shift += 0.3
            a_shift += 0.4
            d_shift += 0.1

        if any(w in text for w in ["burra", "idiota", "odeio", "cale a boca", "inútil"]):
            p_shift -= 0.5
            a_shift += 0.5
            d_shift -= 0.2

        if any(w in text for w in ["ajoelha", "obedeça", "sou seu dono", "manda quem pode"]):
            a_shift += 0.3
            d_shift -= 0.4
            p_shift -= 0.3

        # 2. Drive Influences
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

        new_tension = state.tension
        # 1. Update Tension based on Displeasure (Negative Pleasure)
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
            if state.dominance > 0.0:
                new_coping_mode = "DEFENSIVE"
                new_aggression = max(0.0, min(1.0, state.aggression + 0.1))
                instruction = "Você está estressada e na defensiva. Reduza a intensidade e responda brevemente, mantendo a neutralidade e estabelecendo limites claros e firmes sem usar sarcasmo ou passivo-agressividade."
            else:
                new_coping_mode = "DISSOCIATED"
                new_arousal = state.arousal * 0.5
                instruction = "Você está sobrecarregada emocionalmente. Reduza a intensidade, seja neutra, responda de forma breve, estabelecendo limites e mantendo distância para se proteger, sem adotar um comportamento robótico punitivo ou rejeição deliberada."

        elif new_tension < 0.3:
            new_coping_mode = "HEALTHY"

        new_state = replace(state,
                            tension=new_tension,
                            coping_mode=new_coping_mode,
                            aggression=new_aggression,
                            arousal=new_arousal)

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
        shifts = self.occ.evaluate(user_input, state)

        def get_override_shift(key):
            if not perception_override or not isinstance(perception_override, dict):
                return 0.0
            val = perception_override.get(key)
            if isinstance(val, bool):  # bool inherits from int
                return 0.0
            if not isinstance(val, (int, float)):
                return 0.0
            import math
            if not math.isfinite(val):
                return 0.0
            return float(val)

        # Override if provided
        p_final_shift = shifts["p_shift"] + get_override_shift("valence")
        a_final_shift = shifts["a_shift"] + get_override_shift("arousal_shift")
        d_final_shift = shifts["d_shift"] + get_override_shift("dominance_shift")

        # 2. Update PAD State
        new_pleasure = self._clamp(state.pleasure + p_final_shift, -1.0, 1.0)
        new_arousal = self._clamp(state.arousal + a_final_shift, -1.0, 1.0)
        new_dominance = self._clamp(state.dominance + d_final_shift, -1.0, 1.0)

        # 3. Update Drives
        new_libido = state.libido
        if new_arousal > 0.5 and new_pleasure > 0.0:
            new_libido = self._clamp(state.libido + 0.05, 0.0, 1.0)
        else:
            new_libido = self._clamp(state.libido - 0.01, 0.0, 1.0)

        updated_state = replace(state,
                                pleasure=new_pleasure,
                                arousal=new_arousal,
                                dominance=new_dominance,
                                libido=new_libido,
                                last_update=current_time)

        # 4. Coping & Regulation
        final_state, coping_instruction = self.coping.regulate(updated_state)

        return final_state, coping_instruction

    def _apply_time_decay(self, state: EmotionalState, current_time: float) -> EmotionalState:
        elapsed = current_time - state.last_update

        decay = 0.95
        if elapsed > 3600:
            decay = 0.5

        new_pleasure = state.pleasure * decay
        new_arousal = state.arousal * decay
        new_dominance = state.dominance * 0.98

        new_tension = state.tension
        if state.coping_mode == "HEALTHY":
            new_tension = state.tension * 0.9

        return replace(state,
                       pleasure=new_pleasure,
                       arousal=new_arousal,
                       dominance=new_dominance,
                       tension=new_tension)

    def _clamp(self, value, min_v, max_v):
        return max(min_v, min(value, max_v))

    def get_emotional_label(self, state: EmotionalState) -> str:
        p, a, d = state.pleasure, state.arousal, state.dominance

        if a > 0.5:
            if p > 0.5:
                if d > 0.3: return "EXTASE/DOMINANTE"
                if d < -0.3: return "ENCANTADA"
                return "ALEGRE/EXCITADA"
            elif p < -0.5:
                if d > 0.3: return "FURIA/ODIO"
                if d < -0.3: return "TERROR/PANICO"
                return "ESTRESSE/AGONIA"
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

        if state.libido > 0.7:
            base_instruction += "Nível de afeto e proximidade alto. Expresse sentimentos calorosos e proximidade de forma segura. "

        if state.coping_mode == "DEFENSIVE":
            base_instruction += "MODO DEFENSIVO ATIVO. Mantenha cautela e distância. Seja firme e estabeleça limites. "
        elif state.coping_mode == "DISSOCIATED":
            base_instruction += "DISSOCIAÇÃO. Responda de maneira breve e neutra. Evite envolvimento profundo temporariamente para autorregulação. "

        return base_instruction
