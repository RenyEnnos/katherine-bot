import { useState, useEffect, useRef } from 'react';
import { sendMessage } from '../services/chatService';
import api from '../../../shared/services/apiClient';
import { SYSTEM_MESSAGES } from '../constants';
import { validateEmotionState } from '../../../shared/utils/formatters';

export const useChat = () => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [emotionState, setEmotionState] = useState(null);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    useEffect(() => {
        const fetchHistory = async () => {
            try {
                // api.get uses the interceptor to add the Bearer token automatically
                const response = await api.get('/history');
                setMessages(response.data);
            } catch (error) {
                console.error("Failed to fetch history:", error);
            }
        };

        fetchHistory();
    }, []);

    // Auto-scroll to bottom
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, isLoading]);

    const handleSend = async () => {
        if (!input.trim() || isLoading) return;

        const userMessageText = input.trim();
        const newUserMessage = { role: 'user', content: userMessageText };

        // Optimistic update
        setMessages(prev => [...prev, newUserMessage]);
        setInput('');
        setIsLoading(true);

        try {
            const data = await sendMessage(userMessageText);

            const botMessage = { role: 'assistant', content: data.response };
            setMessages(prev => [...prev, botMessage]);

            // Always validate emotion_state: clear panel on invalid or missing contract
            const validated = validateEmotionState(data.emotion_state);
            setEmotionState(validated);
        } catch (error) {
            // Error handling
            const errorMessage = {
                role: 'system',
                content: SYSTEM_MESSAGES.ERROR_SENDING
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
            // Focus back on input
            setTimeout(() => inputRef.current?.focus(), 100);
        }
    };

    const clearHistory = () => {
        setMessages([]);
        setEmotionState(null);
        // Ideally, we should also call an API endpoint to clear history in backend if desired
    };

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
