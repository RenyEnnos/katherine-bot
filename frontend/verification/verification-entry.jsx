import React from 'react';
import { createRoot } from 'react-dom/client';
import MessageBubble from '../src/features/chat/components/MessageBubble.jsx';
import '../src/index.css';

const App = () => (
    <div className="bg-gray-900 min-h-screen p-8 text-white">
        <h1 className="text-2xl mb-8">Verification: MessageBubble Focus State</h1>

        <div className="w-full max-w-4xl mx-auto space-y-8">
            <h2 className="text-xl">Assistant Message (has copy button)</h2>
            <div className="bg-gray-800 p-8 rounded-lg">
                 <MessageBubble
                    message="Olá! Sou a Katherine. Como posso te ajudar hoje?"
                    isUser={false}
                />
            </div>

            <h2 className="text-xl mt-8">User Message (no copy button)</h2>
            <div className="bg-gray-800 p-8 rounded-lg">
                 <MessageBubble
                    message="Oi Katherine, me ajude com um problema."
                    isUser={true}
                />
            </div>
        </div>
    </div>
);

const root = createRoot(document.getElementById('root'));
root.render(<App />);
