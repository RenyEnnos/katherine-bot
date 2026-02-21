import React, { useState, useRef, useEffect } from 'react';
import { Trash2, Check, X } from 'lucide-react';

const ChatHeader = ({ clearHistory }) => {
    const [showConfirm, setShowConfirm] = useState(false);
    const trashRef = useRef(null);
    const prevShowConfirm = useRef(showConfirm);
    const [shouldFocusTrash, setShouldFocusTrash] = useState(false);

    useEffect(() => {
        // Focus restoration when confirmation closes
        if (prevShowConfirm.current && !showConfirm && trashRef.current) {
            trashRef.current.focus();
        }
        prevShowConfirm.current = showConfirm;
    }, [showConfirm]);

    useEffect(() => {
        // Handle Escape key globally when confirmation is open
        const handleKeyDown = (e) => {
            if (e.key === 'Escape') {
                setShowConfirm(false);
            }
        };

        if (showConfirm) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [showConfirm]);

    const handleClear = () => {
        clearHistory();
        setShowConfirm(false);
    };

    const handleTrashClick = () => {
        setShouldFocusTrash(true);
        setShowConfirm(true);
    };

    return (
        <header className="flex-shrink-0 h-16 border-b border-gray-800 flex items-center justify-between px-4 md:px-8 bg-gray-900 z-10">
            <div className="font-semibold text-lg tracking-tight text-white">
                Katherine <span className="text-gray-500 font-normal">– SoulMate</span>
            </div>

            {showConfirm ? (
                <div
                    className="flex items-center gap-2"
                    role="group"
                    aria-label="Confirmar limpeza do histórico"
                >
                    <span
                        className="text-sm text-gray-400 animate-in fade-in duration-200"
                        id="confirm-text"
                    >
                        Limpar histórico?
                    </span>
                    <button
                        onClick={handleClear}
                        className="text-red-400 hover:text-red-300 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-red-400 focus:outline-none"
                        title="Confirmar limpeza"
                        aria-label="Confirmar limpeza"
                        aria-describedby="confirm-text"
                    >
                        <Check size={20} />
                    </button>
                    <button
                        onClick={() => setShowConfirm(false)}
                        autoFocus
                        className="text-gray-500 hover:text-gray-300 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-gray-400 focus:outline-none"
                        title="Cancelar"
                        aria-label="Cancelar"
                    >
                        <X size={20} />
                    </button>
                </div>
            ) : (
                <button
                    onClick={handleTrashClick}
                    ref={trashRef}
                    autoFocus={shouldFocusTrash}
                    className="text-gray-500 hover:text-red-400 transition-colors p-2 rounded-md hover:bg-gray-800 focus-visible:ring-2 focus-visible:ring-red-400 focus:outline-none"
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
