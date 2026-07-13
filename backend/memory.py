import os
import logging
from datetime import datetime, UTC
from supabase import create_client, Client
from sentence_transformers import SentenceTransformer
from .relationship import UserRelationship
from .emotional_core import EmotionalState

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 10000  # Limite máximo de caracteres por mensagem no histórico para evitar sobrecarga de contexto

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

class ContextLoadError(Exception):
    """Exception raised when turn history cannot be loaded from the database."""
    def __init__(self, message="Falha ao carregar histórico de conversação"):
        self.message = message
        super().__init__(self.message)

class TurnPersistenceError(Exception):
    """Exception raised when a conversation turn cannot be saved to the database."""
    def __init__(self, message="Falha ao persistir turno de conversação"):
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



    def load_user_state(self, user_id: str) -> dict:
        """
        Loads the full user state from Supabase 'profiles' table.
        If not found, creates a default profile.
        Raises StateLoadError on transient database failures.
        """
        if not self.supabase:
            raise StateLoadError("Serviço de persistência indisponível.")

        try:
            response = self.supabase.table("profiles").select("*").eq("user_id", user_id).execute()

            if response is None:
                raise StateLoadError("Sem resposta do banco de dados na leitura.")

            # Check for error in response if client supports it
            if hasattr(response, 'error') and response.error:
                raise StateLoadError("Erro retornado pelo banco de dados na leitura.")

            if not hasattr(response, 'data') or response.data is None:
                raise StateLoadError("Resposta inválida do banco de dados na leitura.")

            if len(response.data) == 0:
                # Create default profile
                default_state = self._get_default_state(user_id)
                try:
                    insert_response = self.supabase.table("profiles").insert({
                        "user_id": user_id,
                        "persona_config": default_state["persona_config"],
                        "user_profile": default_state["user_profile"],
                        "relationship_state": default_state["relationship_state"],
                        "emotional_state": default_state["emotional_state"]
                    }).execute()

                    if insert_response is None:
                        raise StateLoadError("Sem resposta do banco de dados na criação do perfil.")
                    if hasattr(insert_response, 'error') and insert_response.error:
                        raise StateLoadError("Erro retornado pelo banco de dados na criação do perfil.")
                    if not hasattr(insert_response, 'data') or insert_response.data is None or len(insert_response.data) == 0:
                        raise StateLoadError("Nenhuma linha foi criada no banco de dados para o perfil.")
                except StateLoadError:
                    raise
                except Exception as e:
                    raise StateLoadError("Falha na criação do perfil inicial.") from e
                return default_state

            data = response.data[0]
            return {
                "persona_config": data.get("persona_config"),
                "user_profile": data.get("user_profile") or {},
                "relationship_state": data.get("relationship_state") or {},
                "emotional_state": data.get("emotional_state") or {}
            }
        except StateLoadError:
            raise
        except Exception as e:
            raise StateLoadError("Falha ao carregar estado do usuário.") from e

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
            "updated_at": datetime.now(UTC).isoformat()
        }

        if user_profile:
            update_data["user_profile"] = user_profile

        try:
            response = self.supabase.table("profiles").update(update_data).eq("user_id", user_id).execute()

            if response is None:
                raise StatePersistenceError()

            if hasattr(response, 'error') and response.error:
                raise StatePersistenceError()

            # Check for zero updated rows (response.data is empty list)
            if not response.data:
                raise StatePersistenceError()

        except StatePersistenceError:
            raise
        except Exception as e:
            raise StatePersistenceError() from e

    def load_recent_history(self, user_id: str, limit: int = 10) -> list:
        if not self.supabase:
            raise ContextLoadError("Serviço de persistência indisponível.")
        try:
            response = self.supabase.table("chat_logs")\
                .select("role, content")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .order("id", desc=True)\
                .limit(limit)\
                .execute()
            if response is None:
                raise ContextLoadError("Sem resposta do banco de dados na leitura do histórico.")
            if hasattr(response, 'error') and response.error:
                raise ContextLoadError("Erro retornado pelo banco de dados na leitura do histórico.")
            if not hasattr(response, 'data') or response.data is None:
                raise ContextLoadError("Resposta inválida do banco de dados na leitura do histórico.")
            if not isinstance(response.data, list):
                raise ContextLoadError("Resposta do banco de dados não é uma lista.")

            normalized = []
            for item in response.data:
                if not isinstance(item, dict):
                    raise ContextLoadError("Item do histórico não é um dicionário.")
                if "role" not in item or "content" not in item:
                    raise ContextLoadError("Item do histórico não possui as chaves obrigatórias 'role' e 'content'.")
                role = item["role"]
                content = item["content"]
                if role not in ("user", "assistant"):
                    raise ContextLoadError("Role inválida no histórico recente.")
                if not isinstance(content, str):
                    raise ContextLoadError("Conteúdo da mensagem não é uma string.")
                if len(content) > MAX_MESSAGE_LENGTH:
                    raise ContextLoadError("Mensagem no histórico excede o limite máximo de caracteres permitido.")
                
                # Normalize: keep only role and content
                normalized.append({
                    "role": role,
                    "content": content
                })

            return normalized[::-1]
        except ContextLoadError as e:
            logger.error(f"Erro ao carregar histórico: {type(e).__name__}")
            raise
        except Exception as e:
            logger.error(f"Erro ao carregar histórico: {type(e).__name__}")
            raise ContextLoadError("Falha ao carregar histórico de conversação.") from None

    def get_context(self, user_id: str, current_message: str, user_state: dict):
        history = self.load_recent_history(user_id, limit=10)
        short_term_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
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
        if not self.supabase:
            raise TurnPersistenceError("Serviço de persistência indisponível.")
        try:
            if len(user_msg) > MAX_MESSAGE_LENGTH or len(bot_msg) > MAX_MESSAGE_LENGTH:
                raise TurnPersistenceError("Limite de caracteres excedido no turno.")
            response = self.supabase.table("chat_logs").insert([
                {"user_id": user_id, "role": "user", "content": user_msg},
                {"user_id": user_id, "role": "assistant", "content": bot_msg}
            ]).execute()
            if response is None:
                raise TurnPersistenceError("Sem resposta do banco de dados ao salvar turno.")
            if hasattr(response, 'error') and response.error:
                raise TurnPersistenceError("Erro retornado pelo banco de dados ao salvar turno.")
            if not hasattr(response, 'data') or response.data is None or len(response.data) != 2:
                raise TurnPersistenceError("Falha na gravação do turno: registros inseridos incompletos.")
        except TurnPersistenceError as e:
            logger.error(f"Erro ao persistir turno: {type(e).__name__}")
            raise
        except Exception as e:
            logger.error(f"Erro ao persistir turno: {type(e).__name__}")
            raise TurnPersistenceError("Falha ao persistir turno de conversação.") from None

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
