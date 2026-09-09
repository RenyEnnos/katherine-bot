import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [{ role: 'user', content: 'Minha mensagem confidencial' }],
        input: 'Texto no composer',
        setInput: vi.fn(),
        isLoading: false,
        emotionState: {
            schema_version: 1,
            mood_label: 'ALEGRE',
            pad: { pleasure: 0.6, arousal: 0.4, dominance: 0.2 },
            dominant_emotions: [{ name: 'joy', intensity: 0.9 }],
            timestamp: 1700000000,
        },
        messagesEndRef: { current: null },
        inputRef: { current: null },
        handleSend: vi.fn(),
        clearScreen: vi.fn(),
        transport: {
            mode: 'desktop',
            runPrivacyOp: vi.fn(async () => ({ status: 'applied' })),
        },
    },
}));

vi.mock('../src/features/chat/hooks/useChat', () => ({
    useChat: () => {
        chatHarness.calls += 1;
        return chatHarness.model;
    },
}));

import AppDesktop from '../src/AppDesktop.jsx';
import {
    setPresenceMode,
    setAlwaysOnTop,
    getWindowState,
    closeDesktopWindow,
} from '../src/lib/desktopBridge.js';

if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
    HTMLElement.prototype.scrollIntoView = () => {};
}

let pywebviewApi;

function setupBridge() {
    pywebviewApi = {
        set_presence_mode: vi.fn(async (enabled) => ({
            ok: true,
            mode: enabled ? 'presence' : 'companion',
            on_top: false,
            width: enabled ? 200 : 1280,
            height: enabled ? 200 : 800,
        })),
        set_always_on_top: vi.fn(async (enabled) => ({
            ok: true,
            on_top: enabled,
        })),
        window_state: vi.fn(async () => ({
            ok: true,
            mode: 'companion',
            on_top: false,
            width: 1280,
            height: 800,
        })),
        close_window: vi.fn(async () => ({
            ok: true,
        })),
        health: vi.fn(async () => ({
            ok: true,
            api_version: 3,
        })),
    };

    window.pywebview = { api: pywebviewApi };
}

function resetState() {
    chatHarness.calls = 0;
    setupBridge();
    document.body.innerHTML = '';
}

describe('AppDesktop Presence Mode Integration', () => {
    beforeEach(resetState);

    it('initializes in companion mode with solid dark background and single chat model authority', async () => {
        render(<AppDesktop />);

        expect(chatHarness.calls).toBe(1);
        const root = screen.getByTestId('app-desktop-root');
        expect(root).toHaveClass('app-desktop--companion');
        expect(root).toHaveClass('bg-gray-900');
        expect(root).toHaveAttribute('data-desktop-mode', 'companion');
        expect(root.style.background).not.toBe('transparent');

        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.getByTestId('companion-enter-presence-btn')).toBeInTheDocument();
        expect(screen.queryByTestId('katherine-presence-surface')).toBeNull();
    });

    it('transitions smoothly to presence mode, unmounting all conversation data and applying transparent background', async () => {
        render(<AppDesktop />);

        const enterBtn = screen.getByTestId('companion-enter-presence-btn');
        await act(async () => {
            fireEvent.click(enterBtn);
        });

        expect(pywebviewApi.set_presence_mode).toHaveBeenCalledWith(true);

        const root = screen.getByTestId('app-desktop-root');
        expect(root).toHaveClass('app-desktop--presence');
        expect(root).not.toHaveClass('bg-gray-900');
        expect(root).toHaveAttribute('data-desktop-mode', 'presence');
        expect(root.style.background).toBe('transparent');

        // Verify KatherinePresence is mounted
        expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();

        // Strict privacy assertion: CompanionLayout and all conversation DOM are completely unmounted
        expect(screen.queryByTestId('companion-layout')).toBeNull();
        expect(screen.queryByTestId('companion-history')).toBeNull();
        expect(screen.queryByRole('textbox')).toBeNull();
        expect(screen.queryByText('Minha mensagem confidencial')).toBeNull();
        expect(screen.queryByText('Texto no composer')).toBeNull();

        // ChatWindow remains mounted; re-rendered with new layout
        expect(chatHarness.calls).toBeGreaterThanOrEqual(1);
    });

    it('toggles always-on-top in presence mode through the bridge', async () => {
        render(<AppDesktop />);

        // Enter presence
        await act(async () => {
            fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
        });

        const pinBtn = screen.getByTestId('presence-pin-btn');
        expect(pinBtn).toHaveAttribute('aria-pressed', 'false');

        // Toggle on
        await act(async () => {
            fireEvent.click(pinBtn);
        });
        expect(pywebviewApi.set_always_on_top).toHaveBeenCalledWith(true);
        expect(pinBtn).toHaveAttribute('aria-pressed', 'true');

        // Toggle off
        await act(async () => {
            fireEvent.click(pinBtn);
        });
        expect(pywebviewApi.set_always_on_top).toHaveBeenCalledWith(false);
        expect(pinBtn).toHaveAttribute('aria-pressed', 'false');
    });

    it('returns from presence mode back to companion mode cleanly', async () => {
        render(<AppDesktop />);

        // Enter presence
        await act(async () => {
            fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
        });

        expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();

        // Click return button
        const returnBtn = screen.getByTestId('presence-return-btn');
        await act(async () => {
            fireEvent.click(returnBtn);
        });

        expect(pywebviewApi.set_presence_mode).toHaveBeenCalledWith(false);

        // Root restored to companion
        const root = screen.getByTestId('app-desktop-root');
        expect(root).toHaveClass('app-desktop--companion');
        expect(root).toHaveClass('bg-gray-900');
        expect(root).toHaveAttribute('data-desktop-mode', 'companion');
        expect(root.style.background).not.toBe('transparent');

        // CompanionLayout restored, KatherinePresence unmounted
        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.queryByTestId('katherine-presence-surface')).toBeNull();

        // History is back
        expect(screen.getByText('Minha mensagem confidencial')).toBeInTheDocument();
    });

    it('calls closeDesktopWindow when close button is clicked in presence mode', async () => {
        render(<AppDesktop />);

        await act(async () => {
            fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
        });

        const closeBtn = screen.getByTestId('presence-close-btn');
        await act(async () => {
            fireEvent.click(closeBtn);
        });

        expect(pywebviewApi.close_window).toHaveBeenCalledTimes(1);
    });
});

