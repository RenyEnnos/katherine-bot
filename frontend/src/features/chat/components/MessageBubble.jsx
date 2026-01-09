import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    const [isCopied, setIsCopied] = useState(false);

    const handleCopy = () => {
        navigator.clipboard.writeText(message).then(() => {
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), 2000);
        }).catch(err => {
            console.error('Failed to copy message:', err);
        });
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} ${isUser ? 'mb-6' : 'mb-10'} group relative`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content */}
                <div className={`relative px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed ${isUser
                    ? 'bg-blue-600 text-white rounded-tr-none'
                    : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700'
                    }`}>
                    <div className="markdown-content">
                        <ReactMarkdown
                            components={{
                                em: ({ node, ...props }) => <span className="text-gray-400 italic" {...props} />
                            }}
                        >
                            {message}
                        </ReactMarkdown>
                    </div>

                    {/* Copy Button (Only for Assistant) */}
                    {!isUser && (
                        <button
                            onClick={handleCopy}
                            aria-label={isCopied ? "Mensagem copiada" : "Copiar mensagem"}
                            className="absolute -bottom-8 left-0 p-1.5 text-gray-500 hover:text-white bg-gray-900/50 hover:bg-gray-800 rounded-lg opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all duration-200"
                        >
                            {isCopied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
