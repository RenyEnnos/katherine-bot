import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [{ role: 'user', content: 'Secret test token' }],
        input: 'Draft composer input',
        setInput: vi.fn(),
        isLoading: false,
        emotionState: {
            schema_version: 1,
            mood_label: 'ALEGRE',
            pad: { pleasure: 0.5, arousal: 0.5, dominance: 0.5 },
            dominant_emotions: [{ name: 'joy', intensity: 0.8 }],
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

if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
    HTMLElement.prototype.scrollIntoView = () => {};
}

let pywebviewApi;

function setupBridge(customOverrides = {}) {
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
        ...customOverrides,
    };

    window.pywebview = { api: pywebviewApi };
}

describe('Challenger 2 Empirical Verification: Native Minimization & Event Isolation', () => {
    beforeEach(() => {
        chatHarness.calls = 0;
        setupBridge();
        document.body.innerHTML = '';
    });

    describe('1. Native Minimization in KatherinePresence.jsx', () => {
        it('renders presence-minimize-btn with full accessibility attributes and toolbar role', () => {
            const onMinimize = vi.fn();
            render(
                <KatherinePresence
                    emotionState={null}
                    isLoading={false}
                    onReturnToCompanion={vi.fn()}
                    onClose={vi.fn()}
                    onMinimize={onMinimize}
                    onToggleAlwaysOnTop={vi.fn()}
                    isAlwaysOnTop={false}
                />,
            );

            const toolbar = screen.getByTestId('katherine-presence-controls');
            expect(toolbar).toHaveAttribute('role', 'toolbar');
            expect(toolbar).toHaveAttribute('aria-label', 'Controles da presença');

            const minimizeBtn = screen.getByTestId('presence-minimize-btn');
            expect(minimizeBtn).toBeInTheDocument();
            expect(toolbar).toContainElement(minimizeBtn);
            expect(minimizeBtn.tagName.toLowerCase()).toBe('button');
            expect(minimizeBtn).toHaveAttribute('type', 'button');
            expect(minimizeBtn).toHaveAttribute('aria-label', 'Minimizar');
            expect(minimizeBtn).toHaveAttribute('title', 'Minimizar');

            // Icon SVG must be aria-hidden so screen readers do not read decorative SVG
            const svgIcon = minimizeBtn.querySelector('svg');
            expect(svgIcon).not.toBeNull();
            expect(svgIcon).toHaveAttribute('aria-hidden', 'true');

            // Click triggers onMinimize
            fireEvent.click(minimizeBtn);
            expect(onMinimize).toHaveBeenCalledTimes(1);
        });

        it('supports keyboard navigation and activation on presence-minimize-btn', () => {
            const onMinimize = vi.fn();
            render(
                <KatherinePresence
                    emotionState={null}
                    isLoading={false}
                    onReturnToCompanion={vi.fn()}
                    onClose={vi.fn()}
                    onMinimize={onMinimize}
                    onToggleAlwaysOnTop={vi.fn()}
                    isAlwaysOnTop={false}
                />,
            );

            const minimizeBtn = screen.getByTestId('presence-minimize-btn');
            minimizeBtn.focus();
            expect(document.activeElement).toBe(minimizeBtn);

            // Native button responds to click generated by Space/Enter
            fireEvent.click(minimizeBtn);
            expect(onMinimize).toHaveBeenCalledTimes(1);
        });

        it('safely handles omitted onMinimize without errors', () => {
            render(
                <KatherinePresence
                    emotionState={null}
                    isLoading={false}
                    onReturnToCompanion={vi.fn()}
                    onClose={vi.fn()}
                    onToggleAlwaysOnTop={vi.fn()}
                    isAlwaysOnTop={false}
                />,
            );

            const minimizeBtn = screen.getByTestId('presence-minimize-btn');
            expect(() => fireEvent.click(minimizeBtn)).not.toThrow();
        });
    });

    describe('2. Drag Event Isolation & onMouseDown stopPropagation', () => {
        it('stops React synthetic mousedown propagation to parent React containers', () => {
            let parentReceivedMouseDown = false;
            const ParentWrapper = () => (
                <div onMouseDown={() => { parentReceivedMouseDown = true; }}>
                    <KatherinePresence
                        emotionState={null}
                        isLoading={false}
                        onReturnToCompanion={vi.fn()}
                        onClose={vi.fn()}
                        onMinimize={vi.fn()}
                        onToggleAlwaysOnTop={vi.fn()}
                        isAlwaysOnTop={false}
                    />
                </div>
            );

            render(<ParentWrapper />);
            const minimizeBtn = screen.getByTestId('presence-minimize-btn');

            fireEvent.mouseDown(minimizeBtn);

            // Because handleControlMouseDown calls e.stopPropagation(), parent React container never receives it
            expect(parentReceivedMouseDown).toBe(false);
        });

        it('stops native event propagation via stopPropagation and stopImmediatePropagation', () => {
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

            const minimizeBtn = screen.getByTestId('presence-minimize-btn');
            const mousedownEvent = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            const stopPropagationSpy = vi.spyOn(mousedownEvent, 'stopPropagation');
            const stopImmediatePropagationSpy = vi.spyOn(mousedownEvent, 'stopImmediatePropagation');

            minimizeBtn.dispatchEvent(mousedownEvent);

            expect(stopPropagationSpy).toHaveBeenCalled();
            expect(stopImmediatePropagationSpy).toHaveBeenCalled();
        });

        it('strictly isolates all ephemeral toolbar buttons from the pywebview drag handle', () => {
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
            let dragHandleReceived = false;
            dragHandle.addEventListener('mousedown', () => { dragHandleReceived = true; });

            const buttonIds = [
                'presence-return-btn',
                'presence-pin-btn',
                'presence-minimize-btn',
                'presence-close-btn',
            ];

            for (const testId of buttonIds) {
                const btn = screen.getByTestId(testId);
                const evt = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
                btn.dispatchEvent(evt);
                expect(dragHandleReceived).toBe(false);
            }
        });

        it('verifies CSS layout invariants for pywebview drag regions', () => {
            const cssPath = join(
                __dirname,
                '../src/features/katherine-face/KatherinePresence.css',
            );
            const css = readFileSync(cssPath, 'utf8');

            // Drag handle must have -webkit-app-region: drag
            expect(css).toMatch(/\.katherine-presence__drag-handle[\s\S]*?-webkit-app-region:\s*drag;/);

            // Ephemeral controls overlay must have -webkit-app-region: no-drag
            expect(css).toMatch(/\.katherine-presence__controls[\s\S]*?-webkit-app-region:\s*no-drag;/);

            // Buttons must have -webkit-app-region: no-drag
            expect(css).toMatch(/\.katherine-presence__btn[\s\S]*?-webkit-app-region:\s*no-drag;/);

            // Face must have pointer-events: none so dragging the face triggers the drag handle behind it
            expect(css).toMatch(/\.katherine-face--presence[\s\S]*?pointer-events:\s*none;/);
        });
    });

    describe('3. Stress Testing Rapid Clicking & Re-Entrancy Guards', () => {
        it('drops concurrent spam clicks on enter-presence button while transition is in flight', async () => {
            let resolveTransition;
            pywebviewApi.set_presence_mode = vi.fn(
                () => new Promise((resolve) => {
                    resolveTransition = resolve;
                }),
            );

            render(<AppDesktop />);
            const enterBtn = screen.getByTestId('companion-enter-presence-btn');

            // Fire 1st click: launches in-flight transition
            fireEvent.click(enterBtn);

            // Fire 20 rapid concurrent clicks while bridge call is pending
            for (let i = 0; i < 20; i++) {
                fireEvent.click(enterBtn);
            }

            // Flush microtasks so the initial bridge call runs
            await Promise.resolve();
            await Promise.resolve();

            // In-flight guard MUST have dropped all 20 re-entrant attempts! Exactly 1 call reached the bridge!
            expect(pywebviewApi.set_presence_mode).toHaveBeenCalledTimes(1);

            // Fire another 10 clicks while still waiting for backend resolution
            for (let i = 0; i < 10; i++) {
                fireEvent.click(enterBtn);
            }
            await Promise.resolve();
            expect(pywebviewApi.set_presence_mode).toHaveBeenCalledTimes(1);

            // Resolve the in-flight bridge operation
            await act(async () => {
                resolveTransition({
                    ok: true,
                    mode: 'presence',
                    on_top: false,
                    width: 200,
                    height: 200,
                });
            });

            // UI successfully enters presence
            expect(screen.getByTestId('app-desktop-root')).toHaveAttribute('data-desktop-mode', 'presence');
            expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();
        });

        it('drops concurrent spam clicks on return-to-companion button while transition is in flight', async () => {
            render(<AppDesktop />);
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();

            // Set up delayed bridge response for return
            let resolveReturn;
            pywebviewApi.set_presence_mode = vi.fn(
                () => new Promise((resolve) => {
                    resolveReturn = resolve;
                }),
            );

            const returnBtn = screen.getByTestId('presence-return-btn');

            // Fire 1st click
            fireEvent.click(returnBtn);

            // Spam 20 concurrent clicks
            for (let i = 0; i < 20; i++) {
                fireEvent.click(returnBtn);
            }

            await Promise.resolve();
            await Promise.resolve();

            // Re-entrancy guard MUST drop all 20 clicks: exactly 1 call reached bridge!
            expect(pywebviewApi.set_presence_mode).toHaveBeenCalledTimes(1);

            // Spam 10 more clicks
            for (let i = 0; i < 10; i++) {
                fireEvent.click(returnBtn);
            }
            await Promise.resolve();
            expect(pywebviewApi.set_presence_mode).toHaveBeenCalledTimes(1);

            // Complete transition
            await act(async () => {
                resolveReturn({
                    ok: true,
                    mode: 'companion',
                    on_top: false,
                    width: 1280,
                    height: 800,
                });
            });

            // Restored companion
            expect(screen.getByTestId('app-desktop-root')).toHaveAttribute('data-desktop-mode', 'companion');
            expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        });

        it('drops concurrent spam clicks on pin button while pin operation is in flight', async () => {
            render(<AppDesktop />);
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            let resolvePin;
            pywebviewApi.set_always_on_top = vi.fn(
                () => new Promise((resolve) => {
                    resolvePin = resolve;
                }),
            );

            const pinBtn = screen.getByTestId('presence-pin-btn');
            expect(pinBtn).toHaveAttribute('aria-pressed', 'false');

            // Fire 1st click
            fireEvent.click(pinBtn);

            // Spam 20 concurrent clicks
            for (let i = 0; i < 20; i++) {
                fireEvent.click(pinBtn);
            }

            await Promise.resolve();
            await Promise.resolve();

            // Re-entrancy guard MUST drop all 20 clicks: exactly 1 bridge call!
            expect(pywebviewApi.set_always_on_top).toHaveBeenCalledTimes(1);
            expect(pywebviewApi.set_always_on_top).toHaveBeenCalledWith(true);

            // Spam 10 more clicks while awaiting backend
            for (let i = 0; i < 10; i++) {
                fireEvent.click(pinBtn);
            }
            await Promise.resolve();
            expect(pywebviewApi.set_always_on_top).toHaveBeenCalledTimes(1);

            // Resolve pin operation
            await act(async () => {
                resolvePin({ ok: true, on_top: true });
            });

            expect(pinBtn).toHaveAttribute('aria-pressed', 'true');
        });

        it('releases in-flight guards when bridge operations fail so the user can retry', async () => {
            let attempt = 0;
            pywebviewApi.set_presence_mode = vi.fn(async () => {
                attempt += 1;
                if (attempt === 1) {
                    return { ok: false, code: 'window_mutation_failed', message: 'GTK failed' };
                }
                return { ok: true, mode: 'presence', on_top: false, width: 200, height: 200 };
            });

            render(<AppDesktop />);
            const enterBtn = screen.getByTestId('companion-enter-presence-btn');

            // 1st attempt fails
            await act(async () => {
                fireEvent.click(enterBtn);
            });
            expect(attempt).toBe(1);
            expect(screen.getByTestId('app-desktop-root')).toHaveAttribute('data-desktop-mode', 'companion');

            // In-flight guard MUST be released in finally block; retry must be accepted
            await act(async () => {
                fireEvent.click(enterBtn);
            });
            expect(attempt).toBe(2);
            expect(screen.getByTestId('app-desktop-root')).toHaveAttribute('data-desktop-mode', 'presence');
        });

        it('releases pin in-flight guard when setAlwaysOnTop fails so user can retry', async () => {
            render(<AppDesktop />);
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            let attempt = 0;
            pywebviewApi.set_always_on_top = vi.fn(async (enabled) => {
                attempt += 1;
                if (attempt === 1) {
                    return { ok: false, code: 'window_mutation_failed', message: 'Pin failed' };
                }
                return { ok: true, on_top: enabled };
            });

            const pinBtn = screen.getByTestId('presence-pin-btn');

            // 1st attempt fails
            await act(async () => {
                fireEvent.click(pinBtn);
            });
            expect(attempt).toBe(1);
            expect(pinBtn).toHaveAttribute('aria-pressed', 'false');

            // 2nd attempt succeeds
            await act(async () => {
                fireEvent.click(pinBtn);
            });
            expect(attempt).toBe(2);
            expect(pinBtn).toHaveAttribute('aria-pressed', 'true');
        });

        it('safely handles rapid minimize button clicks without unhandled rejections', async () => {
            render(<AppDesktop />);
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            const minBtn = screen.getByTestId('presence-minimize-btn');

            // Rapid fire 10 clicks on minimize button
            for (let i = 0; i < 10; i++) {
                await act(async () => {
                    fireEvent.click(minBtn);
                });
            }

            expect(pywebviewApi.minimize_window).toHaveBeenCalledTimes(10);
            expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();
        });

        it('correctly toggles pin back and forth across sequential settled clicks', async () => {
            let currentOnTop = false;
            pywebviewApi.set_always_on_top = vi.fn(async (enabled) => {
                currentOnTop = enabled;
                return { ok: true, on_top: enabled };
            });

            render(<AppDesktop />);
            await act(async () => {
                fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
            });

            const pinBtn = screen.getByTestId('presence-pin-btn');

            // Toggle 1: false -> true
            await act(async () => {
                fireEvent.click(pinBtn);
            });
            expect(currentOnTop).toBe(true);
            expect(pinBtn).toHaveAttribute('aria-pressed', 'true');

            // Toggle 2: true -> false
            await act(async () => {
                fireEvent.click(pinBtn);
            });
            expect(currentOnTop).toBe(false);
            expect(pinBtn).toHaveAttribute('aria-pressed', 'false');

            // Toggle 3: false -> true
            await act(async () => {
                fireEvent.click(pinBtn);
            });
            expect(currentOnTop).toBe(true);
            expect(pinBtn).toHaveAttribute('aria-pressed', 'true');
        });
    });
});
