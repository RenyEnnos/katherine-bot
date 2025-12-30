import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Copy, Check } from 'lucide-react';
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
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content */}
                <div className={`relative group px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed ${isUser
                    ? 'bg-blue-600 text-white rounded-tr-none'
                    : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700'
                    }`}>
                    <div className={`markdown-content ${!isUser ? 'pb-2' : ''}`}>
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
                            className="absolute bottom-1 right-1 p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-gray-700/50 transition-all opacity-0 group-hover:opacity-100 focus:opacity-100"
                            aria-label={copied ? "Mensagem copiada" : "Copiar mensagem"}
                            title="Copiar mensagem"
                        >
                            {copied ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default MessageBubble;
