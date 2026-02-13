import React, { useState, useRef, useEffect } from 'react';
import { Trash2, Check, X } from 'lucide-react';

const ChatHeader = ({ clearHistory }) => {
    const [showConfirm, setShowConfirm] = useState(false);
    const trashBtnRef = useRef(null);
    const cancelBtnRef = useRef(null);
    const isFirstRender = useRef(true);

    useEffect(() => {
        if (isFirstRender.current) {
            isFirstRender.current = false;
            return;
        }
        if (showConfirm) {
            cancelBtnRef.current?.focus();
        } else {
            trashBtnRef.current?.focus();
        }
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
                        className="text-red-400 hover:text-red-300 transition-colors p-2 rounded-md hover:bg-gray-800"
                        title="Confirmar limpeza"
                        aria-label="Confirmar limpeza"
                    >
                        <Check size={20} />
                    </button>
                    <button
                        ref={cancelBtnRef}
                        onClick={() => setShowConfirm(false)}
                        className="text-gray-500 hover:text-gray-300 transition-colors p-2 rounded-md hover:bg-gray-800"
                        title="Cancelar"
                        aria-label="Cancelar"
                    >
                        <X size={20} />
                    </button>
                </div>
            ) : (
                <button
                    ref={trashBtnRef}
                    onClick={() => setShowConfirm(true)}
                    className="text-gray-500 hover:text-red-400 transition-colors p-2 rounded-md hover:bg-gray-800"
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
