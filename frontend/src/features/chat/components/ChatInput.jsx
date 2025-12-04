import React from 'react';
import { Send } from 'lucide-react';

const ChatInput = ({ input, setInput, handleSend, isLoading, inputRef }) => {
    const handleKeyDown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="flex-shrink-0 p-4 bg-gray-900 border-t border-gray-800">
            <div className="max-w-3xl mx-auto relative flex items-end gap-2 bg-gray-800 p-2 rounded-xl border border-gray-700 focus-within:border-gray-600 focus-within:ring-1 focus-within:ring-gray-600 transition-all shadow-sm">
                <textarea
                    ref={inputRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Escreva aqui sua mensagem..."
                    className="w-full bg-transparent text-white placeholder-gray-400 text-base p-2 max-h-32 min-h-[44px] resize-none focus:outline-none scrollbar-hide"
                    rows={1}
                    disabled={isLoading}
                    style={{ height: 'auto', minHeight: '44px' }}
                    onInput={(e) => {
                        e.target.style.height = 'auto';
                        e.target.style.height = e.target.scrollHeight + 'px';
                    }}
                />
                <button
                    onClick={handleSend}
                    disabled={!input.trim() || isLoading}
                    className={`p-2 rounded-lg mb-1 transition-all ${input.trim() && !isLoading
                        ? 'bg-blue-600 text-white hover:bg-blue-500 shadow-md'
                        : 'bg-gray-700 text-gray-500 cursor-not-allowed'
                        }`}
                >
                    <Send size={20} />
                </button>
            </div>
            <div className="text-center text-xs text-gray-500 mt-2">
                Katherine pode cometer erros. Considere verificar informações importantes.
            </div>
        </div>
    );
};

export default ChatInput;
