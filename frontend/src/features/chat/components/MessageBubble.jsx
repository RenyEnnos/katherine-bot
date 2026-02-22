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
                                    em: ({ node, ...props }) => <span className="text-gray-400 italic" {...props} />,
                                    code: ({ node, className, children, ...props }) => {
                                        const bgClass = isUser ? 'bg-blue-800 text-blue-100' : 'bg-gray-900 text-gray-200';
                                        return (
                                            <code className={`${bgClass} px-1.5 py-0.5 rounded text-sm font-mono break-words`} {...props}>
                                                {children}
                                            </code>
                                        );
                                    },
                                    pre: ({ node, children, ...props }) => {
                                        const containerClass = isUser ? 'bg-blue-900 border-blue-700' : 'bg-gray-950 border-gray-700';
                                        return (
                                            <pre className={`${containerClass} text-gray-200 p-4 rounded-lg overflow-x-auto text-sm my-3 border shadow-inner [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-inherit`} {...props}>
                                                {children}
                                            </pre>
                                        );
                                    },
                                    a: ({ node, ...props }) => {
                                        const linkClass = isUser ? 'text-white underline hover:text-blue-100' : 'text-blue-400 hover:text-blue-300 underline';
                                        return <a className={`${linkClass} transition-colors font-medium`} target="_blank" rel="noopener noreferrer" {...props} />;
                                    },
                                    h1: ({ node, ...props }) => <h1 className="text-xl font-bold mt-4 mb-2" {...props} />,
                                    h2: ({ node, ...props }) => <h2 className="text-lg font-semibold mt-3 mb-2" {...props} />,
                                    h3: ({ node, ...props }) => <h3 className="text-base font-medium mt-2 mb-1" {...props} />,
                                    ul: ({ node, ...props }) => <ul className="list-disc list-outside ml-4 mb-2 space-y-1" {...props} />,
                                    ol: ({ node, ...props }) => <ol className="list-decimal list-outside ml-4 mb-2 space-y-1" {...props} />,
                                    blockquote: ({ node, ...props }) => {
                                        const borderClass = isUser ? 'border-blue-400 bg-blue-700/30' : 'border-gray-600 bg-gray-700/30';
                                        return <blockquote className={`border-l-4 ${borderClass} pl-3 py-1 my-2 italic rounded-r`} {...props} />;
                                    },
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
                            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-all opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 focus-visible:ring-2 focus-visible:ring-gray-500 outline-none"
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
