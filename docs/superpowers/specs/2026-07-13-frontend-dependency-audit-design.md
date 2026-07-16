# Especificação de Design — Correção de Vulnerabilidades do Frontend (#231)

Este documento especifica o design para a remediação de vulnerabilidades de dependências no frontend do Katherine Bot e a implementação de um gate rigoroso e resiliente na pipeline de CI.

## 1. Problema e Contexto

O frontend possui vulnerabilidades conhecidas em dependências diretas e transitivas importantes, incluindo `axios`, `postcss` e `vite`. Além disso, a pipeline de CI atual não possui uma validação granular do relatório do `npm audit`, o que pode mascarar falhas operacionais da ferramenta de auditoria ou aceitar vulnerabilidades críticas indevidamente.

## 2. Abordagem Proposta

### 2.1 Atualização de Dependências Diretas

Atualizaremos as seguintes dependências diretas para versões corrigidas e estáveis:
- **`axios`**: de `^1.6.0` para `^1.18.1` (corrige vulnerabilidades de Prototype Pollution, SSRF e CRLF).
- **`postcss`**: de `^8.4.31` para `^8.5.19`.
- **`vite`**: de `^5.0.0` para `^6.4.3`.
- **`@vitejs/plugin-react`**: de `^4.2.0` para `^4.3.4` (mantendo compatibilidade com o Vite 6).
- **`@supabase/supabase-js`**: de `^2.86.2` para `^2.110.3` (para resolver transitivamente a vulnerabilidade no `ws`).

### 2.2 Substituição de Transitivos via Overrides

Para sanar as vulnerabilidades em dependências transitivas que não são atualizadas pelas dependências diretas, utilizaremos a propriedade `overrides` do `npm` no `package.json`:
- **`minimatch`**: `^3.1.5` (usado por pacotes do ESLint).
- **`picomatch`**: `^2.3.2` (usado por micromatch/tailwindcss).
- **`tinyglobby > picomatch`**: `^4.0.5` (usado por tinyglobby/sucrase).

### 2.3 Resiliência e Política de Gate do `npm audit` na CI

O workflow de CI em `.github/workflows/ci.yml` será configurado para:
1. Executar o `npm audit` de forma que a CI capture falhas em sua execução, mas não ignore falhas operacionais inesperadas (como erro 500 do registry).
2. Verificar se o relatório `audit.json` foi gerado e se ele contém um JSON válido.
3. Verificar se o exit code do `npm audit` é `0` ou `1` (valores válidos que denotam execução bem-sucedida, com ou sem vulnerabilidades). Qualquer outro exit code causará a falha imediata da pipeline.
4. Validar se a chave `.metadata.vulnerabilities` está presente no JSON.
5. Impor a política de segurança: falhar se houver qualquer vulnerabilidade classificada como **alta** ou **crítica** em dependências diretas ou transitivas não justificadas.

## 3. Arquivos Afetados

- `frontend/package.json`
- `frontend/package-lock.json`
- `.github/workflows/ci.yml`

## 4. Plano de Testes

### 4.1 Testes Locais de Build e Lint
- Executar `npm ci` no diretório `frontend` para garantir uma instalação limpa e reprodutível.
- Executar `npm run lint` para garantir que as novas versões do ESLint e dependências não quebraram as regras de estilo.
- Executar `npm run build` para validar o empacotamento completo de produção com o Vite 6.

### 4.2 Testes da Política de CI
- Simulação local de falhas controladas do script de CI (arquivo ausente, JSON inválido, exit code inesperado, metadados ausentes, e violação da política de alta/crítica).

### 4.3 Smoke Test do Envio Autenticado pelo Axios
- Verificar o interceptor de autenticação no arquivo `apiClient.js` e comprovar que o cabeçalho `Authorization: Bearer <token>` está presente e correto.

## 5. Riscos e Mitigação

- **Risco de regressão na build devido ao upgrade do Vite**: Mitigado pelo uso de um `vite.config.js` extremamente simples, apenas com o plugin React oficial atualizado.
- **Risco de problemas de CORS/SSRF no Axios**: A suite completa de testes backend e frontend validará o comportamento de requisição.
