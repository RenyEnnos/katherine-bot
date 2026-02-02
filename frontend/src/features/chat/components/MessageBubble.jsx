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
            console.error('Failed to copy text: ', err);
        }
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content & Actions */}
                <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} min-w-0`}>
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
                            aria-label={isCopied ? "Copiado" : "Copiar resposta"}
                            className="flex items-center gap-1.5 mt-1 ml-1 text-xs text-gray-500 hover:text-gray-300 transition-colors p-1 rounded focus:outline-none focus:ring-2 focus:ring-gray-600"
                        >
                            {isCopied ? (
                                <>
                                    <Check size={14} className="text-green-500" />
                                    <span className="text-green-500">Copiado</span>
                                </>
                            ) : (
                                <>
                                    <Copy size={14} />
                                    <span>Copiar</span>
                                </>
                            )}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
