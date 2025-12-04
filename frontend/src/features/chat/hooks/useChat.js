import { useState, useEffect, useRef } from 'react';
import { sendMessage } from '../services/chatService';
import { STORAGE_KEYS, SYSTEM_MESSAGES } from '../constants';
import { useLocalStorage } from '../../../shared/hooks/useLocalStorage';

export const useChat = () => {
    // Use useLocalStorage for persistence
    const [userId, setUserId] = useLocalStorage(STORAGE_KEYS.USER_ID, '');
    const [messages, setMessages] = useLocalStorage(STORAGE_KEYS.CHAT_HISTORY, []);

    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [emotionState, setEmotionState] = useState(null);
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    // Initialize user if not exists (handled by useLocalStorage initialValue logic mostly, 
    // but we need to ensure a unique ID is generated if empty)
    useEffect(() => {
        if (!userId) {
            setUserId(`user-${Date.now()}`);
        }
    }, [userId, setUserId]);

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
        // if (window.confirm('Tem certeza que deseja limpar toda a conversa?')) {
        setMessages([]);
        setEmotionState(null);
        // }
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
