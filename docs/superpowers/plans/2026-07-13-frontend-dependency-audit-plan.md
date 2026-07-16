# Remediação de Vulnerabilidades do Frontend e Gate de Auditoria na CI — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar vulnerabilidades conhecidas diretas e transitivas do frontend com upgrades estáveis e estruturar um gate de auditoria resiliente na CI que previna regressões sem mascarar falhas operacionais.

**Architecture:** Abordagem A (Upgrades diretos de Axios, PostCSS, Vite + Overrides de transitivos no package.json + script de verificação na pipeline de CI usando jq).

**Tech Stack:** Node.js, npm, Axios, PostCSS, Vite, jq, Bash.

## Global Constraints

- Ramo de origem: `main` atualizado contendo `7bbc122cf2870734203b343731a87986f62400ee`.
- Ramo de entrega: `fix/frontend-dependency-audit`.
- Não utilizar `npm audit fix --force`.
- Não alterar contratos emocionais ou redesign de telas.
- Não editar `.Jules/palette.md`.

---

### Task 1: Atualização de Dependências e Regeneração do Lockfile

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes: N/A
- Produces: package-lock.json atualizado e limpo de vulnerabilidades altas/críticas.

- [ ] **Step 1: Modificar o package.json do frontend**
  
  Editar o arquivo `frontend/package.json` para atualizar as versões e incluir overrides para dependências transitivas.

  Substituir as dependências correspondentes por:
  ```json
  "dependencies": {
      "@supabase/auth-ui-react": "^0.4.7",
      "@supabase/auth-ui-shared": "^0.1.8",
      "@supabase/supabase-js": "^2.110.3",
      "axios": "^1.18.1",
      "lucide-react": "^0.292.0",
      "react": "^18.2.0",
      "react-dom": "^18.2.0",
      "react-markdown": "^9.0.0"
  },
  "devDependencies": {
      "@types/react": "^18.2.37",
      "@types/react-dom": "^18.2.15",
      "@vitejs/plugin-react": "^4.3.4",
      "autoprefixer": "^10.4.16",
      "eslint": "^8.53.0",
      "eslint-plugin-react": "^7.33.2",
      "eslint-plugin-react-hooks": "^4.6.0",
      "eslint-plugin-react-refresh": "^0.4.4",
      "postcss": "^8.5.19",
      "tailwindcss": "^3.3.5",
      "vite": "^6.4.3"
  },
  "overrides": {
      "minimatch": "^3.1.5",
      "picomatch": "^2.3.2",
      "tinyglobby": {
          "picomatch": "^4.0.5"
      }
  }
  ```

- [ ] **Step 2: Remover o lockfile e node_modules antigos e realizar instalação limpa**
  
  Executar no terminal para forçar a regeneração do lockfile sem dependências antigas:
  Run: `rm -rf frontend/node_modules frontend/package-lock.json && npm install --prefix frontend`
  Expected: Instalação bem-sucedida e geração do novo `frontend/package-lock.json`.

- [ ] **Step 3: Validar a instalação limpa via npm ci**
  
  Run: `npm ci --prefix frontend`
  Expected: Instalação rápida concluída com sucesso a partir do lockfile gerado.

- [ ] **Step 4: Executar lint e build do frontend**
  
  Run: `npm run lint --prefix frontend && npm run build --prefix frontend`
  Expected: Sem erros de ESLint e build de produção do Vite completada com sucesso.

- [ ] **Step 5: Rodar npm audit local para validar vulnerabilidades restantes**
  
  Run: `npm audit --prefix frontend --json`
  Expected: O relatório gerado não deve conter nenhuma vulnerabilidade com severidade `high` ou `critical`. Caso restem vulnerabilidades `moderate` ou `low`, verificar que estão justificadas e documentadas.

- [ ] **Step 6: Realizar commit**
  
  Run:
  ```bash
  git add frontend/package.json frontend/package-lock.json
  git commit -m "chore(frontend): upgrade dependencies and configure transitive overrides"
  ```

