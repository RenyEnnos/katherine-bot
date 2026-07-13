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
