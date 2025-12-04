import os
import json
import chromadb
from datetime import datetime
from .groq_manager import GroqClientManager
from .relationship import UserRelationship

class CoreMemory:
    def __init__(self, filepath="core_memory.json"):
        self.filepath = filepath
        self.data = self._load_memory()
        
    def _load_memory(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure relationships dict exists
                if "relationships" not in data:
                    data["relationships"] = {}
                return data
        return {
            "persona": "Katherine...",
            "user_profile": {},
            "relationships": {} # user_id -> UserRelationship dict
        }

    def save_memory(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def get_relationship(self, user_id: str) -> UserRelationship:
        rel_data = self.data["relationships"].get(user_id)
        if rel_data:
            return UserRelationship.from_dict(rel_data)
        return UserRelationship(user_id=user_id)

    def update_relationship(self, relationship: UserRelationship):
        self.data["relationships"][relationship.user_id] = relationship.to_dict()
        self.save_memory()

    def update_user_profile(self, analysis: dict):
        # Merge new analysis into existing profile
        current = self.data.get("user_profile", {})
        current.update(analysis)
        self.data["user_profile"] = current
        self.save_memory()

class MemoryManager:
    def __init__(self):
        # 1. Core Memory (Always present)
        self.core_memory = CoreMemory()
        
        # 2. Short-term memory (Working Context)
        self.short_term_memory = {} 
        
        # 3. Archival Memory (ChromaDB - Long Term)
        self.chroma_client = chromadb.PersistentClient(path="./chroma_db")
        self.collection = self.chroma_client.get_or_create_collection(name="soulmate_memories")
        
        # Use Manager for rotation
        self.groq_manager = GroqClientManager()
        self.model_fast = "llama-3.1-8b-instant"

    def get_context(self, user_id: str, current_message: str):
        # 1. Get Short Term History (Last 10 turns for better flow)
        history = self.short_term_memory.get(user_id, [])
        short_term_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-10:]])
        
        # 2. Retrieve Archival Memories (RAG)
        relevant_memories = self._retrieve_relevant(current_message)
        
        context_str = f"""
        === CORE MEMORY (QUEM VOCÊ É) ===
        {self.core_memory.data.get('persona', 'Katherine...')}
        
        === CORE MEMORY (QUEM É O USUÁRIO) ===
        {self.core_memory.data.get('user_profile', {})}
        
        === MEMÓRIA ARQUIVADA (LEMBRANÇAS RELEVANTES) ===
        {relevant_memories}
        
        === CONVERSA ATUAL (CURTO PRAZO) ===
        {short_term_str}
        """
        return context_str

    def save_turn(self, user_id: str, user_msg: str, bot_msg: str):
        if user_id not in self.short_term_memory:
            self.short_term_memory[user_id] = []
            
        # Update Short Term
        self.short_term_memory[user_id].append({"role": "user", "content": user_msg})
        self.short_term_memory[user_id].append({"role": "assistant", "content": bot_msg})
        
        # Trim Short Term (Keep last 20 messages max)
        if len(self.short_term_memory[user_id]) > 20:
            self.short_term_memory[user_id] = self.short_term_memory[user_id][-20:]
            
        # Async: Extract Facts & Update Core Memory
        self._analyze_and_store(user_msg)

    def _retrieve_relevant(self, query: str):
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=3
            )
            
            if not results['documents'] or not results['documents'][0]:
                return "Nenhuma memória específica encontrada."
                
            formatted = []
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                formatted.append(f"- {doc} (Tags: {meta.get('tags', '')})")
                
            return "\n".join(formatted)
        except Exception as e:
            print(f"Error retrieving memory: {e}")
            return ""

    def _analyze_and_store(self, text: str):
        # Ask LLM to extract facts AND suggest Core Memory updates
        prompt = f"""
        Analise a mensagem do usuário: "{text}"
        
        1. Extraia fatos novos para a Memória de Arquivo (eventos, gostos, opiniões).
        2. Sugira atualizações para a Core Memory do Usuário (se descobrimos algo fundamental sobre ele).
        
        Retorne JSON: 
        {{
            "archival_facts": [{{"content": "...", "tags": "...", "importance": 0.0-1.0}}],
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
                    self._store_fact(fact)
            
            # Update Core Memory (Append logic for simplicity, real MemGPT replaces sections)
            # Update Core Memory
            update_text = data.get('core_memory_update')
            if update_text:
                # We append this to a 'notes' field in user_profile or update a specific key if structured
                # For simplicity, we'll maintain a list of 'key_facts' in user_profile
                current_profile = self.core_memory.data.get("user_profile", {})
                if "notes" not in current_profile:
                    current_profile["notes"] = []
                
                # Avoid duplicates
                if update_text not in current_profile["notes"]:
                    current_profile["notes"].append(update_text)
                    self.core_memory.update_user_profile(current_profile)
                    print(f"Updated Core Memory Profile: {update_text}") 
                
        except Exception as e:
            print(f"Error analyzing memory: {e}")

    def _store_fact(self, fact):
        fact_id = f"mem_{datetime.now().timestamp()}"
        
        # Ensure tags are a string, not a list
        tags_value = fact['tags']
        if isinstance(tags_value, list):
            tags_value = ",".join(tags_value)
            
        self.collection.add(
            documents=[fact['content']],
            metadatas=[{"tags": tags_value, "importance": fact['importance'], "timestamp": str(datetime.now())}],
            ids=[fact_id]
        )
        print(f"Saved Archival Memory: {fact['content']}")
