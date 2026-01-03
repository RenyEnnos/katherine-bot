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
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4 items-start`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content & Actions */}
                <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} min-w-0`}>
                    <div className={`px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed break-words w-full ${isUser
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

                    {/* Copy Button - Only for assistant */}
                    {!isUser && (
                        <div className="flex items-center mt-1 ml-1 h-6">
                            <button
                                onClick={handleCopy}
                                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800 px-2 py-1 rounded-md transition-all opacity-100 md:opacity-0 group-hover:opacity-100 focus:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-blue-500 outline-none"
                                aria-label={isCopied ? "Copiado!" : "Copiar resposta"}
                                title={isCopied ? "Copiado!" : "Copiar resposta"}
                            >
                                {isCopied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                                <span>{isCopied ? "Copiado" : "Copiar"}</span>
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
