from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import os
from dotenv import load_dotenv
from .engine import ConversationEngine

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SoulMate API", description="Backend for the Emotional Companion Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Engine
engine = ConversationEngine()

class ChatInput(BaseModel):
    user_id: str
    message: str

class ChatResponse(BaseModel):
    response: str
    emotion_state: dict

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(input_data: ChatInput, background_tasks: BackgroundTasks):
    try:
        response_text, current_emotion = await engine.process_turn(input_data.user_id, input_data.message, background_tasks)
        return ChatResponse(response=response_text, emotion_state=current_emotion)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "alive", "engine_status": "ready"}

@app.get("/history/{user_id}")
async def get_history(user_id: str):
    try:
        # Fetch last 50 messages from Supabase
        # We access the supabase client via the engine's memory manager
        if not engine.memory_manager.supabase:
            return []
            
        response = engine.memory_manager.supabase.table("chat_logs")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
            
        # Return reversed (chronological order)
        return response.data[::-1] if response.data else []
    except Exception as e:
        print(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
