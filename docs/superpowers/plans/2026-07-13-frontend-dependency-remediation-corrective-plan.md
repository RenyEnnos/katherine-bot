# Remediação de Dependências e Gate de CI — Plano Corretivo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir a resolução de picomatch/minimatch, refatorar o gate do `npm audit` para um validador estrutural rigoroso e adicionar testes automatizados obrigatórios de CI (incluindo o smoke test do Axios).

**Architecture:** 
- Substituição do override global de picomatch por overrides específicos por dependência.
- Extração do script de validação de auditoria para `frontend/scripts/audit-validator.js`.
- Criação de testes unitários para o validador usando o test runner nativo do Node.js.
- Refatoração sutil do interceptor do Axios para permitir injeção de dependência e testes herméticos.
- Adição de script de teste de CI.

**Tech Stack:** Node.js, npm, Axios, Vite, jq, native Node.js test runner (`node:test`, `node:assert`).

## Global Constraints

- Ramo atual: `fix/frontend-dependency-audit`
- Manter o PR #244 aberto contra `main`. Não abrir novo PR.
- Não utilizar `npm audit fix --force`.
- Não alterar contratos emocionais ou redesign de telas.
- Não editar `.Jules/palette.md`.

---

### Task 1: Correção dos Overrides do Picomatch e Minimatch

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Consumes: N/A
- Produces: Resolução sem conflitos de picomatch e minimatch nas árvores de dependência.

- [ ] **Step 1: Modificar o package.json do frontend**
  
  Editar `frontend/package.json` para substituir os overrides globais por overrides específicos:
  - Remover `"picomatch": "^2.3.2"` do bloco global de `overrides`.
  - Adicionar overrides de `picomatch` direcionados aos consumidores 2.x e 4.x.
  - Verificar e manter o override global de `minimatch` apenas para `eslint` e seus plugins (que aceitam 3.x).
  
  O bloco de overrides em `frontend/package.json` deve ficar exatamente assim:
  ```json
  "overrides": {
      "minimatch": "^3.1.5",
      "micromatch": {
          "picomatch": "^2.3.2"
      },
      "anymatch": {
          "picomatch": "^2.3.2"
      },
      "readdirp": {
          "picomatch": "^2.3.2"
      },
      "tinyglobby": {
          "picomatch": "^4.0.5"
      },
      "vite": {
          "picomatch": "^4.0.5"
      }
  }
  ```

- [ ] **Step 2: Re-instalar dependências limpamente**
  
  Run: `rm -rf frontend/node_modules frontend/package-lock.json && npm install --prefix frontend`
  Expected: Instalação bem-sucedida e regeneração do novo `package-lock.json` com overrides direcionados aplicados.

- [ ] **Step 3: Validar a instalação e resolução**
  
  Executar validações estruturais para garantir que não há erros de dependências órfãs ou inválidas:
  Run: `npm ls picomatch minimatch --prefix frontend`
  Expected: Nenhuma dependência `invalid` ou `extraneous`. Vite resolve Picomatch 4.x, e micromatch resolve Picomatch 2.x de forma segura.

- [ ] **Step 4: Executar testes, lint e build atuais**
  
  Run: `npm run lint --prefix frontend && npm run build --prefix frontend`
  Expected: Build do Vite e lint passam perfeitamente.

- [ ] **Step 5: Commitar modificações dos pacotes**
  
  Run:
  ```bash
  git add frontend/package.json frontend/package-lock.json
  git commit -m "chore(frontend): refine package overrides for picomatch and minimatch"
  ```

---

### Task 2: Implementação do Audit Validator Script e Modificação da CI

**Files:**
- Create: `frontend/scripts/audit-validator.js`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: JSON do relatório do `npm audit` e exit code do comando audit.
- Produces: Execução limpa do validador retornando 0 se passar na política, ou códigos de erro específicos caso contrário.

