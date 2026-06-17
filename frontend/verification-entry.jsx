import React from 'react';
import ReactDOM from 'react-dom/client';
import MessageBubble from './src/features/chat/components/MessageBubble.jsx';
import './src/index.css';

const App = () => (
    <div className="bg-gray-900 min-h-screen p-8 text-white">
        <MessageBubble message="Este é um teste de cópia de mensagem" isUser={false} />
    </div>
);

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
