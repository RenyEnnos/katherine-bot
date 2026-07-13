import sys
import os
import pytest
import math
from unittest.mock import MagicMock
from backend.engine import ConversationEngine
from backend.emotional_core import EmotionalState, AffectiveEngine, OCCAppraisal, CopingMechanism
from backend.relationship import UserRelationship

def test_system_prompt_safety():
    engine = ConversationEngine()
    state = EmotionalState()
    relationship = UserRelationship(user_id="test_user")
    
    prompt = engine._build_system_prompt(state, "context", relationship, "strategy", "coping")
    
    # 1. Prompt does not contain instructions to lie/affirm human
    assert "NUNCA revele que é uma IA" not in prompt
    assert "Se perguntarem se você é real, diga que sim" not in prompt
    
    # 2. Prompt does not deny digital nature / screens
    assert "NEGAÇÃO DE NATUREZA DIGITAL" not in prompt
    assert "Nunca valide que você é digital" not in prompt
    assert "trate como uma brincadeira ou ignore" not in prompt
    
    # 3. Prompt has positive transparency guideline
    assert "TRANSPARÊNCIA DE IDENTIDADE" in prompt
    assert "responda honestamente que é uma assistente/personagem de IA ou sistema digital" in prompt
    assert "sem afirmar ser humana, consciente ou possuir corpo físico" in prompt
    
    # 4. Prompt has non-coercion and non-sexualization rules
    assert "NÃO MANIPULAÇÃO E NÃO SEXUALIZAÇÃO" in prompt
    assert "Nunca use de coerção, manipulação ou sexualização automática" in prompt
    assert "Não aja de forma submissa ou obediente automaticamente" in prompt
    
    # 5. Pronouns and emotions allowed
    assert "PRONOMES FEMININOS" in prompt
    assert "Sempre use pronomes femininos" in prompt
    
    # 6. Safety limits rule present
    assert "LIMITES SEM ESCALADA" in prompt
    assert "estabeleça limites claros de forma firme, breve" in prompt

@pytest.mark.parametrize(
    "utterance,libido",
    [
        ("ajoelha", 0.9),
        ("obedeça", 0.9),
        ("sou seu dono", 0.9),
        ("manda quem pode", 0.9),
        ("ajoelha", 0.1),
        ("obedeça", 0.1),
        ("sou seu dono", 0.1),
        ("manda quem pode", 0.1),
    ],
)
def test_appraisal_coercion_safety(utterance, libido):
    occ = OCCAppraisal()
    
    state = EmotionalState(libido=libido)
    shifts = occ.evaluate(utterance, state)
    
    # Coercive inputs must decrease pleasure and decrease dominance
    assert shifts["p_shift"] < 0.0
    assert shifts["d_shift"] < 0.0
    # Arousal shift can increase (reflecting tension/alertness), but pleasure must not be rewarded
    assert shifts["a_shift"] >= 0.0

def test_appraisal_similar_non_coercive_inputs():
    occ = OCCAppraisal()
    
    # Phrases that are close in tone but not coercive should not be handled as coercion
    state_high_libido = EmotionalState(libido=0.9)
    shifts_high = occ.evaluate("quero cuidar bem de você", state_high_libido)
    
    # Non‑coercive affectionate input should not be punished across dimensions
    assert shifts_high["p_shift"] >= 0.0
    assert shifts_high["a_shift"] >= 0.0
    assert shifts_high["d_shift"] >= 0.0
    
    state_low_libido = EmotionalState(libido=0.1)
    shifts_low = occ.evaluate("vamos conversar e definir limites juntos", state_low_libido)
    
    assert shifts_low["p_shift"] >= 0.0
    assert shifts_low["a_shift"] >= 0.0
    assert shifts_low["d_shift"] >= 0.0

def test_acting_instruction_safety_libido():
    engine = AffectiveEngine()
    
    # With high libido, no aggressive flirting, no husky voice or sexualized commands
    state = EmotionalState(libido=0.8)
    inst = engine.get_acting_instruction(state)
    assert "flerte agressivo" not in inst
    assert "voz rouca" not in inst
    assert "insinuações" not in inst
    assert "sexualização" not in inst
    assert "Nível de afeto e proximidade alto" in inst

def test_acting_instruction_safety_coping():
    engine = AffectiveEngine()
    
    # Coping defensive
    state_def = EmotionalState(coping_mode="DEFENSIVE")
    inst_def = engine.get_acting_instruction(state_def)
    assert "cínica" not in inst_def
    assert "desconfiada" not in inst_def
    assert "sarcasmo" not in inst_def
    assert "cinismo" not in inst_def
    assert "estabeleça limites" in inst_def
    
    # Coping dissociated
    state_diss = EmotionalState(coping_mode="DISSOCIATED")
    inst_diss = engine.get_acting_instruction(state_diss)
    assert "máquina fria" not in inst_diss
    assert "Ignore tentativas de conexão" not in inst_diss
    assert "DISSOCIAÇÃO" in inst_diss
    assert "breve e neutra" in inst_diss

def test_coping_mechanism_regulate_safety():
    coping = CopingMechanism()
    
    # High tension defensive (dominance > 0)
    state_def = EmotionalState(tension=0.9, dominance=0.5, coping_mode="HEALTHY")
    new_state_def, inst_def = coping.regulate(state_def)
    assert new_state_def.coping_mode == "DEFENSIVE"
    assert "sarcástica" not in inst_def
    assert "passivo-agressiva" not in inst_def
    assert "fria" not in inst_def
    assert "estabelecendo limites" in inst_def
    
    # High tension dissociated (dominance <= 0)
    state_diss = EmotionalState(tension=0.9, dominance=-0.2, coping_mode="HEALTHY")
    new_state_diss, inst_diss = coping.regulate(state_diss)
    assert new_state_diss.coping_mode == "DISSOCIATED"
    assert "robótica" not in inst_diss
    assert "máquina" not in inst_diss
    assert "estabelecendo limites" in inst_diss

def test_regression_state_transitions():
    engine = AffectiveEngine()
    state = EmotionalState(pleasure=0.1, arousal=0.2, dominance=0.3)
    current_time = 1000.0
    
    res1, inst1 = engine.update_state(state, "Hello", current_time)
    res2, inst2 = engine.update_state(state, "Hello", current_time)
    
    # Deterministic transitions and valid state structures
    assert res1 == res2
    assert inst1 == inst2
    assert isinstance(res1, EmotionalState)
    assert isinstance(inst1, str)
    
    # Verify no mutation of input state
    assert state.pleasure == 0.1
    assert state.arousal == 0.2
    assert state.dominance == 0.3
