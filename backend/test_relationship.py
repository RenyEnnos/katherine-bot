import asyncio
from backend.engine import ConversationEngine

async def test_relationship_evolution():
    print("Initializing Engine for Relationship Test...")
    engine = ConversationEngine()
    user_id = "tester_relationship"
    
    # 1. Initial State
    print("\n=== INITIAL STATE ===")
    rel = engine.memory_manager.core_memory.get_relationship(user_id)
    print(f"Bond: {rel.bond_label} | Trust: {rel.trust:.2f} | Affection: {rel.affection:.2f} | Tension: {rel.tension:.2f}")
    
    # 2. Positive Interaction (Building Trust/Affection)
    print("\n=== POSITIVE INTERACTION (Compliment) ===")
    msg = "Você é incrível, Katherine. Sinto que posso confiar em você."
    print(f"USER: {msg}")
    response, state = await engine.process_turn(user_id, msg)
    print(f"KATHERINE: {response}")
    
    rel = engine.memory_manager.core_memory.get_relationship(user_id)
    print(f"Bond: {rel.bond_label} | Trust: {rel.trust:.2f} | Affection: {rel.affection:.2f} | Tension: {rel.tension:.2f}")
    
    # 3. Negative Interaction (Creating Tension)
    print("\n=== NEGATIVE INTERACTION (Insult) ===")
    msg = "Você não entende nada. É irritante falar com você."
    print(f"USER: {msg}")
    response, state = await engine.process_turn(user_id, msg)
    print(f"KATHERINE: {response}")
    
    rel = engine.memory_manager.core_memory.get_relationship(user_id)
    print(f"Bond: {rel.bond_label} | Trust: {rel.trust:.2f} | Affection: {rel.affection:.2f} | Tension: {rel.tension:.2f}")

    # 4. Reconciliation (Reducing Tension)
    print("\n=== RECONCILIATION (Apology) ===")
    msg = "Desculpa, eu não queria dizer aquilo. Tive um dia ruim."
    print(f"USER: {msg}")
    response, state = await engine.process_turn(user_id, msg)
    print(f"KATHERINE: {response}")
    
    rel = engine.memory_manager.core_memory.get_relationship(user_id)
    print(f"Bond: {rel.bond_label} | Trust: {rel.trust:.2f} | Affection: {rel.affection:.2f} | Tension: {rel.tension:.2f}")

if __name__ == "__main__":
    asyncio.run(test_relationship_evolution())
