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
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
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

                {/* Copy Button (Assistant only) */}
                {!isUser && (
                    <button
                        onClick={handleCopy}
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity p-2 text-gray-500 hover:text-gray-300 self-start mt-2 outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-md"
                        aria-label="Copiar mensagem"
                        title="Copiar mensagem"
                    >
                        {copied ? <Check size={16} /> : <Copy size={16} />}
                    </button>
                )}
            </div>
        </div>
    );
};

export default MessageBubble;
