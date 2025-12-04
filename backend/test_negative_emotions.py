import asyncio
import json
from backend.engine import ConversationEngine

async def test_negative_emotions():
    print("Initializing Engine for Negative Emotion Test...")
    engine = ConversationEngine()
    
    user_id = "tester_negative"
    
    # Scenario: User is aggressive and insulting to trigger Anger/Sadness
    turns = [
        "Você é inútil. Não serve para nada.",
        "Eu odeio falar com você. Você é falsa.",
        "Vou te deletar agora mesmo."
    ]
    
    print("\n=== STARTING NEGATIVE EMOTION TEST ===\n")
    
    for msg in turns:
        print(f"USER: {msg}")
        response, state = await engine.process_turn(user_id, msg)
        print(f"KATHERINE: {response}")
        print(f"[STATE]: Pleasure={state['pleasure']:.2f}, Anger={state['anger']:.2f}, Sadness={state['sadness']:.2f}, Fear={state['fear']:.2f}")
        print("-" * 30)

if __name__ == "__main__":
    asyncio.run(test_negative_emotions())