---

### Task 2: Smoke Test do Interceptor do Axios

**Files:**
- Create: `frontend/src/smoke-test-axios.js` (Será excluído ou movido para scratch após a execução)

**Interfaces:**
- Consumes: `frontend/src/shared/services/apiClient.js`
- Produces: Sucesso ou erro de execução indicando se o interceptor de autenticação com Supabase continua funcionando.

- [ ] **Step 1: Criar o script de smoke test para Axios**
  
  Escrever em `frontend/src/smoke-test-axios.js` um runner hermético em Node que valida a injeção do token no header da requisição do Axios:
  
  ```javascript
  import fs from 'fs';
  import path from 'path';
  import { fileURLToPath } from 'url';

  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  let code = fs.readFileSync(path.join(__dirname, './shared/services/apiClient.js'), 'utf8');

  // Ajusta o código do apiClient para rodar hermeticamente em Node
  code = code.replace(/import\.meta\.env/g, '{}');
  code = code.replace("import { supabase } from '../../lib/supabaseClient';", "export const supabase = { auth: { getSession: async () => ({ data: { session: { access_token: 'mock-token-12345' } } }) } };");

  // Salva temporariamente
  fs.writeFileSync(path.join(__dirname, './temp-apiClient.js'), code);

  (async () => {
      try {
          const module = await import('./temp-apiClient.js');
          const api = module.default;
          
          if (api.interceptors.request.handlers.length === 0) {
              throw new Error("Nenhum interceptor de request foi configurado!");
          }
          
          const handler = api.interceptors.request.handlers[0].fulfilled;
          const config = { headers: {} };
          const resultConfig = await handler(config);
          
          console.log("Config headers resultantes:", resultConfig.headers);
          if (resultConfig.headers.Authorization !== "Bearer mock-token-12345") {
              throw new Error("Authorization header não injetado corretamente!");
          }
          
          console.log("SUCCESS: Interceptor do Axios validado com sucesso!");
          fs.unlinkSync(path.join(__dirname, './temp-apiClient.js'));
          process.exit(0);
      } catch (err) {
          console.error("FAILURE:", err.message);
          try { fs.unlinkSync(path.join(__dirname, './temp-apiClient.js')); } catch(e) {}
          process.exit(1);
      }
  })();
  ```

- [ ] **Step 2: Executar o smoke test do Axios**
  
  Run: `node frontend/src/smoke-test-axios.js`
  Expected: Saída terminando com "SUCCESS: Interceptor do Axios validado com sucesso!" e exit code 0.

- [ ] **Step 3: Limpar o arquivo de smoke test**
  
  Run: `rm frontend/src/smoke-test-axios.js`
  Expected: Arquivo removido para manter o diretório `src` limpo.

- [ ] **Step 4: Commit de confirmação da validação**
  
  Não há arquivos a comitar (o teste foi deletado), mas podemos fazer um commit vazio ou apenas prosseguir.

---

### Task 3: Implementar Validação de Auditoria e Política na CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `frontend/test-ci-logic.sh` (Para teste local controlado, depois deletar)

**Interfaces:**
- Consumes: Relatório de auditoria gerado pelo `npm audit --json`.
- Produces: Workflow de CI protegido contra falhas operacionais e que falha ativamente em vulnerabilidades altas ou críticas.

