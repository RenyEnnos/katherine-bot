import asyncio
import traceback
from backend.engine import ConversationEngine

async def debug_chat():
    print("Initializing Engine...")
    try:
        engine = ConversationEngine()
        print("Engine initialized successfully.")
    except Exception:
        traceback.print_exc()
        return

    print("Processing turn (forcing MetaCognition)...")
    try:
        # Force turn count to trigger MetaCognition (turn_count % 3 == 0)
        # engine.turn_count starts at 0. process_turn increments it to 1.
        # So we need to set it to 2 so it becomes 3.
        engine.turn_count = 2 
        response, state = await engine.process_turn("debug_user", "Olá, Katherine")
        print("Response received:", response)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_chat())
