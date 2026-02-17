import React, { useState } from 'react';
import { Trash2, Check, X } from 'lucide-react';

const ChatHeader = ({ clearHistory }) => {
    const [showConfirm, setShowConfirm] = useState(false);
    const [shouldFocusTrash, setShouldFocusTrash] = useState(false);

    const handleClear = () => {
        clearHistory();
        setShowConfirm(false);
        setShouldFocusTrash(true);
    };

    const handleCancel = () => {
        setShowConfirm(false);
        setShouldFocusTrash(true);
    };

    return (
        <header className="flex-shrink-0 h-16 border-b border-gray-800 flex items-center justify-between px-4 md:px-8 bg-gray-900 z-10">
            <div className="font-semibold text-lg tracking-tight text-white">
                Katherine <span className="text-gray-500 font-normal">– SoulMate</span>
            </div>

            {showConfirm ? (
                <div
                    className="flex items-center gap-2"
                    onKeyDown={(e) => {
                        if (e.key === 'Escape') handleCancel();
                    }}
                >
                    <span className="text-sm text-gray-400">Confirmar?</span>
                    <button
                        onClick={handleClear}
                        className="text-red-400 hover:text-red-300 transition-colors p-2 rounded-md hover:bg-gray-800"
                        title="Confirmar limpeza"
                        aria-label="Confirmar limpeza"
                    >
                        <Check size={20} />
                    </button>
                    <button
                        onClick={handleCancel}
                        className="text-gray-500 hover:text-gray-300 transition-colors p-2 rounded-md hover:bg-gray-800"
                        title="Cancelar"
                        aria-label="Cancelar"
                        autoFocus
                    >
                        <X size={20} />
                    </button>
                </div>
            ) : (
                <button
                    onClick={() => {
                        setShowConfirm(true);
                        setShouldFocusTrash(true);
                    }}
                    className="text-gray-500 hover:text-red-400 transition-colors p-2 rounded-md hover:bg-gray-800"
                    title="Limpar conversa"
                    aria-label="Limpar conversa"
                    autoFocus={shouldFocusTrash}
                >
                    <Trash2 size={20} />
                </button>
            )}
        </header>
    );
};

export default ChatHeader;
