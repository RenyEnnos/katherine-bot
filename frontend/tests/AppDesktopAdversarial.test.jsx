import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [
            { role: 'user', content: 'SECRET_USER_TOKEN_12345' },
            { role: 'assistant', content: 'Confidential assistant reply' },
        ],
        input: 'SECRET_UNSENT_INPUT_DRAFT',
        setInput: vi.fn(),
        isLoading: false,
        emotionState: {
            schema_version: 1,
            mood_label: 'ALEGRE',
            pad: { pleasure: 0.8, arousal: 0.5, dominance: 0.3 },
            dominant_emotions: [{ name: 'joy', intensity: 0.95 }],
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
import KatherinePresence from '../src/features/katherine-face/KatherinePresence.jsx';
import {
    setPresenceMode,
    setAlwaysOnTop,
    getWindowState,
    closeDesktopWindow,
    minimizeDesktopWindow,
} from '../src/lib/desktopBridge.js';

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
        minimize_window: vi.fn(async () => ({
            ok: true,
        })),
        health: vi.fn(async () => ({
            ok: true,
            api_version: 3,
        })),
    };

    window.pywebview = { api: pywebviewApi };
}

describe('Adversarial Stress Suite — Frontend Floating Presence', () => {
    beforeEach(() => {
        chatHarness.calls = 0;
        setupBridge();
        document.body.innerHTML = '';
    });

    describe('1. Rapid Mode Switching Stress Tests', () => {
        it('survives rapid successive mode transitions without crashing or desyncing DOM state', async () => {
            render(<AppDesktop />);

            const root = screen.getByTestId('app-desktop-root');
            expect(root).toHaveAttribute('data-desktop-mode', 'companion');

            // Rapidly enter presence
            const enterBtn = screen.getByTestId('companion-enter-presence-btn');
            await act(async () => {
                fireEvent.click(enterBtn);
            });
            expect(root).toHaveAttribute('data-desktop-mode', 'presence');

            // Rapid alternation: 10 cycles back and forth
            for (let i = 0; i < 10; i++) {
                const returnBtn = screen.getByTestId('presence-return-btn');
                await act(async () => {
                    fireEvent.click(returnBtn);
                });
                expect(root).toHaveAttribute('data-desktop-mode', 'companion');

                const presenceBtn = screen.getByTestId('companion-enter-presence-btn');
                await act(async () => {
                    fireEvent.click(presenceBtn);
                });
                expect(root).toHaveAttribute('data-desktop-mode', 'presence');
            }

            expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();
            expect(screen.queryByTestId('companion-layout')).toBeNull();
        });

        it('handles rapid repeated pin button clicks safely', async () => {
            render(<AppDesktop />);

            // Enter presence
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            const pinBtn = screen.getByTestId('presence-pin-btn');

            // Rapid fire 10 clicks on pin button
            for (let i = 0; i < 10; i++) {
                await act(async () => {
                    fireEvent.click(pinBtn);
                });
            }

            expect(pywebviewApi.set_always_on_top).toHaveBeenCalledTimes(10);
            expect(pinBtn).toBeInTheDocument();
        });

        it('handles intermittent bridge mutation failures during rapid switching without ghost state', async () => {
            let attempt = 0;
            pywebviewApi.set_presence_mode = vi.fn(async (enabled) => {
                attempt += 1;
                // Fail odd attempts
                if (attempt % 2 === 1) {
                    return {
                        ok: false,
                        code: 'window_mutation_failed',
                        message: 'Synthetic GTK timeout',
                    };
                }
                return {
                    ok: true,
                    mode: enabled ? 'presence' : 'companion',
                    on_top: false,
                    width: enabled ? 200 : 1280,
                    height: enabled ? 200 : 800,
                };
            });

            render(<AppDesktop />);
            const root = screen.getByTestId('app-desktop-root');
            expect(root).toHaveAttribute('data-desktop-mode', 'companion');

            const enterBtn = screen.getByTestId('companion-enter-presence-btn');
            // Attempt 1: bridge fails -> UI must remain companion
            await act(async () => {
                fireEvent.click(enterBtn);
            });
            expect(root).toHaveAttribute('data-desktop-mode', 'companion');
            expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
            expect(screen.queryByTestId('katherine-presence-surface')).toBeNull();

            // Attempt 2: bridge succeeds -> UI transitions to presence
            await act(async () => {
                fireEvent.click(enterBtn);
            });
            expect(root).toHaveAttribute('data-desktop-mode', 'presence');
            expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();
            expect(screen.queryByTestId('companion-layout')).toBeNull();
        });
    });

    describe('2. Strict Privacy Isolation Under Adversarial Inspection', () => {
        it('guarantees zero confidential data, messages, or composer input exists anywhere in DOM during presence', async () => {
            render(<AppDesktop />);

            // Pre-condition: secrets exist in companion mode
            expect(screen.getByText('SECRET_USER_TOKEN_12345')).toBeInTheDocument();
            expect(screen.getByText('Confidential assistant reply')).toBeInTheDocument();
            expect(screen.getByDisplayValue('SECRET_UNSENT_INPUT_DRAFT')).toBeInTheDocument();

            // Transition to presence mode
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            // Adversarial audit of document body HTML
            const fullHtml = document.body.innerHTML;
            expect(fullHtml).not.toContain('SECRET_USER_TOKEN_12345');
            expect(fullHtml).not.toContain('Confidential assistant reply');
            expect(fullHtml).not.toContain('SECRET_UNSENT_INPUT_DRAFT');
            expect(fullHtml).not.toContain('textarea');
            expect(fullHtml).not.toContain('input');
            expect(fullHtml).not.toContain('valence');
            expect(fullHtml).not.toContain('arousal');
            expect(fullHtml).not.toContain('dominance');

            // DOM structure check
            expect(screen.queryByRole('textbox')).toBeNull();
            expect(screen.queryByTestId('companion-history')).toBeNull();
            expect(screen.queryByTestId('companion-layout')).toBeNull();
            expect(screen.queryByTestId('emotion-panel')).toBeNull();
            expect(screen.queryByTestId('privacy-panel')).toBeNull();
        });
    });

    describe('3. Drag Handle vs Button Hit-Testing & Event Isolation', () => {
        it('verifies control buttons stop propagation and do not bubble to drag handle', () => {
            const onReturn = vi.fn();
            const onClose = vi.fn();
            const onMinimize = vi.fn();
            const onToggle = vi.fn();

            render(
                <KatherinePresence
                    emotionState={null}
                    isLoading={false}
                    onReturnToCompanion={onReturn}
                    onClose={onClose}
                    onMinimize={onMinimize}
                    onToggleAlwaysOnTop={onToggle}
                    isAlwaysOnTop={false}
                />,
            );

            const dragHandle = screen.getByTestId('katherine-presence-drag-handle');
            let dragHandleReceivedMouseDown = false;
            dragHandle.addEventListener('mousedown', () => {
                dragHandleReceivedMouseDown = true;
            });

            // Test return button
            const returnBtn = screen.getByTestId('presence-return-btn');
            const evt1 = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            returnBtn.dispatchEvent(evt1);
            expect(dragHandleReceivedMouseDown).toBe(false);

            // Test minimize button
            const minBtn = screen.getByTestId('presence-minimize-btn');
            const evt2 = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            minBtn.dispatchEvent(evt2);
            expect(dragHandleReceivedMouseDown).toBe(false);

            // Test pin button
            const pinBtn = screen.getByTestId('presence-pin-btn');
            const evt3 = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            pinBtn.dispatchEvent(evt3);
            expect(dragHandleReceivedMouseDown).toBe(false);

            // Test close button
            const closeBtn = screen.getByTestId('presence-close-btn');
            const evt4 = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            closeBtn.dispatchEvent(evt4);
            expect(dragHandleReceivedMouseDown).toBe(false);
        });

        it('verifies KatherineFace has pointer-events: none class so drag events pass to handle', () => {
            render(
                <KatherinePresence
                    emotionState={null}
                    isLoading={false}
                    onReturnToCompanion={vi.fn()}
                    onClose={vi.fn()}
                    onMinimize={vi.fn()}
                    onToggleAlwaysOnTop={vi.fn()}
                    isAlwaysOnTop={false}
                />,
            );

            const dragHandle = screen.getByTestId('katherine-presence-drag-handle');
            expect(dragHandle).toHaveClass('pywebview-drag-region');
            expect(dragHandle).toHaveClass('katherine-presence__drag-handle');

            const faceContainer = dragHandle.firstElementChild;
            expect(faceContainer).toHaveClass('katherine-face--presence');
        });
    });

    describe('4. Boundary, Typing, and Error Resilience in Bridge Client', () => {
        it('rejects all non-boolean types in setPresenceMode', async () => {
            const invalidValues = [
                1, 0, -1, 100, 'true', 'false', '', null, undefined, {}, [], () => {}, Symbol('test'),
            ];

            for (const val of invalidValues) {
                const res = await setPresenceMode(val);
                expect(res.ok).toBe(false);
                expect(res.code).toBe('invalid_input');
                expect(res.message).toBe('enabled must be a boolean');
            }
        });

        it('rejects all non-boolean types in setAlwaysOnTop', async () => {
            const invalidValues = [
                1, 0, 'true', 'false', null, undefined, {}, [], () => {},
            ];

            for (const val of invalidValues) {
                const res = await setAlwaysOnTop(val);
                expect(res.ok).toBe(false);
                expect(res.code).toBe('invalid_input');
                expect(res.message).toBe('enabled must be a boolean');
            }
        });

        it('handles bridge exceptions gracefully without crashing or throwing to caller', async () => {
            const failingWindow = {
                pywebview: {
                    api: {
                        set_presence_mode: vi.fn(async () => {
                            throw new Error('GTK IPC pipe broken');
                        }),
                        set_always_on_top: vi.fn(async () => {
                            throw new Error('WebKit IPC disconnected');
                        }),
                        window_state: vi.fn(async () => {
                            throw new Error('X11 server died');
                        }),
                        close_window: vi.fn(async () => {
                            throw new Error('Process killed');
                        }),
                        minimize_window: vi.fn(async () => {
                            throw new Error('GTK minimize failed');
                        }),
                    },
                },
            };

            const r1 = await setPresenceMode(true, failingWindow);
            expect(r1.ok).toBe(false);
            expect(r1.code).toBe('bridge_error');

            const r2 = await setAlwaysOnTop(true, failingWindow);
            expect(r2.ok).toBe(false);
            expect(r2.code).toBe('bridge_error');

            const r3 = await getWindowState(failingWindow);
            expect(r3.ok).toBe(false);
            expect(r3.code).toBe('bridge_error');

            const r4 = await closeDesktopWindow(failingWindow);
            expect(r4.ok).toBe(false);
            expect(r4.code).toBe('bridge_error');

            const r5 = await minimizeDesktopWindow(failingWindow);
            expect(r5.ok).toBe(false);
            expect(r5.code).toBe('bridge_error');
        });

        it('handles malformed payloads from backend gracefully', async () => {
            const malformedWindow = {
                pywebview: {
                    api: {
                        set_presence_mode: vi.fn(async () => 'not a json object'),
                        set_always_on_top: vi.fn(async () => 42),
                        window_state: vi.fn(async () => null),
                        close_window: vi.fn(async () => undefined),
                        minimize_window: vi.fn(async () => 123),
                    },
                },
            };

            const r1 = await setPresenceMode(true, malformedWindow);
            expect(r1.ok).toBe(false);
            expect(r1.code).toBe('unknown');

            const r2 = await setAlwaysOnTop(true, malformedWindow);
            expect(r2.ok).toBe(false);
            expect(r2.code).toBe('unknown');

            const r3 = await getWindowState(malformedWindow);
            expect(r3.ok).toBe(false);
            expect(r3.code).toBe('unknown');

            const r4 = await closeDesktopWindow(malformedWindow);
            expect(r4.ok).toBe(false);
            expect(r4.code).toBe('unknown');

            const r5 = await minimizeDesktopWindow(malformedWindow);
            expect(r5.ok).toBe(false);
            expect(r5.code).toBe('unknown');
        });

        it('returns honest bridge_unavailable across all window control methods when bridge is missing (Blocker 3)', async () => {
            const emptyWindow = {};
            const methods = [
                () => setPresenceMode(true, emptyWindow),
                () => setAlwaysOnTop(true, emptyWindow),
                () => getWindowState(emptyWindow),
                () => closeDesktopWindow(emptyWindow),
                () => minimizeDesktopWindow(emptyWindow),
            ];

            for (const fn of methods) {
                const res = await fn();
                expect(res.ok).toBe(false);
                expect(res.code).toBe('bridge_unavailable');
                expect(res.message).toBe('Desktop window control is unavailable.');
            }
        });
    });
});
