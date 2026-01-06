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
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                <div className={`flex flex-col w-full min-w-0 ${isUser ? 'items-end' : 'items-start'}`}>
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

                    {/* Actions - Visible on hover for desktop, always visible on mobile/focus */}
                    {!isUser && (
                        <div className="flex items-center gap-2 mt-1 ml-1 opacity-100 md:opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-200">
                             <button
                                onClick={handleCopy}
                                className="flex items-center gap-1.5 p-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors rounded hover:bg-gray-800/50 focus:outline-none focus:ring-1 focus:ring-gray-500"
                                aria-label={isCopied ? "Copiado para a área de transferência" : "Copiar mensagem para a área de transferência"}
                                title={isCopied ? "Copiado!" : "Copiar mensagem"}
                            >
                                {isCopied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                                <span className="text-xs font-medium">{isCopied ? "Copiado" : "Copiar"}</span>
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
