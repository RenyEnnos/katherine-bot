import { useState, useEffect, useRef, useCallback } from 'react';
import { sendMessage, ChatError } from '../services/chatService';
import api from '../../../shared/services/apiClient';
import { SYSTEM_MESSAGES } from '../constants';
import { validateEmotionState } from '../../../shared/utils/formatters';

/**
 * Hook for managing chat state with AbortController-based timeout.
 *
 * Each send creates a fresh AbortController. The timer is cleaned up on
 * success, error, cancellation, and unmount.
 */
export const useChat = () => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [emotionState, setEmotionState] = useState(null);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);
    const abortControllerRef = useRef(null);

    useEffect(() => {
        const fetchHistory = async () => {
            try {
                // api.get uses the interceptor to add the Bearer token automatically
                const response = await api.get('/history');
                if (Array.isArray(response.data)) {
                    setMessages(response.data);
                }
            } catch (error) {
                // History fetch failure is not critical — log sanitised
                if (process.env.NODE_ENV !== 'test') {
                    console.warn('Failed to fetch history');
                }
            }
        };

        fetchHistory();
    }, []);

    // Auto-scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isLoading]);

    // Cleanup abort controller on unmount
    useEffect(() => {
        return () => {
            abortControllerRef.current?.abort();
        };
    }, []);

    const handleSend = useCallback(async () => {
        if (!input.trim() || isLoading) return;

        const userMessageText = input.trim();
        const newUserMessage = { role: 'user', content: userMessageText };

        // Optimistic update
        setMessages(prev => [...prev, newUserMessage]);
        setInput('');
        setIsLoading(true);

        // Create fresh AbortController for this request
        const controller = new AbortController();
        abortControllerRef.current = controller;

        // Create timeout timer
        const timeoutMs = 50000;
        const timerId = setTimeout(() => {
            controller.abort();
        }, timeoutMs);

        try {
            const data = await sendMessage(userMessageText, {
                signal: controller.signal,
                timeout: timeoutMs,
            });

            // Clear timer on success
            clearTimeout(timerId);

            const botMessage = { role: 'assistant', content: data.response };
            setMessages(prev => [...prev, botMessage]);

            // Always validate emotion_state: clear panel on invalid or missing contract
            const validated = validateEmotionState(data.emotion_state);
            setEmotionState(validated);
        } catch (error) {
            // Clear timer on error/cancel
            clearTimeout(timerId);

            if (error instanceof ChatError) {
                const errorMessage = {
                    role: 'system',
                    content: error.message,
                };
                setMessages(prev => [...prev, errorMessage]);
            } else {
                // Unknown error — use safe default
                const errorMessage = {
                    role: 'system',
                    content: SYSTEM_MESSAGES.ERROR_SENDING,
                };
                setMessages(prev => [...prev, errorMessage]);
            }
        } finally {
            setIsLoading(false);
            abortControllerRef.current = null;
            // Focus back on input
            setTimeout(() => inputRef.current?.focus(), 100);
        }
    }, [input, isLoading]);

    const clearHistory = useCallback(() => {
        setMessages([]);
        setEmotionState(null);
    }, []);

    return {
        messages,
        input,
        setInput,
        isLoading,
        emotionState,
        messagesEndRef,
        inputRef,
        handleSend,
        clearHistory
    };
};