- [ ] **Step 1: Criar o script audit-validator.js**
  
  Escrever o script `frontend/scripts/audit-validator.js` com suporte a execução CLI e exportação da função pure `validateAudit`:
  ```javascript
  import fs from 'fs';
  import { fileURLToPath } from 'url';

  export function validateAudit(fileContent, auditExitCode) {
    const exitCode = parseInt(auditExitCode, 10);
    if (isNaN(exitCode) || (exitCode !== 0 && exitCode !== 1)) {
      throw { message: `OPERATIONAL_ERROR: npm audit exited with unexpected exit code: ${auditExitCode}`, code: 4 };
    }

    let data;
    try {
      data = JSON.parse(fileContent);
    } catch (err) {
      throw { message: `INVALID_STRUCTURE: Audit report contains invalid JSON: ${err.message}`, code: 3 };
    }

    if (!data || typeof data !== 'object') {
      throw { message: 'INVALID_STRUCTURE: Audit report is not an object', code: 5 };
    }

    if (!data.metadata || typeof data.metadata !== 'object' || data.metadata === null) {
      throw { message: 'INVALID_STRUCTURE: .metadata is missing or not an object', code: 5 };
    }

    const vulnerabilities = data.metadata.vulnerabilities;
    if (!vulnerabilities || typeof vulnerabilities !== 'object' || vulnerabilities === null) {
      throw { message: 'INVALID_STRUCTURE: .metadata.vulnerabilities is missing, null, or not an object', code: 5 };
    }

    const severities = ['info', 'low', 'moderate', 'high', 'critical'];
    const allKeys = [...severities, 'total'];

    for (const key of allKeys) {
      if (!(key in vulnerabilities)) {
        throw { message: `INVALID_STRUCTURE: Vulnerability count for '${key}' is missing`, code: 5 };
      }
      const val = vulnerabilities[key];
      if (val === null || typeof val !== 'number' || !Number.isInteger(val) || val < 0) {
        throw { message: `INVALID_STRUCTURE: Vulnerability count for '${key}' is invalid (value: ${val})`, code: 5 };
      }
    }

    const sum = severities.reduce((acc, key) => acc + vulnerabilities[key], 0);
    if (vulnerabilities.total !== sum) {
      throw { message: `INVALID_STRUCTURE: Total count (${vulnerabilities.total}) does not match sum of severities (${sum})`, code: 5 };
    }

    if (vulnerabilities.high > 0 || vulnerabilities.critical > 0) {
      throw { message: `SECURITY_POLICY_VIOLATION: Found ${vulnerabilities.high} high and ${vulnerabilities.critical} critical vulnerabilities`, code: 6 };
    }

    return vulnerabilities;
  }

  const isMain = process.argv[1] && (
    process.argv[1] === fileURLToPath(import.meta.url) ||
    process.argv[1].endsWith('audit-validator.js')
  );

  if (isMain) {
    try {
      const filePath = process.argv[2];
      const auditExitCodeStr = process.argv[3];

      if (!filePath || auditExitCodeStr === undefined) {
        console.error('Usage: node audit-validator.js <path_to_audit.json> <audit_exit_code>');
        process.exit(2);
      }

      if (!fs.existsSync(filePath)) {
        console.error(`OPERATIONAL_ERROR: Audit report file is missing at: ${filePath}`);
        process.exit(2);
      }

      const fileContent = fs.readFileSync(filePath, 'utf8');
      validateAudit(fileContent, auditExitCodeStr);

      console.log('Auditoria passou com sucesso!');
      process.exit(0);
    } catch (err) {
      console.error(err.message || err);
      process.exit(err.code || 1);
    }
  }
  ```

- [ ] **Step 2: Modificar o workflow de CI**
  
  Editar `.github/workflows/ci.yml` para invocar o script de validação de auditoria ao invés do script bash inline:
  ```yaml
      - name: Audit dependencies
        working-directory: ./frontend
        run: |
          set +e
          npm audit --json > audit.json
          audit_exit=$?
          set -e
          echo "npm audit finalizado com exit code: $audit_exit"
          node scripts/audit-validator.js audit.json $audit_exit
  ```

- [ ] **Step 3: Commitar script de validação e modificações da CI**
  
  Run:
  ```bash
  git add frontend/scripts/audit-validator.js .github/workflows/ci.yml
  git commit -m "ci: replace inline audit shell script with dedicated node validator"
  ```

---

### Task 3: Implementação de Testes para o Audit Validator

**Files:**
- Create: `frontend/tests/audit-validator.test.js`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: `frontend/scripts/audit-validator.js`
- Produces: Resultados de testes demonstrando a robustez do validador frente aos 12 cenários obrigatórios.

