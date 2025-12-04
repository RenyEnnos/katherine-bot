import React from 'react';
import { Loader2 } from 'lucide-react';
import MessageBubble from './MessageBubble';

const MessageList = ({ messages, isLoading, messagesEndRef }) => {
    return (
        <div className="flex-1 overflow-y-auto p-4 md:p-8 space-y-6 scroll-smooth">
            {messages.length === 0 && (
                <div className="h-full flex flex-col items-center justify-center text-gray-500 opacity-50">
                    <p>Comece uma conversa com a Katherine...</p>
                </div>
            )}

            {messages.map((msg, idx) => (
                msg.role === 'system' ? (
                    <div key={idx} className="text-center text-red-400 text-sm py-2">
                        {msg.content}
                    </div>
                ) : (
                    <MessageBubble
                        key={idx}
                        message={msg.content}
                        isUser={msg.role === 'user'}
                    />
                )
            ))}

            {isLoading && (
                <div className="flex items-center gap-2 text-gray-500 text-sm ml-2 animate-pulse">
                    <Loader2 size={16} className="animate-spin" />
                    Katherine está digitando...
                </div>
            )}
            <div ref={messagesEndRef} />
        </div>
    );
};

export default MessageList;
