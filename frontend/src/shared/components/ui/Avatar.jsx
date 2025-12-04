import React from 'react';
import { User, Bot } from 'lucide-react';

const Avatar = ({ isUser, size = 18 }) => {
    return (
        <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${isUser ? 'bg-blue-600' : 'bg-green-600'
            }`}>
            {isUser ? <User size={size} className="text-white" /> : <Bot size={size} className="text-white" />}
        </div>
    );
};

export default Avatar;