- [ ] **Step 1: Criar o arquivo de testes do validador**
  
  Escrever `frontend/tests/audit-validator.test.js` cobrindo todos os cenários usando `node:test` e `node:assert`:
  ```javascript
  import { test } from 'node:test';
  import assert from 'node:assert';
  import { validateAudit } from '../scripts/audit-validator.js';

  const createReport = (vulns) => JSON.stringify({
    metadata: {
      vulnerabilities: {
        info: 0,
        low: 0,
        moderate: 0,
        high: 0,
        critical: 0,
        total: 0,
        ...vulns
      }
    }
  });

  test('relatório limpo com exit code 0', () => {
    const report = createReport({});
    const result = validateAudit(report, 0);
    assert.strictEqual(result.total, 0);
  });

  test('relatório apenas com baixa/moderada e exit code 1', () => {
    const report = createReport({ low: 2, moderate: 3, total: 5 });
    const result = validateAudit(report, 1);
    assert.strictEqual(result.total, 5);
  });

  test('vulnerabilidade alta', () => {
    const report = createReport({ high: 1, total: 1 });
    assert.throws(() => validateAudit(report, 1), (err) => {
      return err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION');
    });
  });

  test('vulnerabilidade crítica', () => {
    const report = createReport({ critical: 1, total: 1 });
    assert.throws(() => validateAudit(report, 1), (err) => {
      return err.code === 6 && err.message.includes('SECURITY_POLICY_VIOLATION');
    });
  });

  test('exit code operacional inesperado', () => {
    const report = createReport({});
    assert.throws(() => validateAudit(report, 2), (err) => {
      return err.code === 4 && err.message.includes('OPERATIONAL_ERROR');
    });
  });

  test('JSON inválido', () => {
    assert.throws(() => validateAudit('invalid json text', 0), (err) => {
      return err.code === 3 && err.message.includes('INVALID_STRUCTURE');
    });
  });

  test('.metadata.vulnerabilities ausente', () => {
    const report = JSON.stringify({ metadata: {} });
    assert.throws(() => validateAudit(report, 0), (err) => {
      return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
    });
  });

  test('objeto de vulnerabilidades vazio', () => {
    const report = JSON.stringify({ metadata: { vulnerabilities: {} } });
    assert.throws(() => validateAudit(report, 0), (err) => {
      return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
    });
  });

  test('uma contagem ausente', () => {
    const report = JSON.stringify({
      metadata: {
        vulnerabilities: {
          info: 0,
          low: 0,
          moderate: 0,
          high: 0,
          total: 0
          // critical missing
        }
      }
    });
    assert.throws(() => validateAudit(report, 0), (err) => {
      return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
    });
  });

  test('contagem null, string, negativa ou fracionária', () => {
    const cases = [
      { info: null, total: 0 },
      { info: '2', total: 2 },
      { info: -1, total: -1 },
      { info: 1.5, total: 1.5 }
    ];
    for (const c of cases) {
      const report = JSON.stringify({ metadata: { vulnerabilities: { low: 0, moderate: 0, high: 0, critical: 0, total: 0, ...c } } });
      assert.throws(() => validateAudit(report, 0), (err) => {
        return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
      });
    }
  });

  test('total inconsistente', () => {
    const report = createReport({ low: 1, total: 5 });
    assert.throws(() => validateAudit(report, 1), (err) => {
      return err.code === 5 && err.message.includes('INVALID_STRUCTURE');
    });
  });
  ```

- [ ] **Step 2: Configurar o script de teste no package.json**
  
  Editar `frontend/package.json` para definir o script de execução dos testes:
  ```json
  "scripts": {
      "dev": "vite",
      "build": "vite build",
      "lint": "eslint .",
      "preview": "vite preview",
      "test": "node --test tests/*.test.js"
  }
  ```

- [ ] **Step 3: Adicionar a execução de testes no workflow de CI**
  
  Editar `.github/workflows/ci.yml` para rodar `npm test` antes dos steps de `Lint` e `Build`:
  ```yaml
      - name: Run Tests
        working-directory: ./frontend
        run: npm test
  ```

- [ ] **Step 4: Rodar localmente e commitar**
  
  Run: `npm test --prefix frontend`
  Expected: Todos os 12 testes unitários passam com sucesso.
  
  Run:
  ```bash
  git add frontend/tests/audit-validator.test.js frontend/package.json .github/workflows/ci.yml
  git commit -m "test(frontend): implement comprehensive unit tests for audit-validator"
  ```

---

### Task 4: Refatoração e Smoke Test Automatizado do Interceptor do Axios

**Files:**
- Modify: `frontend/src/shared/services/apiClient.js`
- Modify: `frontend/src/lib/supabaseClient.js`
- Create: `frontend/tests/apiClient.test.js`

**Interfaces:**
- Consumes: `frontend/src/shared/services/apiClient.js`
- Produces: Testes herméticos (offline) demonstrando o comportamento correto do interceptor de autenticação com e sem token.

- [ ] **Step 1: Ajustar o supabaseClient.js para não falhar sem as variáveis de ambiente em testes**
  
  Editar `frontend/src/lib/supabaseClient.js` para usar optional chaining e evitar falhas de inicialização em ambiente de testes:
  ```javascript
  import { createClient } from '@supabase/supabase-js';

  const supabaseUrl = import.meta.env?.VITE_SUPABASE_URL;
  const supabaseAnonKey = import.meta.env?.VITE_SUPABASE_ANON_KEY;

  if (!supabaseUrl || !supabaseAnonKey) {
      if (process.env.NODE_ENV !== 'test') {
          throw new Error('Missing Supabase environment variables');
      }
  }

  export const supabase = (supabaseUrl && supabaseAnonKey) 
      ? createClient(supabaseUrl, supabaseAnonKey) 
      : null;
  ```

