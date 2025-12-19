import asyncio
import os
from dotenv import load_dotenv
from backend.engine import ConversationEngine

# Load env vars
load_dotenv()

async def test_conversation():
    print("Initializing Engine...")
    engine = ConversationEngine()
    
    user_id = "test_user_001"
    
    turns = [
        "Oi Katherine, tudo bem? O dia está lindo hoje.",
        "Estou me sentindo um pouco triste com meu trabalho.",
        "Você acha que eu deveria pedir demissão?",
        "Obrigado pelo apoio, você é incrível.",
        "Na verdade, estou com medo do futuro.",
        "Mas conversar com você me acalma."
    ]
    
    print("\n=== STARTING CONVERSATION TEST (WITH META-COGNITION) ===\n")
    
    for i, msg in enumerate(turns):
        print(f"TURN {i+1} | USER: {msg}")
        response, state = await engine.process_turn(user_id, msg)
        
        print(f"KATHERINE: {response}")
        print(f"[STATE]: Mood={state.get('pleasure'):.2f}, Energy={state.get('energy'):.2f}")
        
        # Check if profile was updated (every 3 turns)
        if (i + 1) % 3 == 0:
            # We need to access cached profile or reload
            # print(f"[META]: User Profile Updated -> {engine.memory_manager.current_user_profile}")
            pass
            
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(test_conversation())
