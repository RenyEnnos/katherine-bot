/**
 * Desktop companion root (#336, #342).
 *
 * This module is the desktop app's ONLY root. It contains ONLY
 * desktop concerns and imports nothing from the web stack: no
 * supabaseClient, no AuthPage, no web auth/session logic. The web
 * modules live exclusively behind `AppWeb`/`main-web.jsx`.
 *
 * The desktop companion is single-user local (no login, no session,
 * no cloud): ChatWindow renders directly and all data flows through
 * the local bridge transport (useChat / chatTransport /
 * desktopBridge).
 *
 * Mode switching (#342):
 * - 'companion': full companion layout (ChatHeader, face, message history,
 *   composer, emotion and privacy utilities) on solid dark background.
 * - 'presence': minimal floating presence surface (KatherinePresence) with
 *   true alpha transparency on the window surface.
 * - In presence mode, CompanionLayout and all conversation DOM elements are
 *   completely unmounted.
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import ChatWindow from './features/chat/components/ChatWindow';
import CompanionLayout from './features/chat/components/CompanionLayout.jsx';
import KatherinePresence from './features/katherine-face/KatherinePresence.jsx';
import {
    setPresenceMode,
    setAlwaysOnTop,
    getWindowState,
    closeDesktopWindow,
    minimizeDesktopWindow,
} from './lib/desktopBridge';

export default function AppDesktop() {
    const [mode, setMode] = useState('companion');
    const [isAlwaysOnTop, setIsAlwaysOnTop] = useState(false);
    const isTransitioningRef = useRef(false);
    const isPinningRef = useRef(false);

    // Bounded one-shot sync on shell startup (#342) - no continuous polling.
    useEffect(() => {
        let active = true;
        getWindowState().then((state) => {
            if (active && state?.ok) {
                if (state.mode === 'presence' || state.mode === 'companion') {
                    setMode(state.mode);
                }
                if (typeof state.on_top === 'boolean') {
                    setIsAlwaysOnTop(state.on_top);
                }
            }
        });
        return () => {
            active = false;
        };
    }, []);

    const handleEnterPresence = useCallback(async () => {
        if (isTransitioningRef.current) return;
        isTransitioningRef.current = true;
        try {
            const res = await setPresenceMode(true);
            if (res?.ok) {
                setMode('presence');
                if (typeof res.on_top === 'boolean') {
                    setIsAlwaysOnTop(res.on_top);
                }
            }
        } finally {
            isTransitioningRef.current = false;
        }
    }, []);

    const handleReturnToCompanion = useCallback(async () => {
        if (isTransitioningRef.current) return;
        isTransitioningRef.current = true;
        try {
            const res = await setPresenceMode(false);
            if (res?.ok) {
                setMode('companion');
                if (typeof res.on_top === 'boolean') {
                    setIsAlwaysOnTop(res.on_top);
                }
            }
        } finally {
            isTransitioningRef.current = false;
        }
    }, []);

    const handleToggleAlwaysOnTop = useCallback(async () => {
        if (isPinningRef.current) return;
        isPinningRef.current = true;
        try {
            const nextState = !isAlwaysOnTop;
            const res = await setAlwaysOnTop(nextState);
            if (res?.ok && typeof res.on_top === 'boolean') {
                setIsAlwaysOnTop(res.on_top);
            }
        } finally {
            isPinningRef.current = false;
        }
    }, [isAlwaysOnTop]);

    const handleMinimize = useCallback(async () => {
        await minimizeDesktopWindow();
    }, []);

    const handleClose = useCallback(async () => {
        await closeDesktopWindow();
    }, []);

    const renderLayout = useCallback(
        (chatModel) => {
            if (mode === 'presence') {
                return (
                    <KatherinePresence
                        emotionState={chatModel.emotionState}
                        isLoading={chatModel.isLoading}
                        onReturnToCompanion={handleReturnToCompanion}
                        onClose={handleClose}
                        onToggleAlwaysOnTop={handleToggleAlwaysOnTop}
                        onMinimize={handleMinimize}
                        isAlwaysOnTop={isAlwaysOnTop}
                    />
                );
            }
            return (
                <CompanionLayout
                    {...chatModel}
                    onEnterPresence={handleEnterPresence}
                />
            );
        },
        [
            mode,
            isAlwaysOnTop,
            handleEnterPresence,
            handleReturnToCompanion,
            handleToggleAlwaysOnTop,
            handleMinimize,
            handleClose,
        ],
    );

    const isPresence = mode === 'presence';

    return (
        <div
            className={`app-desktop ${
                isPresence
                    ? 'app-desktop--presence font-sans antialiased'
                    : 'app-desktop--companion min-h-screen bg-gray-900 text-gray-100 font-sans antialiased'
            }`}
            style={isPresence ? { background: 'transparent' } : undefined}
            data-testid="app-desktop-root"
            data-desktop-mode={mode}
        >
            <ChatWindow renderLayout={renderLayout} />
        </div>
    );
}
