from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

import logging
from supabase_auth.errors import AuthApiError, AuthRetryableError
logger = logging.getLogger(__name__)


from pydantic import BaseModel, ConfigDict
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


security = HTTPBearer(auto_error=False)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    token = credentials.credentials
    try:
        if not engine.memory_manager.supabase:
            raise HTTPException(status_code=503, detail="Authentication service unavailable")

        auth_response = engine.memory_manager.supabase.auth.get_user(token)
        if not auth_response.user:
            raise HTTPException(status_code=401, detail="Authentication failed", headers={"WWW-Authenticate": "Bearer"})
        return auth_response.user
    except HTTPException:
        raise
    except AuthApiError as e:
        # e.status is present in AuthApiError
        if e.status in (400, 401, 403):
            raise HTTPException(status_code=401, detail="Authentication failed", headers={"WWW-Authenticate": "Bearer"})
        logger.error("Authentication service failure: Upstream AuthApiError")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except AuthRetryableError:
        logger.error("Authentication service failure: Transport/Fetch error")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except Exception:
        logger.error("Authentication service failure: Unexpected error")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str

class ChatResponse(BaseModel):
    response: str
    emotion_state: dict

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    input_data: ChatInput,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    try:
        user_id = current_user.id
        response_text, current_emotion = await engine.process_turn(user_id, input_data.message, background_tasks)
        return ChatResponse(response=response_text, emotion_state=current_emotion)
    except Exception as e:
        logger.error(f"Error in chat_endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.get("/health")
def health_check():
    return {"status": "alive", "engine_status": "ready"}

@app.get("/history")
def get_history(current_user = Depends(get_current_user)):
    user_id = current_user.id
    try:
        if not engine.memory_manager.supabase:
            return []
            
        response = engine.memory_manager.supabase.table("chat_logs")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
            
        return response.data[::-1] if response.data else []
    except Exception:
        raise HTTPException(status_code=500, detail="Internal Server Error")

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
