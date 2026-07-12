import os
import json
import logging
from datetime import datetime
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from .groq_manager import GroqClientManager
from .relationship import UserRelationship
from .emotional_core import EmotionalState

logger = logging.getLogger(__name__)

class StatePersistenceError(Exception):
    """Exception raised when user state cannot be persisted safely."""
    def __init__(self, message="Falha ao persistir estado do usuário"):
        self.message = message
        super().__init__(self.message)

class StateLoadError(Exception):
    """Exception raised when user state cannot be loaded safely."""
    def __init__(self, message="Falha ao carregar estado do usuário"):
        self.message = message
        super().__init__(self.message)

class MemoryManager:
    def __init__(self):
        # 1. Initialize Supabase
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            self.supabase: Client = None
        else:
            try:
                self.supabase: Client = create_client(url, key)
            except Exception:
                self.supabase = None

        # 2. Initialize Embeddings Model (Local)
        try:
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception:
            self.embedding_model = None

        # 3. Short-term memory (Working Context)
        self.short_term_memory = {} 
        
        # 4. LLM Manager
        self.groq_manager = GroqClientManager()
        self.model_fast = "llama-3.1-8b-instant"

    def load_user_state(self, user_id: str) -> dict:
        """
        Loads the full user state from Supabase 'profiles' table.
        If not found, creates a default profile.
        """
        if not self.supabase:
            raise StateLoadError("Serviço de persistência indisponível.")

        try:
            response = self.supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        except Exception as e:
            raise StateLoadError("Erro ao recuperar perfil do banco de dados.") from e

        if response is None or not hasattr(response, "data") or response.data is None:
            raise StateLoadError("Resposta inválida do serviço de persistência.")

        if len(response.data) == 0:
            # Create default profile
            default_state = self._get_default_state(user_id)
            try:
                insert_resp = self.supabase.table("profiles").insert({
                    "user_id": user_id,
                    "persona_config": default_state["persona_config"],
                    "user_profile": default_state["user_profile"],
                    "relationship_state": default_state["relationship_state"],
                    "emotional_state": default_state["emotional_state"]
                }).execute()
            except Exception as e:
                raise StateLoadError("Falha ao inicializar perfil padrão.") from e

            if insert_resp is None or not hasattr(insert_resp, "data") or not insert_resp.data:
                raise StateLoadError("Falha ao salvar perfil padrão criado.")
            return default_state

        try:
            data = response.data[0]
            return {
                "persona_config": data.get("persona_config"),
                "user_profile": data.get("user_profile") or {},
                "relationship_state": data.get("relationship_state") or {},
                "emotional_state": data.get("emotional_state") or {}
            }
        except Exception as e:
            raise StateLoadError("Erro ao processar dados de perfil.") from e

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
        Raises StatePersistenceError if persistence fails.
        """
        if not self.supabase:
            raise StatePersistenceError("Serviço de persistência não configurado.")

        update_data = {
            "emotional_state": emotional_state.to_dict(),
            "relationship_state": relationship.to_dict(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        if user_profile:
            update_data["user_profile"] = user_profile

        try:
            response = self.supabase.table("profiles").update(update_data).eq("user_id", user_id).execute()
            # If response is empty or has error attribute (depending on supabase version)
            if response is None:
                raise StatePersistenceError()

            if hasattr(response, 'error') and response.error:
                raise StatePersistenceError()

        except StatePersistenceError:
            raise
        except Exception as e:
            # Chain the original exception for internal debugging but don't leak it in the message
            raise StatePersistenceError() from e

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
            except Exception:
                pass

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
        except Exception:
            pass

    def _retrieve_relevant(self, user_id: str, query: str):
        if not self.supabase or not self.embedding_model:
            return "Memória indisponível (offline)."

        try:
            # Generate embedding
            query_embedding = self.embedding_model.encode(query).tolist()
            
            # Call RPC function
            params = {
                "query_embedding": query_embedding,
                "match_threshold": 0.5,
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
        except Exception:
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
                if self.supabase:
                    resp = self.supabase.table("profiles").select("user_profile").eq("user_id", user_id).execute()
                    if resp.data:
                        current_profile = resp.data[0].get("user_profile", {})
                        if "notes" not in current_profile:
                            current_profile["notes"] = []
                        
                        if update_text not in current_profile["notes"]:
                            current_profile["notes"].append(update_text)
                            self.supabase.table("profiles").update({"user_profile": current_profile}).eq("user_id", user_id).execute()

        except Exception:
            pass

    def _store_memory(self, user_id: str, content: str, tags: list, importance: float):
        if not self.supabase or not self.embedding_model:
            return

        try:
            embedding = self.embedding_model.encode(content).tolist()
            
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
        except Exception:
            pass
