import React from 'react';
import { Trash2 } from 'lucide-react';

const ChatHeader = ({ clearHistory }) => {
    return (
        <header className="flex-shrink-0 h-16 border-b border-gray-800 flex items-center justify-between px-4 md:px-8 bg-gray-900 z-10">
            <div className="font-semibold text-lg tracking-tight text-white">
                Katherine <span className="text-gray-500 font-normal">– SoulMate</span>
            </div>
            <button
                onClick={clearHistory}
                className="text-gray-500 hover:text-red-400 transition-colors p-2 rounded-md hover:bg-gray-800"
                title="Limpar conversa"
            >
                <Trash2 size={20} />
            </button>
        </header>
    );
};

export default ChatHeader;
