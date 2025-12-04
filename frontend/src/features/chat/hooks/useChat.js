import { useState, useEffect, useRef } from 'react';
import { sendMessage } from '../services/chatService';
import { SYSTEM_MESSAGES } from '../constants';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const useChat = (userId) => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [emotionState, setEmotionState] = useState(null);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    // Fetch history on mount or when userId changes
    useEffect(() => {
        if (!userId) return;

        const fetchHistory = async () => {
            try {
                const response = await fetch(`${API_URL}/history/${userId}`);
                if (response.ok) {
                    const history = await response.json();
                    // Map backend format to frontend format if needed
                    // Backend returns: [{role: 'user', content: '...'}, ...]
                    setMessages(history);
                }
            } catch (error) {
                console.error("Failed to fetch history:", error);
            }
        };

        fetchHistory();
    }, [userId]);

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
            const data = await sendMessage(userId, userMessageText);

            const botMessage = { role: 'assistant', content: data.response };
            setMessages(prev => [...prev, botMessage]);

            if (data.emotion_state) {
                setEmotionState(data.emotion_state);
            }
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
