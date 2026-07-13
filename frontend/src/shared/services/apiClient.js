import axios from 'axios';
import { supabase } from '../../lib/supabaseClient.js';

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
