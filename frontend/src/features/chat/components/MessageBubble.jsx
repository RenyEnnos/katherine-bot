import React, { useState, useMemo } from 'react';
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

    const components = useMemo(() => ({
        em: ({ node, ...props }) => <span className="italic opacity-80" {...props} />,
        strong: ({ node, ...props }) => <span className="font-bold" {...props} />,
        h1: ({ node, ...props }) => <h1 className="text-xl font-bold mt-4 mb-2 first:mt-0" {...props} />,
        h2: ({ node, ...props }) => <h2 className="text-lg font-bold mt-3 mb-2" {...props} />,
        h3: ({ node, ...props }) => <h3 className="text-base font-bold mt-2 mb-1" {...props} />,
        a: ({ node, ...props }) => (
            <a
                className={`underline underline-offset-2 transition-colors ${isUser ? 'text-white hover:text-blue-100' : 'text-blue-400 hover:text-blue-300'}`}
                target="_blank" rel="noopener noreferrer" {...props}
            />
        ),
        ul: ({ node, ...props }) => <ul className="list-disc pl-4 mb-2 space-y-1" {...props} />,
        ol: ({ node, ...props }) => <ol className="list-decimal pl-4 mb-2 space-y-1" {...props} />,
        li: ({ node, ...props }) => <li className="pl-1" {...props} />,
        blockquote: ({ node, ...props }) => (
            <blockquote
                className={`border-l-4 pl-4 py-1 my-2 italic ${isUser ? 'border-white/30 text-white/90' : 'border-gray-600 text-gray-400'}`}
                {...props}
            />
        ),
        pre: ({ node, ...props }) => (
            <pre className="bg-gray-950/50 p-3 rounded-lg overflow-x-auto my-2 border border-white/10 [&_code]:bg-transparent [&_code]:p-0" {...props} />
        ),
        code: ({ node, className, ...props }) => (
            <code
                className={`px-1.5 py-0.5 rounded text-sm font-mono ${isUser ? 'bg-blue-700 text-white' : 'bg-gray-700 text-gray-200'}`}
                {...props}
            />
        ),
    }), [isUser]);

    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6 group`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                <Avatar isUser={isUser} name={isUser ? "Você" : "Katherine"} />
                <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-full overflow-hidden`}>
                    <div className={`px-4 py-3 rounded-2xl shadow-sm text-sm md:text-base leading-relaxed ${isUser
                        ? 'bg-blue-600 text-white rounded-tr-none'
                        : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700'
                        }`}>
                        <div className="markdown-content">
                            <ReactMarkdown components={components}>{message}</ReactMarkdown>
                        </div>
                    </div>
                </div>
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
