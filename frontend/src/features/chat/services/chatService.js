import api from '../../../shared/services/apiClient';

export const sendMessage = async (userId, message) => {
    try {
        const response = await api.post('/chat', {
            user_id: userId,
            message: message,
        });
        return response.data;
    } catch (error) {
        console.error('Error sending message:', error);
        throw error;
    }
};
