import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    const [isCopied, setIsCopied] = useState(false);

    useEffect(() => {
        if (isCopied) {
            const timeout = setTimeout(() => setIsCopied(false), 2000);
            return () => clearTimeout(timeout);
        }
    }, [isCopied]);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(message);
            setIsCopied(true);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                <div className={`flex flex-col gap-1 min-w-0 ${isUser ? 'items-end' : 'items-start'}`}>
                    {/* Message Content */}
                    <div className={`px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed ${isUser
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
                    </div>

                    {/* Copy Button (Only for AI) */}
                    {!isUser && (
                        <button
                            onClick={handleCopy}
                            aria-label="Copiar mensagem"
                            className="p-1.5 text-gray-500 hover:text-gray-300 transition-colors rounded-lg hover:bg-gray-800/50 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 opacity-100"
                            title="Copiar"
                        >
                            {isCopied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