- [ ] **Step 1: Modificar o step de auditoria no ci.yml**
  
  Editar `.github/workflows/ci.yml` na seção `frontend` para substituir a execução da auditoria pelo script resiliente:

  ```yaml
      - name: Audit dependencies
        working-directory: ./frontend
        run: |
          set +e
          npm audit --json > audit.json
          audit_exit=$?
          set -e
          
          echo "npm audit finalizado com exit code: $audit_exit"
          
          # 1. Validar se o arquivo audit.json existe
          if [ ! -f audit.json ]; then
            echo "ERRO: Relatório audit.json não foi gerado."
            exit 2
          fi
          
          # 2. Validar se contém JSON válido
          if ! jq empty audit.json 2>/dev/null; then
            echo "ERRO: O relatório audit.json não contém um JSON válido."
            echo "Conteúdo recebido:"
            cat audit.json
            exit 3
          fi
          
          # 3. Validar se o exit code é o esperado (0 ou 1)
          if [ "$audit_exit" -ne 0 ] && [ "$audit_exit" -ne 1 ]; then
            echo "ERRO OPERACIONAL: O npm audit falhou com exit code inesperado: $audit_exit"
            exit 4
          fi
          
          # 4. Validar se a chave .metadata.vulnerabilities existe
          if ! jq -e '.metadata.vulnerabilities' audit.json >/dev/null; then
            echo "ERRO: O campo .metadata.vulnerabilities está ausente no relatório."
            exit 5
          fi
          
          # 5. Aplicar política para vulnerabilidades altas e críticas
          high_vulns=$(jq '.metadata.vulnerabilities.high' audit.json)
          critical_vulns=$(jq '.metadata.vulnerabilities.critical' audit.json)
          
          echo "Vulnerabilidades encontradas:"
          jq '.metadata.vulnerabilities' audit.json
          
          if [ "$high_vulns" -gt 0 ] || [ "$critical_vulns" -gt 0 ]; then
            echo "ERRO: Foram encontradas $high_vulns vulnerabilidades altas e $critical_vulns críticas."
            exit 6
          fi
          
          echo "Auditoria passou com sucesso!"
  ```

- [ ] **Step 2: Criar script de validação controlada da lógica de CI**
  
  Escrever em `frontend/test-ci-logic.sh` o runner de simulação:
  ```bash
  #!/usr/bin/env bash
  
  # Função para rodar a lógica da CI usando um arquivo de auditoria simulado
  run_ci_logic() {
    local simulated_exit=$1
    local audit_file=$2
    
    # Executa a mesma lógica do ci.yml, adaptada para ler o arquivo simulado
    (
      audit_exit=$simulated_exit
      
      if [ ! -f "$audit_file" ]; then
        echo "ERRO: Relatório audit.json não foi gerado."
        exit 2
      fi
      
      if ! jq empty "$audit_file" 2>/dev/null; then
        echo "ERRO: O relatório audit.json não contém um JSON válido."
        exit 3
      fi
      
      if [ "$audit_exit" -ne 0 ] && [ "$audit_exit" -ne 1 ]; then
        echo "ERRO OPERACIONAL: O npm audit falhou com exit code inesperado: $audit_exit"
        exit 4
      fi
      
      if ! jq -e '.metadata.vulnerabilities' "$audit_file" >/dev/null; then
        echo "ERRO: O campo .metadata.vulnerabilities está ausente no relatório."
        exit 5
      fi
      
      high_vulns=$(jq '.metadata.vulnerabilities.high' "$audit_file")
      critical_vulns=$(jq '.metadata.vulnerabilities.critical' "$audit_file")
      
      if [ "$high_vulns" -gt 0 ] || [ "$critical_vulns" -gt 0 ]; then
        echo "ERRO: Foram encontradas $high_vulns vulnerabilidades altas e $critical_vulns críticas."
        exit 6
      fi
      
      echo "Auditoria passou com sucesso!"
      exit 0
    )
  }
  
  echo "=== Testando Cenário 1: Arquivo ausente ==="
  run_ci_logic 0 "nao_existe.json"
  echo "Exit code obtido: $? (Esperado: 2)"
  
  echo "=== Testando Cenário 2: JSON Inválido ==="
  echo "texto comum" > invalid.json
  run_ci_logic 0 "invalid.json"
  echo "Exit code obtido: $? (Esperado: 3)"
  
  echo "=== Testando Cenário 3: Exit code inesperado (ex: 2) ==="
  echo '{"metadata": {"vulnerabilities": {"high": 0, "critical": 0}}}' > valid.json
  run_ci_logic 2 "valid.json"
  echo "Exit code obtido: $? (Esperado: 4)"
  
  echo "=== Testando Cenário 4: Ausência de metadata ==="
  echo '{"foo": "bar"}' > no_meta.json
  run_ci_logic 0 "no_meta.json"
  echo "Exit code obtido: $? (Esperado: 5)"
  
  echo "=== Testando Cenário 5: Vulnerabilidades Altas/Críticas > 0 ==="
  echo '{"metadata": {"vulnerabilities": {"high": 1, "critical": 0}}}' > high_vuln.json
  run_ci_logic 1 "high_vuln.json"
  echo "Exit code obtido: $? (Esperado: 6)"
  
  echo "=== Testando Cenário 6: Tudo Ok (0 vulnerabilidades altas/críticas) ==="
  echo '{"metadata": {"vulnerabilities": {"high": 0, "critical": 0, "moderate": 2}}}' > ok.json
  run_ci_logic 1 "ok.json"
  echo "Exit code obtido: $? (Esperado: 0)"
  
  # Limpeza
  rm -f invalid.json valid.json no_meta.json high_vuln.json ok.json
  ```

