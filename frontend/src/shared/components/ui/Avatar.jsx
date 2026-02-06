import React from 'react';
import { User, Bot } from 'lucide-react';

const Avatar = ({ isUser, size = 18, name }) => {
    const label = name || (isUser ? "Você" : "Assistente");

    return (
        <div
            className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isUser ? 'bg-blue-600' : 'bg-green-600'}`}
            role="img"
            aria-label={label}
        >
            {isUser ? (
                <User size={size} className="text-white" aria-hidden="true" />
            ) : (
                <Bot size={size} className="text-white" aria-hidden="true" />
            )}
        </div>
    );
};

export default Avatar;
