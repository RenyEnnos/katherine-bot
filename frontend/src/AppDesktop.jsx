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
 *
 * Settings workspace (#347):
 * - `isSettingsOpen` is a plain composition flag, not a router: when open
 *   (companion mode only), `renderLayout` renders SettingsWorkspace instead
 *   of CompanionLayout. ChatWindow — and therefore the single useChat()
 *   call with its history and draft state — stays mounted above this seam
 *   and is never remounted by opening/closing settings.
 * - Settings never renders inside floating presence mode: the presence
 *   surface stays minimal and free of conversation/settings DOM (#342).
 * - The gear access lives in the companion header, not in the #344 state
 *   sidebar: the sidebar keeps answering "how Katherine is right now".
 */
import React, { useState, useCallback, useEffect, useRef } from 'react';
import ChatWindow from './features/chat/components/ChatWindow';
import CompanionLayout from './features/chat/components/CompanionLayout.jsx';
import KatherinePresence from './features/katherine-face/KatherinePresence.jsx';
import KatherineStateSidebar from './features/chat/components/KatherineStateSidebar.jsx';
import SettingsWorkspace from './features/settings/SettingsWorkspace.jsx';
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
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);
    const isTransitioningRef = useRef(false);
    const isPinningRef = useRef(false);
    const windowStateEpochRef = useRef(0);
    const settingsButtonRef = useRef(null);
    const shouldFocusSettingsButtonRef = useRef(false);

    // Bounded one-shot sync on shell startup (#342) - no continuous polling.
    useEffect(() => {
        let active = true;
        const readEpoch = windowStateEpochRef.current;
        getWindowState().then((state) => {
            // A startup snapshot may resolve after a newer confirmed window
            // operation. Never let that stale read overwrite the newer
            // owner state.
            if (active && readEpoch === windowStateEpochRef.current && state?.ok) {
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
                    windowStateEpochRef.current += 1;
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
                    windowStateEpochRef.current += 1;
                    setIsAlwaysOnTop(res.on_top);
                }
            }
        } finally {
            isTransitioningRef.current = false;
        }
    }, []);

    const handleToggleAlwaysOnTop = useCallback(async () => {
        if (isPinningRef.current) {
            return { applied: false, code: 'busy' };
        }
        isPinningRef.current = true;
        try {
            const nextState = !isAlwaysOnTop;
            const res = await setAlwaysOnTop(nextState);
            if (res?.ok && typeof res.on_top === 'boolean') {
                windowStateEpochRef.current += 1;
                setIsAlwaysOnTop(res.on_top);
                return { applied: true, on_top: res.on_top };
            }
            // Bridge refused or failed: keep the previous coherent
            // state and return the sanitized failure payload (#347).
            return res?.ok === false
                ? { applied: false, code: res.code, message: res.message }
                : { applied: false, code: 'unknown' };
        } finally {
            isPinningRef.current = false;
        }
    }, [isAlwaysOnTop]);

    const handleMinimize = useCallback(async () => {
        const res = await minimizeDesktopWindow();
        if (typeof window !== 'undefined') {
            window.__lastMinimizeResult = res;
        }
        return res;
    }, []);

    const handleClose = useCallback(async () => {
        await closeDesktopWindow();
    }, []);

    const handleOpenSettings = useCallback(() => {
        setIsSettingsOpen(true);
    }, []);

    const handleCloseSettings = useCallback(() => {
        shouldFocusSettingsButtonRef.current = true;
        setIsSettingsOpen(false);
    }, []);

    // After settings closes, the companion header (with the gear
    // button that opened the workspace) is re-mounted. Restore focus
    // there so keyboard users are not stranded at the end of the DOM.
    // The ref is null while settings is open (the button unmounts), so
    // the focus must happen in this post-commit effect.
    useEffect(() => {
        if (!isSettingsOpen && shouldFocusSettingsButtonRef.current) {
            shouldFocusSettingsButtonRef.current = false;
            settingsButtonRef.current?.focus();
        }
    }, [isSettingsOpen]);

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
            // #347: settings is a companion-mode composition swap. The
            // single useChat() in ChatWindow is untouched by this branch.
            if (isSettingsOpen) {
                return (
                    <SettingsWorkspace
                        onReturn={handleCloseSettings}
                        isAlwaysOnTop={isAlwaysOnTop}
                        onToggleAlwaysOnTop={handleToggleAlwaysOnTop}
                    />
                );
            }
            return (
                <CompanionLayout
                    {...chatModel}
                    onEnterPresence={handleEnterPresence}
                    onOpenSettings={handleOpenSettings}
                    settingsButtonRef={settingsButtonRef}
                    auxiliarySlot={
                        <KatherineStateSidebar emotionState={chatModel.emotionState} />
                    }
                />
            );
        },
        [
            mode,
            isAlwaysOnTop,
            isSettingsOpen,
            handleEnterPresence,
            handleReturnToCompanion,
            handleToggleAlwaysOnTop,
            handleMinimize,
            handleClose,
            handleOpenSettings,
            handleCloseSettings,
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
