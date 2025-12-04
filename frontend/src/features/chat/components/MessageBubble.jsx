import React from 'react';
import ReactMarkdown from 'react-markdown';
import Avatar from '../../../shared/components/ui/Avatar';

const MessageBubble = ({ message, isUser }) => {
    return (
        <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'} mb-6`}>
            <div className={`flex max-w-[80%] md:max-w-[70%] ${isUser ? 'flex-row-reverse' : 'flex-row'} gap-4`}>
                {/* Avatar */}
                <Avatar isUser={isUser} />

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
            </div>
        </div>
    );
};

export default MessageBubble;
