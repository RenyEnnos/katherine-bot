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
                                    // Headers
                                    h1: ({ node, ...props }) => <h1 className="text-xl font-bold mt-4 mb-2" {...props} />,
                                    h2: ({ node, ...props }) => <h2 className="text-lg font-bold mt-3 mb-2" {...props} />,
                                    h3: ({ node, ...props }) => <h3 className="text-base font-bold mt-2 mb-1" {...props} />,

                                    // Links
                                    a: ({ node, ...props }) => (
                                        <a
                                            className={`hover:underline break-all ${isUser ? 'text-white underline' : 'text-blue-400'}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            {...props}
                                        />
                                    ),

                                    // Lists
                                    ul: ({ node, ...props }) => <ul className="list-disc pl-5 space-y-1 my-2" {...props} />,
                                    ol: ({ node, ...props }) => <ol className="list-decimal pl-5 space-y-1 my-2" {...props} />,
                                    li: ({ node, ...props }) => <li className="pl-1" {...props} />,

                                    // Code
                                    code: ({ node, inline, className, children, ...props }) => {
                                        return (
                                            <code
                                                className={`px-1.5 py-0.5 rounded text-sm font-mono ${isUser
                                                    ? 'bg-blue-700 text-blue-100'
                                                    : 'bg-gray-700 text-gray-200 border border-gray-600'}`}
                                                {...props}
                                            >
                                                {children}
                                            </code>
                                        );
                                    },
                                    pre: ({ node, ...props }) => (
                                        <div className={`rounded-lg overflow-hidden my-3 border ${isUser
                                            ? 'bg-blue-800 border-blue-700'
                                            : 'bg-gray-950 border-gray-700'}`}>
                                            <pre
                                                className={`p-3 overflow-x-auto font-mono text-sm [&_code]:bg-transparent [&_code]:border-none [&_code]:p-0`}
                                                {...props}
                                            />
                                        </div>
                                    ),

                                    // Blockquotes
                                    blockquote: ({ node, ...props }) => (
                                        <blockquote
                                            className={`border-l-4 pl-4 italic my-2 ${isUser
                                                ? 'border-blue-400 text-blue-100'
                                                : 'border-gray-600 text-gray-400'}`}
                                            {...props}
                                        />
                                    ),

                                    // Emphasis
                                    em: ({ node, ...props }) => (
                                        <span className={`italic ${isUser ? 'text-blue-100' : 'text-gray-400'}`} {...props} />
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
