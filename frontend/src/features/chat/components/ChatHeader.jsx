import React, { useState, useRef, useEffect } from 'react';
import { Trash2, Check, X } from 'lucide-react';

const ChatHeader = ({ clearHistory }) => {
    const [showConfirm, setShowConfirm] = useState(false);
    const cancelButtonRef = useRef(null);
    const trashButtonRef = useRef(null);
    const prevShowConfirm = useRef(showConfirm);

    useEffect(() => {
        if (!prevShowConfirm.current && showConfirm) {
            cancelButtonRef.current?.focus();
        } else if (prevShowConfirm.current && !showConfirm) {
            trashButtonRef.current?.focus();
        }
        prevShowConfirm.current = showConfirm;
    }, [showConfirm]);

    const handleClear = () => {
        clearHistory();
        setShowConfirm(false);
    };

    return (
        <header className="flex-shrink-0 h-16 border-b border-gray-800 flex items-center justify-between px-4 md:px-8 bg-gray-900 z-10">
            <div className="font-semibold text-lg tracking-tight text-white">
                Katherine <span className="text-gray-500 font-normal">– SoulMate</span>
            </div>

            {showConfirm ? (
                <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-400">Confirmar?</span>
                    <button
                        onClick={handleClear}
                        className="text-red-400 hover:text-red-300 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
                        title="Confirmar limpeza"
                        aria-label="Confirmar limpeza"
                    >
                        <Check size={20} />
                    </button>
                    <button
                        ref={cancelButtonRef}
                        onClick={() => setShowConfirm(false)}
                        className="text-gray-500 hover:text-gray-300 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
                        title="Cancelar"
                        aria-label="Cancelar"
                    >
                        <X size={20} />
                    </button>
                </div>
            ) : (
                <button
                    ref={trashButtonRef}
                    onClick={() => setShowConfirm(true)}
                    className="text-gray-500 hover:text-red-400 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
                    title="Limpar conversa"
                    aria-label="Limpar conversa"
                >
                    <Trash2 size={20} />
                </button>
            )}
        </header>
    );
};

export default ChatHeader;
