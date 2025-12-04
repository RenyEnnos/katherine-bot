from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time

@dataclass
class UserRelationship:
    user_id: str
    trust: float = 0.5        # 0.0 (distrust) to 1.0 (blind trust)
    affection: float = 0.3    # 0.0 (indifference) to 1.0 (love/deep care)
    tension: float = 0.0      # 0.0 (peace) to 1.0 (conflict/resentment)
    bond_label: str = "Conhecidos"
    
    # Emotional triggers specific to this user (e.g., "childhood", "music")
    triggers: List[str] = field(default_factory=list)
    
    last_interaction: float = field(default_factory=time.time)

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(data: Dict):
        rel = UserRelationship(user_id=data["user_id"])
        rel.trust = data.get("trust", 0.5)
        rel.affection = data.get("affection", 0.3)
        rel.tension = data.get("tension", 0.0)
        rel.bond_label = data.get("bond_label", "Conhecidos")
        rel.triggers = data.get("triggers", [])
        rel.last_interaction = data.get("last_interaction", time.time())
        return rel

class RelationshipManager:
    def __init__(self):
        pass

    def update_relationship(self, relationship: UserRelationship, perception: Dict) -> UserRelationship:
        """
        Evolves the relationship based on the emotional impact of the last interaction.
        """
        valence = perception.get("valence", 0)
        triggered_emotions = perception.get("triggered_emotions", {})
        
        # 1. Update Trust
        # Trust builds slowly with positive valence and consistency
        if valence > 0.2:
            relationship.trust = self._clamp(relationship.trust + 0.02)
        elif valence < -0.3:
            # Trust breaks faster than it builds
            relationship.trust = self._clamp(relationship.trust - 0.05)
            
        # 2. Update Affection
        # Affection grows with Tenderness, Joy, Gratitude
        affection_boost = 0.0
        if triggered_emotions.get("tenderness", 0) > 0.3: affection_boost += 0.03
        if triggered_emotions.get("joy", 0) > 0.3: affection_boost += 0.01
        if triggered_emotions.get("gratitude", 0) > 0.3: affection_boost += 0.02
        
        relationship.affection = self._clamp(relationship.affection + affection_boost)
        
        # 3. Update Tension
        # Tension rises with Anger, Disgust, or negative valence
        tension_spike = 0.0
        if triggered_emotions.get("anger", 0) > 0.3: tension_spike += 0.1
        if triggered_emotions.get("disgust", 0) > 0.3: tension_spike += 0.1
        if valence < -0.5: tension_spike += 0.05
        
        relationship.tension = self._clamp(relationship.tension + tension_spike)
        
        # Decay Tension if interaction was positive (Reconciliation)
        if valence > 0.3 and relationship.tension > 0:
            relationship.tension = self._clamp(relationship.tension - 0.1)

        # 4. Update Bond Label
        relationship.bond_label = self._determine_bond_label(relationship)
        
        relationship.last_interaction = time.time()
        return relationship

    def _determine_bond_label(self, rel: UserRelationship) -> str:
        if rel.tension > 0.7:
            return "Em Conflito"
        if rel.tension > 0.4:
            return "Tenso"
            
        if rel.trust > 0.8 and rel.affection > 0.8:
            return "Alma Gêmea"
        if rel.trust > 0.7 and rel.affection > 0.6:
            return "Íntimos"
        if rel.trust > 0.5 and rel.affection > 0.4:
            return "Amigos"
        if rel.trust < 0.3:
            return "Desconfiada"
            
        return "Conhecidos"

    def _clamp(self, value, min_v=0.0, max_v=1.0):
        return max(min_v, min(value, max_v))