- [ ] **Step 2: Refatorar o apiClient.js para permitir injeção**
  
  Editar `frontend/src/shared/services/apiClient.js` para expor a função de configuração do interceptor separada, permitindo injeção de instâncias mocks no teste:
  ```javascript
  import axios from 'axios';
  import { supabase } from '../../lib/supabaseClient';

  const API_BASE_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || 'http://localhost:8000';

  export function setupRequestInterceptor(apiInstance, supabaseClient) {
      apiInstance.interceptors.request.use(async (config) => {
          if (supabaseClient) {
              const { data: { session } } = await supabaseClient.auth.getSession();
              if (session?.access_token) {
                  config.headers.Authorization = `Bearer ${session.access_token}`;
              }
          }
          return config;
      }, (error) => {
          return Promise.reject(error);
      });
  }

  const api = axios.create({
      baseURL: API_BASE_URL,
      headers: {
          'Content-Type': 'application/json',
      },
  });

  setupRequestInterceptor(api, supabase);

  export default api;
  ```

- [ ] **Step 3: Escrever o teste unitário apiClient.test.js**
  
  Criar `frontend/tests/apiClient.test.js` com testes herméticos sem rede usando `node:test` e `node:assert`:
  ```javascript
  import { test } from 'node:test';
  import assert from 'node:assert';
  import axios from 'axios';
  import { setupRequestInterceptor } from '../src/shared/services/apiClient.js';

  test('comportamento do interceptor com token de sessão ativo', async () => {
    // Instância fictícia do axios
    const apiInstance = axios.create();
    
    // Mock do supabaseClient
    const mockSupabase = {
      auth: {
        getSession: async () => ({
          data: {
            session: { access_token: 'mock-token-12345' }
          }
        })
      }
    };
    
    setupRequestInterceptor(apiInstance, mockSupabase);
    
    // Simula a interceptação de request
    const handler = apiInstance.interceptors.request.handlers[0].fulfilled;
    const config = { headers: {} };
    const resultConfig = await handler(config);
    
    assert.strictEqual(resultConfig.headers.Authorization, 'Bearer mock-token-12345');
  });

  test('comportamento do interceptor sem token de sessão (ou deslogado)', async () => {
    const apiInstance = axios.create();
    const mockSupabase = {
      auth: {
        getSession: async () => ({
          data: { session: null }
        })
      }
    };
    
    setupRequestInterceptor(apiInstance, mockSupabase);
    
    const handler = apiInstance.interceptors.request.handlers[0].fulfilled;
    const config = { headers: {} };
    const resultConfig = await handler(config);
    
    assert.strictEqual(resultConfig.headers.Authorization, undefined);
  });
  ```

- [ ] **Step 4: Executar e validar os testes locais**
  
  Run: `NODE_ENV=test npm test --prefix frontend`
  Expected: Todos os testes de validador de auditoria e interceptor do Axios passam (14 testes no total).

- [ ] **Step 5: Commitar testes e refatorações**
  
  Run:
  ```bash
  git add frontend/src/shared/services/apiClient.js frontend/src/lib/supabaseClient.js frontend/tests/apiClient.test.js
  git commit -m "test(frontend): implement offline unit tests for axios authorization interceptor"
  ```

---

### Task 5: Validação Geral da Pipeline e Atualização de Descrição do PR

**Files:**
- Modify: N/A

**Interfaces:**
- Consumes: N/A
- Produces: CI verde e descrição do PR atualizada no GitHub.

- [ ] **Step 1: Rodar suite do backend**
  
  Run: `PYTHONPATH=. .venv/bin/pytest backend/tests`
  Expected: Todos os 82 testes do backend continuam passando com sucesso.

- [ ] **Step 2: Rodar auditoria com o novo script**
  
  Executar localmente e validar que o script aceita o relatório atual:
  Run: `npm audit --prefix frontend --json > frontend/audit.json && node frontend/scripts/audit-validator.js frontend/audit.json $?`
  Expected: Imprime "Auditoria passou com sucesso!" e sai com exit code 0.
  
  Limpeza:
  Run: `rm frontend/audit.json`
  Expected: Arquivo temporário excluído.

- [ ] **Step 3: Atualizar a descrição da PR #244 no GitHub**
  
  Atualizar o corpo da PR para incluir a lista de testes versionados na pasta `frontend/tests/`.
  Run: `gh pr edit 244 --body-file .superpowers/sdd/pr-body.md` (ajustar o pr-body.md primeiro com os testes unitários adicionados)
