# Arquitetura de Memória Híbrida para LLMs (Foco: Eficiência e Emoção)

Este documento define a arquitetura de memória para o Chatbot "Katherine", focando em consumo mínimo de tokens (Groq API) e profundidade emocional.

## 1. Modelo Conceitual de Três Camadas

O sistema opera com um funil de informação para garantir que apenas o essencial chegue ao prompt.

1.  **Memória Imediata (Buffer de Contexto)**
    *   **O que é:** As últimas 4-6 mensagens (trocas diretas) em seu formato original.
    *   **Função:** Manter a fluidez imediata, referências a "isso/aquilo" e coerência gramatical.
    *   **Gestão:** Janela deslizante estrita (FIFO).

2.  **Memória de Trabalho (Resumo de Sessão)**
    *   **O que é:** Um parágrafo único e denso (max 50-80 tokens) descrevendo o estado atual da conversa e o "humor" do usuário.
    *   **Função:** Dar contexto ao que aconteceu 10 minutos atrás sem gastar tokens com o diálogo bruto.
    *   **Atualização:** Atualizado a cada 3-5 trocas de mensagens por uma chamada assíncrona (background).

3.  **Memória de Longo Prazo (LTM - External Storage)**
    *   **O que é:** Banco de dados (Vetorial + Palavras-chave) contendo "fatos atômicos" e "padrões emocionais".
    *   **Função:** Retenção infinita de preferências, biografia e evolução emocional.
    *   **Acesso:** Apenas via Retrieval (RAG) sob demanda.

---

## 2. Regras de Armazenamento (Gatilhos de Memória)

Não salvamos tudo. O sistema deve agir como um "filtro de relevância".

**Salvar na LTM SE:**
1.  **Fato Explícito:** O usuário declara uma preferência ou dado biográfico.
    *   *Ex:* "Meu nome é Pedro", "Sou vegetariano", "Tenho 30 anos".
2.  **Objetivo/Intenção:** O usuário define uma meta de longo prazo.
    *   *Ex:* "Quero aprender a programar este ano".
3.  **Padrão Emocional Recorrente:** O sistema detecta uma reação forte ou repetitiva.
    *   *Ex:* Usuário demonstra ansiedade sempre que fala de prazos.
4.  **Evento Marcante:** Um acontecimento significativo na vida do usuário.
    *   *Ex:* "Fui demitido hoje", "Nasceu meu filho".

**NÃO Salvar:**
*   Comentários triviais ("O tempo está bom").
*   Dúvidas momentâneas já resolvidas.
*   Cumprimentos e cortesias.

---

## 3. Formato de Armazenamento Ultra-Compacto

Para economizar espaço em disco e, crucialmente, tokens na injeção do prompt, usamos chaves minificadas e valores diretos.

**Estrutura JSON Sugerida:**

```json
{
  "i": "uuid_curto",      // ID
  "t": "bio",             // Tipo: bio (biografia), pref (preferência), emo (emocional), obj (objetivo)
  "c": "nome: Pedro",     // Conteúdo: Fato atômico e direto
  "w": 0.9,               // Peso/Importância (0.0 a 1.0)
  "d": "240101"           // Data compacta (AAMMDD)
}
```

**Exemplos de Entradas:**
*   `{"t":"pref", "c":"odeia coentro", "w":0.8}`
*   `{"t":"emo", "c":"ansioso com finanças", "w":0.9}`
*   `{"t":"bio", "c":"trabalha: dev frontend", "w":1.0}`

---

## 4. Estratégias de Compressão e Manutenção

O "Jardineiro de Memória" roda em background para manter o banco limpo.

1.  **Deduplicação Semântica (Merge):**
    *   Ao inserir "Não gosto de carne", se já existir "Sou vegetariano", o sistema detecta redundância.
    *   *Ação:* Manter o mais abrangente ou fundir: "Vegetariano (reforçado em 240101)".

2.  **Decaimento por Relevância (Decay):**
    *   Memórias do tipo "emo" (emocional) perdem 0.1 de peso a cada semana se não forem reforçadas.
    *   Se `w < 0.3`, a memória é arquivada/deletada ("esquecimento natural").
    *   Memórias "bio" (biográficas) não decaem (peso fixo 1.0).

3.  **Resuarização Extrema:**
    *   Em vez de guardar "O usuário disse que na semana passada foi ao parque e não gostou porque estava cheio", guarde:
    *   `{"t":"pref", "c":"evita lugares lotados", "w":0.7}`

---

## 5. Fluxo de Recuperação (Retrieval Otimizado)

Objetivo: Injetar no prompt apenas o que importa para *esta* resposta.

1.  **Análise da Mensagem (Query Gen):**
    *   Usuário: "O que você sugere pro meu jantar hoje?"
    *   Extração de Tópicos: `jantar`, `comida`, `preferências alimentares`.

2.  **Busca Híbrida:**
    *   Busca Vetorial por "jantar/comida".
    *   Filtro por `t:pref` ou `t:bio`.

3.  **Seleção e Ranking:**
    *   Recupera top 10 candidatos.
    *   Reordena por: `Score Vetorial * Peso (w) * Recência`.
    *   Corta para os top 3-5 resultados.

4.  **Injeção no Prompt (Formato Final):**
    *   Não jogue o JSON. Formate como uma lista compacta de fatos.

    ```text
    [MEMÓRIA]
    - Vegetariano; odeia coentro.
    - Está de dieta (low carb).
    - Ansioso hoje (trate com calma).
    ```

---

## 6. Prompts Internos (System Prompts)

### A. Prompt de Extração (Background)
*Usado para analisar a conversa e criar novas memórias.*

```text
Analise a msg do usuário. Extraia fatos novos, preferências ou estados emocionais importantes.
Saída APENAS JSON minificado (lista). Se nada relevante, retorne [].
Formato: {"t": "tipo", "c": "fato curto", "w": 0.0-1.0}
Tipos: bio, pref, emo, obj.
Texto: "{user_message}"
```

### B. Prompt de Resumo de Memória de Trabalho (Background)
*Usado para atualizar o resumo da sessão.*

```text
Resuma a conversa atual em 1 frase densa. Foque no objetivo atual e estado emocional.
Atual: "{resumo_anterior}"
Novas msgs: "{buffer_recente}"
Saída (max 30 palavras):
```

### C. Prompt Principal (Injeção de Contexto)
*O prompt que gera a resposta final.*

```text
Você é Katherine.
[MEMÓRIA DE LONGO PRAZO]
{memoria_recuperada_formatada} // Ex: - Vegetariano. - Gosta de Sci-Fi.

[CONTEXTO ATUAL]
{resumo_sessao} // Ex: Usuário discutindo refatoração de código, levemente frustrado.

[HISTÓRICO RECENTE]
{buffer_mensagens}

Responda de forma natural, usando a memória para personalizar, mas sem ser repetitiva.
```
