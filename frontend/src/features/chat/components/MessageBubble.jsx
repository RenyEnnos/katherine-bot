import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    const [isCopied, setIsCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(message);
            setIsCopied(true);
            setTimeout(() => setIsCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content & Actions */}
                <div className={`flex flex-col gap-1 max-w-full ${isUser ? 'items-end' : 'items-start'}`}>
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

                    {!isUser && (
                        <button
                            onClick={handleCopy}
                            aria-label="Copiar resposta"
                            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-300 focus-visible:text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-600 rounded transition-colors ml-1 p-1"
                        >
                            {isCopied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                            {isCopied ? 'Copiado!' : 'Copiar'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