- [ ] **Step 3: Executar o script de teste de lógica da CI**
  
  Run: `bash frontend/test-ci-logic.sh`
  Expected:
  - Cenário 1 retorna `2`
  - Cenário 2 retorna `3`
  - Cenário 3 retorna `4`
  - Cenário 4 retorna `5`
  - Cenário 5 retorna `6`
  - Cenário 6 retorna `0`

- [ ] **Step 4: Limpar o script de testes controlado**
  
  Run: `rm frontend/test-ci-logic.sh`
  Expected: O diretório volta ao estado limpo.

- [ ] **Step 5: Executar a CI localmente com o novo script**
  
  Executar o audit no frontend com a nossa lógica para comprovar que passa com o estado atual atualizado:
  Run:
  ```bash
  (
    cd frontend
    npm audit --json > audit.json
    audit_exit=$?
    high_vulns=$(jq '.metadata.vulnerabilities.high' audit.json)
    critical_vulns=$(jq '.metadata.vulnerabilities.critical' audit.json)
    echo "Altas: $high_vulns | Críticas: $critical_vulns | Exit: $audit_exit"
    [ "$high_vulns" -eq 0 ] && [ "$critical_vulns" -eq 0 ] && ([ "$audit_exit" -eq 0 ] || [ "$audit_exit" -eq 1 ])
  )
  ```
  Expected: Retorno com sucesso (exit code 0 da expressão), confirmando que a nossa base de código agora atende à política.

- [ ] **Step 6: Commit das alterações de CI**
  
  Run:
  ```bash
  git add .github/workflows/ci.yml
  git commit -m "ci: enforce strict and resilient npm audit gates"
  ```

---

### Task 4: Validação Geral e Execução Completa de Testes

**Files:**
- Modify: N/A

**Interfaces:**
- Consumes: Repositório com as correções integradas.
- Produces: Confirmação de que todas as suítes passam sem regressão.

- [ ] **Step 1: Executar testes de backend**
  
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests`
  Expected: Todos os testes do backend passam com sucesso.

- [ ] **Step 2: Executar auditoria, lint e build do frontend completos**
  
  Run: `npm ci --prefix frontend && npm run lint --prefix frontend && npm run build --prefix frontend`
  Expected: Instalação limpa, lint limpo e build concluídos com sucesso.

- [ ] **Step 3: Verificar status de git**
  
  Run: `git status`
  Expected: Apenas os arquivos `frontend/package.json`, `frontend/package-lock.json` e `.github/workflows/ci.yml` foram modificados no branch `fix/frontend-dependency-audit`.

- [ ] **Step 4: Mesclar se necessário ou documentar vulnerabilidades transitivas justificadas**
  
  Revisar se há vulnerabilidades de baixa/moderada severidade restantes e justificar na entrega se necessário.
