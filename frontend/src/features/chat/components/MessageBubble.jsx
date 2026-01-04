import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(message);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    };

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4 relative`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

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

                {/* Copy Button - Only for assistant messages */}
                {!isUser && (
                    <button
                        onClick={handleCopy}
                        className="absolute -bottom-6 left-14 p-1 text-gray-500 hover:text-gray-300 text-xs flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 transition-opacity"
                        aria-label={copied ? "Copiado!" : "Copiar mensagem"}
                        title={copied ? "Copiado!" : "Copiar mensagem"}
                    >
                        {copied ? <Check size={14} /> : <Copy size={14} />}
                        <span className="sr-only">{copied ? "Copiado!" : "Copiar mensagem"}</span>
                        <span className="text-xs" aria-hidden="true">{copied ? "Copiado" : ""}</span>
                    </button>
                )}
            </div>
        </div>
    );
};

export default MessageBubble;
