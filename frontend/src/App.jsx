import { useState, useEffect } from 'react';
import { supabase } from './lib/supabaseClient';
import AuthPage from './features/auth/AuthPage';
import ChatWindow from './features/chat/components/ChatWindow';

function App() {
    const [session, setSession] = useState(null);

    useEffect(() => {
        supabase.auth.getSession().then(({ data: { session } }) => {
            setSession(session);
        });

        const {
            data: { subscription },
        } = supabase.auth.onAuthStateChange((_event, session) => {
            setSession(session);
        });

        return () => subscription.unsubscribe();
    }, []);

    if (!session) {
        return <AuthPage />;
    }

    return (
        <div className="min-h-screen bg-gray-900 text-gray-100 font-sans antialiased">
            <ChatWindow userId={session.user.id} />
        </div>
    );
}

export default App;
