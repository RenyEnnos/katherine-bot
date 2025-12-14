import os
import json
from datetime import datetime
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from .groq_manager import GroqClientManager
from .relationship import UserRelationship
from .emotional_core import EmotionalState

class MemoryManager:
    def __init__(self):
        # 1. Initialize Supabase
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            print("WARNING: SUPABASE_URL or SUPABASE_KEY not found. Persistence will fail.")
            self.supabase: Client = None
        else:
            self.supabase: Client = create_client(url, key)

        # 2. Initialize Embeddings Model (Lazy Load)
        # We use a lightweight model compatible with the 384-dim vector in Supabase
        self.embedding_model = None

        # 3. Short-term memory (Working Context)
        self.short_term_memory = {} 
        
        # 4. LLM Manager
        self.groq_manager = GroqClientManager()
        self.model_fast = "llama-3.1-8b-instant"

        # Cache for current session state
        self.current_user_profile = {}
        self.current_relationship = None
        self.current_emotional_state = None

    def _get_embedding_model(self):
        if self.embedding_model is None:
            try:
                print("INFO: Loading embedding model (lazy)...")
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception as e:
                print(f"Error loading embedding model: {e}")
                self.embedding_model = None
        return self.embedding_model

    def load_user_state(self, user_id: str) -> dict:
        """
        Loads the full user state from Supabase 'profiles' table.
        If not found, creates a default profile.
        """
        if not self.supabase:
            return self._get_default_state(user_id)

        try:
            response = self.supabase.table("profiles").select("*").eq("user_id", user_id).execute()
            
            if not response.data:
                # Create default profile
                default_state = self._get_default_state(user_id)
                self.supabase.table("profiles").insert({
                    "user_id": user_id,
                    "persona_config": default_state["persona_config"],
                    "user_profile": default_state["user_profile"],
                    "relationship_state": default_state["relationship_state"],
                    "emotional_state": default_state["emotional_state"]
                }).execute()
                return default_state
            
            data = response.data[0]
            return {
                "persona_config": data.get("persona_config"),
                "user_profile": data.get("user_profile") or {},
                "relationship_state": data.get("relationship_state") or {},
                "emotional_state": data.get("emotional_state") or {}
            }
        except Exception as e:
            print(f"Error loading user state: {e}")
            return self._get_default_state(user_id)

    def _get_default_state(self, user_id: str):
        return {
            "persona_config": "Katherine...",
            "user_profile": {},
            "relationship_state": UserRelationship(user_id=user_id).to_dict(),
            "emotional_state": EmotionalState().to_dict()
        }

    def sync_state(self, user_id: str, emotional_state: EmotionalState, relationship: UserRelationship, user_profile: dict = None):
        """
        Persists the current state to Supabase.
        """
        if not self.supabase: return

        update_data = {
            "emotional_state": emotional_state.to_dict(),
            "relationship_state": relationship.to_dict(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if user_profile:
            update_data["user_profile"] = user_profile

        try:
            self.supabase.table("profiles").update(update_data).eq("user_id", user_id).execute()
            # print(f"DEBUG: Synced state for {user_id}")
        except Exception as e:
            print(f"Error syncing state: {e}")

    def get_context(self, user_id: str, current_message: str, user_state: dict):
        # 1. Get Short Term History
        history = self.short_term_memory.get(user_id, [])
        short_term_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-10:]])
        
        # 2. Retrieve Archival Memories (RAG)
        relevant_memories = self._retrieve_relevant(user_id, current_message)
        
        context_str = f"""
        === CORE MEMORY (QUEM VOCÊ É) ===
        {user_state.get('persona_config', 'Katherine...')}
        
        === CORE MEMORY (QUEM É O USUÁRIO) ===
        {user_state.get('user_profile', {})}
        
        === MEMÓRIA ARQUIVADA (LEMBRANÇAS RELEVANTES) ===
        {relevant_memories}
        
        === CONVERSA ATUAL (CURTO PRAZO) ===
        {short_term_str}
        """
        return context_str

    def save_turn(self, user_id: str, user_msg: str, bot_msg: str):
        # 1. Update Short Term Memory
        if user_id not in self.short_term_memory:
            self.short_term_memory[user_id] = []
        
        self.short_term_memory[user_id].append({"role": "user", "content": user_msg})
        self.short_term_memory[user_id].append({"role": "assistant", "content": bot_msg})
        
        # 2. Persist to Supabase Chat Logs
        if self.supabase:
            try:
                self.supabase.table("chat_logs").insert([
                    {"user_id": user_id, "role": "user", "content": user_msg},
                    {"user_id": user_id, "role": "assistant", "content": bot_msg}
                ]).execute()
            except Exception as e:
                print(f"Error saving chat logs: {e}")

        # 3. Check for compression
        if len(self.short_term_memory[user_id]) > 20:
            self._compress_episodes(user_id)
            
        # 4. Async: Extract Facts & Update Core Memory
        self._analyze_and_store(user_id, user_msg)

    def _compress_episodes(self, user_id: str):
        if len(self.short_term_memory[user_id]) < 20:
            return

        oldest_messages = self.short_term_memory[user_id][:10]
        self.short_term_memory[user_id] = self.short_term_memory[user_id][10:]
        
        conversation_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in oldest_messages])
        
        prompt = f"""
        Analyze this conversation segment and create a concise "Episodic Memory".
        Focus on:
        1. Key events or topics discussed.
        2. Emotional tone of the user.
        3. Any significant revelations.
        
        Conversation:
        {conversation_text}
        
        Return ONLY the summary text.
        """
        
        try:
            completion = self.groq_manager.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                temperature=0.3
            )
            summary = completion.choices[0].message.content
            
            # Store in Supabase
            self._store_memory(user_id, summary, tags=["episodic", "summary"], importance=0.8)
            print(f"Compressed episodes into: {summary}")
        except Exception as e:
            print(f"Error compressing episodes: {e}")

    def _retrieve_relevant(self, user_id: str, query: str):
        model = self._get_embedding_model()
        if not self.supabase or not model:
            return "Memória indisponível (offline)."

        try:
            # Generate embedding
            query_embedding = model.encode(query).tolist()
            
            # Call RPC function
            params = {
                "query_embedding": query_embedding,
                "match_threshold": 0.5, # Adjust threshold as needed
                "match_count": 3,
                "filter_user_id": user_id
            }
            response = self.supabase.rpc("match_memories", params).execute()
            
            if not response.data:
                return "Nenhuma memória específica encontrada."
                
            formatted = []
            for doc in response.data:
                meta = doc.get('metadata', {})
                formatted.append(f"- {doc['content']} (Tags: {meta.get('tags', '')})")
                
            return "\n".join(formatted)
        except Exception as e:
            print(f"Error retrieving memory: {e}")
            return ""

    def _analyze_and_store(self, user_id: str, text: str):
        prompt = f"""
        Analise a mensagem do usuário: "{text}"
        
        1. Extraia fatos novos para a Memória de Arquivo (eventos, gostos, opiniões).
        2. Sugira atualizações para a Core Memory do Usuário (se descobrimos algo fundamental sobre ele).
        
        Retorne JSON: 
        {{
            "archival_facts": [{{"content": "...", "tags": "tag1,tag2", "importance": 0.0-1.0}}],
            "core_memory_update": "Texto para adicionar/modificar no perfil do usuário (ou null se nada mudar)"
        }}
        """
        
        try:
            completion = self.groq_manager.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                temperature=0,
                response_format={"type": "json_object"}
            )
            data = json.loads(completion.choices[0].message.content)
            
            # Store Archival Facts
            for fact in data.get('archival_facts', []):
                if fact['importance'] > 0.5:
                    tags = fact['tags'].split(',') if isinstance(fact['tags'], str) else fact['tags']
                    self._store_memory(user_id, fact['content'], tags, fact['importance'])
            
            # Update Core Memory
            update_text = data.get('core_memory_update')
            if update_text:
                # We need to fetch current profile first (or rely on cached if we trust it)
                # Ideally, we fetch fresh to avoid race conditions, but for now we append to what we have or fetch
                # For simplicity, let's fetch fresh state in next turn or just append to a list in DB?
                # We'll rely on the fact that we sync state at end of turn. 
                # BUT, this runs async. So we should probably fetch-update-push.
                
                # Fetch current profile specifically
                if self.supabase:
                    resp = self.supabase.table("profiles").select("user_profile").eq("user_id", user_id).execute()
                    if resp.data:
                        current_profile = resp.data[0].get("user_profile", {})
                        if "notes" not in current_profile:
                            current_profile["notes"] = []
                        
                        if update_text not in current_profile["notes"]:
                            current_profile["notes"].append(update_text)
                            self.supabase.table("profiles").update({"user_profile": current_profile}).eq("user_id", user_id).execute()
                            print(f"Updated Core Memory Profile: {update_text}")

        except Exception as e:
            print(f"Error analyzing memory: {e}")

    def _store_memory(self, user_id: str, content: str, tags: list, importance: float):
        model = self._get_embedding_model()
        if not self.supabase or not model:
            return

        try:
            embedding = model.encode(content).tolist()
            
            self.supabase.table("memories").insert({
                "user_id": user_id,
                "content": content,
                "embedding": embedding,
                "metadata": {
                    "tags": tags,
                    "importance": importance,
                    "timestamp": str(datetime.now())
                }
            }).execute()
            print(f"Saved Archival Memory: {content}")
        except Exception as e:
            print(f"Error storing memory: {e}")
