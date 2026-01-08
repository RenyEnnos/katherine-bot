import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    const [isCopied, setIsCopied] = useState(false);

    const handleCopy = async () => {
        if (!message) return;
        try {
            await navigator.clipboard.writeText(message);
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} ${isUser ? 'mb-6' : 'mb-10'}`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4 group`}>
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

                    {!isUser && (
                        <button
                            onClick={handleCopy}
                            className="absolute -bottom-8 left-0 p-1.5 text-gray-400 hover:text-white bg-gray-800/50 hover:bg-gray-700 rounded-lg transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 flex items-center gap-2 text-xs"
                            aria-label="Copiar mensagem"
                            title="Copiar mensagem"
                        >
                            {isCopied ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
                            <span className="sr-only">{isCopied ? 'Copiado!' : 'Copiar'}</span>
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