describe('desktopBridge window control client functions (unmocked)', () => {
    function makeBridgeWindow(api = {}) {
        return {
            addEventListener: () => {},
            pywebview: { api },
        };
    }

    it('setPresenceMode calls api.set_presence_mode with boolean parameter', async () => {
        let calledWith = null;
        const fakeWindow = makeBridgeWindow({
            set_presence_mode: async (val) => {
                calledWith = val;
                return { ok: true, mode: 'presence', on_top: false, width: 200, height: 200 };
            },
        });

        const res = await setPresenceMode(true, fakeWindow);
        expect(calledWith).toBe(true);
        expect(res).toEqual({ ok: true, mode: 'presence', on_top: false, width: 200, height: 200 });
    });

    it('setPresenceMode validates parameter and rejects non-boolean', async () => {
        const res = await setPresenceMode('invalid');
        expect(res).toEqual({
            ok: false,
            code: 'invalid_input',
            message: 'enabled must be a boolean',
        });
    });

    it('setPresenceMode provides graceful fallback when pywebview is absent', async () => {
        const res = await setPresenceMode(true, {});
        expect(res).toEqual({
            ok: true,
            mode: 'presence',
            on_top: false,
            fallback: true,
        });
    });

    it('setAlwaysOnTop calls api.set_always_on_top and provides graceful fallback', async () => {
        let calledWith = null;
        const fakeWindow = makeBridgeWindow({
            set_always_on_top: async (val) => {
                calledWith = val;
                return { ok: true, on_top: val };
            },
        });

        const res = await setAlwaysOnTop(true, fakeWindow);
        expect(calledWith).toBe(true);
        expect(res).toEqual({ ok: true, on_top: true });

        // Fallback when api missing
        const fallbackRes = await setAlwaysOnTop(true, {});
        expect(fallbackRes).toEqual({ ok: true, on_top: true, fallback: true });
    });

    it('getWindowState calls api.window_state and provides fallback', async () => {
        const fakeWindow = makeBridgeWindow({
            window_state: async () => ({
                ok: true,
                mode: 'presence',
                on_top: true,
                width: 200,
                height: 200,
            }),
        });

        const res = await getWindowState(fakeWindow);
        expect(res).toEqual({
            ok: true,
            mode: 'presence',
            on_top: true,
            width: 200,
            height: 200,
        });

        // Fallback
        const fallbackRes = await getWindowState({});
        expect(fallbackRes).toEqual({
            ok: true,
            mode: 'companion',
            on_top: false,
            fallback: true,
        });
    });

    it('closeDesktopWindow calls api.close_window and handles fallback', async () => {
        let closeCalled = false;
        const fakeWindow = makeBridgeWindow({
            close_window: async () => {
                closeCalled = true;
                return { ok: true };
            },
        });

        const res = await closeDesktopWindow(fakeWindow);
        expect(closeCalled).toBe(true);
        expect(res).toEqual({ ok: true });

        // Fallback
        let windowClosed = false;
        const fallbackRes = await closeDesktopWindow({
            close: () => { windowClosed = true; },
        });
        expect(windowClosed).toBe(true);
        expect(fallbackRes).toEqual({ ok: true, fallback: true });
    });
});
