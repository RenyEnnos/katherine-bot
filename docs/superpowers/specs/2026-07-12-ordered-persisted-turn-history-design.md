# Design Spec — ordered-persisted-turn-history

Este documento especifica o design técnico para a remoção do estado de conversa mutável em memória e a persistência síncrona/leitura ordenada de histórico recente por usuário na Katherine Bot.

## Contexto e Problema
O `MemoryManager` armazena o histórico em um dicionário mutável no processo global (`self.short_term_memory`), o que viola a isolabilidade dos estados por usuário.
Adicionalmente, a gravação de turnos ocorria de forma assíncrona com `BackgroundTasks`, permitindo que locks de requisições subsequentes fossem liberados antes do término da persistência do turno anterior.

## Objetivos
1. Remover `MemoryManager.short_term_memory`.
2. Criar busca direta de histórico recente na tabela `chat_logs`.
3. Ordenar o histórico determinística e estavelmente usando `created_at` e a chave primária `id`.
4. Persistir o turno atual de forma síncrona dentro do lock do usuário, sem usar `BackgroundTasks`.
5. Validar todas as operações do Supabase lançando exceções higienizadas (`ContextLoadError` e `TurnPersistenceError`).
6. Eliminar código legado inativo (`_compress_episodes`, `_analyze_and_store`, `_store_memory`).

## Detalhamento Técnico

### Exceções Higienizadas
```python
class ContextLoadError(Exception):
    """Exceção levantada ao falhar no carregamento de contexto de mensagens recentes."""
    pass

class TurnPersistenceError(Exception):
    """Exceção levantada ao falhar na persistência do turno atual."""
    pass
```
*Garantia de Higienização*: Nenhuma exceção conterá dados sensíveis de usuários (mensagens, IDs, chaves de API).

### Consultas ao Banco de Dados (chat_logs)

#### Recuperação de Histórico
```python
response = self.supabase.table("chat_logs")\
    .select("role,content")\
    .eq("user_id", user_id)\
    .order("created_at", desc=True)\
    .order("id", desc=True)\
    .limit(limit)\
    .execute()
```
O retorno será invertido em memória para restabelecer a ordem cronológica ascendente.

#### Persistência do Turno
```python
response = self.supabase.table("chat_logs").insert([
    {"user_id": user_id, "role": "user", "content": user_msg},
    {"user_id": user_id, "role": "assistant", "content": bot_msg}
]).execute()
```
Será validado se `response` contém dados inseridos e se o tamanho do retorno é maior que zero.

### Sincronização e Locks
Em `backend/engine.py`, no método `process_turn`, a chamada a `save_turn` será feita via `asyncio.to_thread` e aguardada (`await`) diretamente dentro do escopo do lock `run_under_lock`.
`BackgroundTasks` do FastAPI não participará do caminho crítico da persistência de turnos.
