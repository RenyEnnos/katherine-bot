import os
import json
import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime
from groq import Groq

class MemoryManager:
    def __init__(self):
        # Short-term memory: list of {"role": "user"|"assistant", "content": "..."}
        self.short_term_memory = {} 
        
        # Long-term memory: ChromaDB
        self.chroma_client = chromadb.PersistentClient(path="./chroma_db")
        
        # Use a simple embedding function (or a better one if available)
        # For simplicity/speed in this prototype, we rely on Chroma's default or a lightweight one.
        # Ideally, use a local model or an API based embedding if Groq supports it (Groq doesn't do embeddings yet natively usually, so we might use a placeholder or a lightweight local lib).
        # We will use the default SentenceTransformer built-in to Chroma for now.
        self.collection = self.chroma_client.get_or_create_collection(name="soulmate_memories")
        
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model_fast = "llama-3.1-8b-instant"

    def get_context(self, user_id: str, current_message: str):
        # 1. Get Short Term History (Last 5 turns)
        history = self.short_term_memory.get(user_id, [])
        short_term_str = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history[-5:]])
        
        # 2. Retrieve Long Term Memories (RAG)
        relevant_memories = self._retrieve_relevant(current_message)
        
        context_str = f"""
        [MEMÓRIA DE CURTO PRAZO]
        {short_term_str}
        
        [MEMÓRIA DE LONGO PRAZO (FATOS RELEVANTES)]
        {relevant_memories}
        """
        return context_str

    def save_turn(self, user_id: str, user_msg: str, bot_msg: str):
        if user_id not in self.short_term_memory:
            self.short_term_memory[user_id] = []
            
        # Update Short Term
        self.short_term_memory[user_id].append({"role": "user", "content": user_msg})
        self.short_term_memory[user_id].append({"role": "assistant", "content": bot_msg})
        
        # Trim Short Term (Keep last 10 messages max)
        if len(self.short_term_memory[user_id]) > 10:
            self.short_term_memory[user_id] = self.short_term_memory[user_id][-10:]
            
        # Async/Background: Extract and Save Facts from User Message
        # In a real app, this should be a background task (Celery/RQ)
        self._extract_and_save_facts(user_msg)

    def _retrieve_relevant(self, query: str):
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=3
            )
            
            if not results['documents'][0]:
                return "Nenhuma memória relevante encontrada."
                
            # Format: "- [Fato] (Tags)"
            formatted = []
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                # Only show if importance is high enough or distance is low (omitted for simplicity)
                formatted.append(f"- {doc}")
                
            return "\n".join(formatted)
        except Exception as e:
            print(f"Error retrieving memory: {e}")
            return ""

    def _extract_and_save_facts(self, text: str):
        # Ask LLM to extract facts
        prompt = f"""
        Extraia fatos atômicos, preferências ou eventos emocionais importantes da mensagem abaixo.
        Se não houver nada digno de nota (apenas "oi", "tudo bem"), retorne uma lista vazia.
        
        Retorne APENAS um JSON: {{"facts": [{{"content": "...", "tags": ["..."], "importance": 0.0-1.0}}]}}
        
        Mensagem: "{text}"
        """
        
        try:
            completion = self.groq_client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_fast,
                temperature=0,
                response_format={"type": "json_object"}
            )
            data = json.loads(completion.choices[0].message.content)
            
            for fact in data.get('facts', []):
                if fact['importance'] > 0.6: # Only save important stuff
                    self._store_fact(fact)
        except Exception as e:
            print(f"Error extracting facts: {e}")

    def _store_fact(self, fact):
        # Generate ID
        fact_id = f"mem_{datetime.now().timestamp()}"
        
        self.collection.add(
            documents=[fact['content']],
            metadatas=[{"tags": ",".join(fact['tags']), "importance": fact['importance'], "timestamp": str(datetime.now())}],
            ids=[fact_id]
        )
        print(f"Saved Memory: {fact['content']}")
