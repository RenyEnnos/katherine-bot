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
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />

                {/* Message Content & Actions */}
                <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-full overflow-hidden`}>
                    <div className={`px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed ${isUser
                        ? 'bg-blue-600 text-white rounded-tr-none'
                        : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700'
                        }`}>
                        <div className="markdown-content">
                            <ReactMarkdown
                                components={{
                                    em: ({ node, ...props }) => <span className="italic opacity-80" {...props} />,
                                    strong: ({ node, ...props }) => <span className="font-semibold" {...props} />,
                                    ul: ({ node, ...props }) => <ul className="list-disc pl-4 space-y-1 my-2" {...props} />,
                                    ol: ({ node, ...props }) => <ol className="list-decimal pl-4 space-y-1 my-2" {...props} />,
                                    li: ({ node, ...props }) => <li className="pl-1" {...props} />,
                                    a: ({ node, ...props }) => (
                                        <a target="_blank" rel="noopener noreferrer"
                                           className={`underline ${isUser ? 'text-blue-100 hover:text-white' : 'text-blue-400 hover:text-blue-300'}`}
                                           {...props}
                                        />
                                    ),
                                    code: ({ node, ...props }) => (
                                        <code className={`font-mono text-xs px-1 py-0.5 rounded ${isUser ? 'bg-blue-700 text-blue-50' : 'bg-gray-900 text-pink-200'}`} {...props} />
                                    ),
                                    pre: ({ node, ...props }) => (
                                        <pre className={`p-3 rounded-lg overflow-x-auto my-2 border text-sm [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit ${isUser ? 'bg-blue-800 border-blue-700 text-blue-50' : 'bg-gray-950 border-gray-700 text-gray-300'}`} {...props} />
                                    ),
                                    blockquote: ({ node, ...props }) => (
                                        <blockquote className={`border-l-4 pl-3 py-1 italic my-2 ${isUser ? 'border-blue-400 text-blue-100' : 'border-gray-600 text-gray-400'}`} {...props} />
                                    )
                                }}
                            >
                                {message}
                            </ReactMarkdown>
                        </div>
                    </div>

                </div>

                {/* Copy Button - Visible on mobile, hover on desktop */}
                {!isUser && (
                    <div className="flex flex-col justify-center">
                        <button
                            onClick={handleCopy}
                            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100"
                            aria-label={isCopied ? "Copiado" : "Copiar mensagem"}
                            title={isCopied ? "Copiado" : "Copiar mensagem"}
                        >
                            {isCopied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
};

export default MessageBubble;
