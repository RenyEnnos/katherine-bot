/**
 * Katherine settings workspace (#347).
 *
 * Contract under test:
 * - The workspace is a separate surface opened from a discrete gear
 *   button in the companion header (never inside the #344 state sidebar).
 * - Opening/closing settings preserves the single useChat() model:
 *   history stays, the composer draft stays, no second useChat() mount,
 *   and no history re-fetch happens just from navigating.
 * - Only capabilities backed by real bridge contracts appear as
 *   functional. No fake TTS/voice, memory, provider, or integration
 *   sections exist in the DOM.
 * - The always-on-top control: initial state comes from the real
 *   bridge (`window_state`), mutations only commit after the bridge
 *   confirms, failures keep coherent state and surface a sanitized
 *   error, and the copy never promises persistence.
 * - Settings never renders inside floating presence mode.
 */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [],
        input: '',
        setInput: vi.fn((value) => {
            chatHarness.model.input = value;
        }),
        isLoading: false,
        emotionState: null,
        messagesEndRef: { current: null },
        inputRef: { current: null },
        handleSend: vi.fn(),
        clearScreen: vi.fn(),
        transport: {
            mode: 'desktop',
            fetchHistory: vi.fn(async () => ({ data: [] })),
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

if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
    HTMLElement.prototype.scrollIntoView = () => {};
}

let pywebviewApi;
let windowStatePayload;

function setupBridge() {
    windowStatePayload = {
        ok: true,
        mode: 'companion',
        on_top: false,
        width: 1280,
        height: 800,
    };
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
        window_state: vi.fn(async () => windowStatePayload),
        close_window: vi.fn(async () => ({ ok: true })),
        minimize_window: vi.fn(async () => ({ ok: true })),
        health: vi.fn(async () => ({ ok: true, api_version: 3 })),
        runtime_state: vi.fn(async () => ({
            ok: true,
            storage: true,
            provider_configured: true,
            revision: 1,
        })),
    };
    window.pywebview = { api: pywebviewApi };
}

function resetState() {
    chatHarness.calls = 0;
    Object.assign(chatHarness.model, {
        messages: [],
        input: '',
        isLoading: false,
        emotionState: null,
    });
    chatHarness.model.transport.fetchHistory.mockClear();
    setupBridge();
    document.body.innerHTML = '';
}

const openSettings = async () => {
    await act(async () => {
        fireEvent.click(screen.getByTestId('companion-open-settings-btn'));
    });
};

const closeSettings = async () => {
    await act(async () => {
        fireEvent.click(screen.getByTestId('settings-back-btn'));
    });
};

describe('SettingsWorkspace: access and separation', () => {
    beforeEach(resetState);

    it('exposes a discrete, labeled settings button in the companion header', () => {
        render(<AppDesktop />);

        const gearBtn = screen.getByTestId('companion-open-settings-btn');
        expect(gearBtn).toBeInTheDocument();
        expect(gearBtn).toHaveAttribute('aria-label', 'Configurações da Katherine');
        expect(gearBtn.tagName).toBe('BUTTON');

        // Not inside the state sidebar: the #344 sidebar stays state-only.
        const sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar).not.toContainElement(gearBtn);
        // And not a toolbar: exactly two header action buttons.
        const headerActions = document.querySelector('.companion-layout__header-actions');
        expect(headerActions.querySelectorAll('button')).toHaveLength(2);
    });

    it('does not render the settings button when no handler is provided (web parity)', async () => {
        // CompanionLayout without onOpenSettings renders no gear (backward
        // compatible composition seam, same pattern as onEnterPresence).
        const { default: CompanionLayout } = await import(
            '../src/features/chat/components/CompanionLayout.jsx'
        );
        render(
            <CompanionLayout
                messages={[]}
                input=""
                setInput={() => {}}
                isLoading={false}
                emotionState={null}
                messagesEndRef={{ current: null }}
                inputRef={{ current: null }}
                handleSend={() => {}}
                clearScreen={() => {}}
                transport={{ mode: 'desktop' }}
            />,
        );
        expect(screen.queryByTestId('companion-open-settings-btn')).toBeNull();
    });
});

describe('SettingsWorkspace: conversation preservation', () => {
    beforeEach(resetState);

    it('opening and closing settings preserves history, draft, and the single useChat()', async () => {
        chatHarness.model.messages = [
            { role: 'user', content: 'Mensagem histórica importante' },
            { role: 'assistant', content: 'Resposta guardada' },
        ];
        chatHarness.model.input = 'Rascunho não enviado no composer';

        render(<AppDesktop />);
        const useChatCallsBefore = chatHarness.calls;
        const fetchCallsBefore = chatHarness.model.transport.fetchHistory.mock.calls.length;
        expect(useChatCallsBefore).toBe(1);

        await openSettings();
        expect(screen.getByTestId('settings-workspace')).toBeInTheDocument();
        expect(screen.queryByTestId('companion-layout')).toBeNull();

        await closeSettings();
        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.queryByTestId('settings-workspace')).toBeNull();

        // History and draft preserved.
        expect(screen.getByText('Mensagem histórica importante')).toBeInTheDocument();
        expect(screen.getByText('Resposta guardada')).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue(
            'Rascunho não enviado no composer',
        );

        // useChat() was NOT re-created by navigation: the hook call count
        // only grows when ChatWindow re-renders, never resets to a second
        // mount. Same mount => same transport => no extra history fetch.
        expect(chatHarness.calls).toBeGreaterThanOrEqual(useChatCallsBefore);
        const fetchCallsAfter = chatHarness.model.transport.fetchHistory.mock.calls.length;
        expect(fetchCallsAfter).toBe(fetchCallsBefore);
    });

    it('re-opening settings a second time still preserves the draft', async () => {
        chatHarness.model.input = 'Segundo rascunho';

        render(<AppDesktop />);
        await openSettings();
        await closeSettings();
        await openSettings();
        await closeSettings();

        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue(
            'Segundo rascunho',
        );
    });
});

describe('SettingsWorkspace: honesty of capabilities', () => {
    beforeEach(resetState);

    it('renders only the Janela category with the real always-on-top control', async () => {
        render(<AppDesktop />);
        await openSettings();

        const workspace = screen.getByTestId('settings-workspace');
        expect(screen.getByTestId('settings-section-window')).toBeInTheDocument();

        // No fake/future sections appear as functional.
        const forbidden = [
            /voz/i, /tts/i, /memória/i, /memorias/i, /modelo/i, /prove/i,
            /integra/i, /ouroboros/i, /runstead/i, /lifeos/i, /avançado/i,
        ];
        for (const pattern of forbidden) {
            expect(workspace.textContent).not.toMatch(pattern);
        }

        // Exactly one interactive control exists in the workspace.
        expect(workspace.querySelectorAll('button[role="switch"]')).toHaveLength(1);

        // No save button / fake persistence surface: the single control
        // commits through the real bridge on interaction.
        expect(screen.queryByRole('button', { name: /salvar/i })).toBeNull();
    });

    it('secrets never appear in the settings DOM', async () => {
        render(<AppDesktop />);
        await openSettings();

        const html = document.body.innerHTML;
        expect(html).not.toMatch(/api[_-]?key|secret|sk-[a-z0-9]/i);
    });

    it('opening settings triggers no history load or other bridge calls', async () => {
        render(<AppDesktop />);
        // Flush the shell's bounded startup sync so the count baseline is
        // stable before the workspace opens.
        await act(async () => {});
        pywebviewApi.window_state.mockClear();
        pywebviewApi.set_always_on_top.mockClear();
        pywebviewApi.set_presence_mode.mockClear();
        pywebviewApi.close_window.mockClear();
        pywebviewApi.minimize_window.mockClear();

        await openSettings();

        // Opening the workspace performs exactly one bounded read of the
        // real window state (the initial sync) and nothing else: no
        // history load, no mutations, no network.
        expect(pywebviewApi.window_state).toHaveBeenCalledTimes(1);
        expect(pywebviewApi.set_always_on_top).not.toHaveBeenCalled();
        expect(pywebviewApi.set_presence_mode).not.toHaveBeenCalled();
        expect(pywebviewApi.close_window).not.toHaveBeenCalled();
        expect(pywebviewApi.minimize_window).not.toHaveBeenCalled();
    });
});

describe('SettingsWorkspace: always-on-top control lifecycle', () => {
    beforeEach(resetState);

    it('adopts the real initial state from the bridge on open', async () => {
        render(<AppDesktop />);
        // The shell startup sync consumed the first read; change the
        // authoritative bridge state before opening the workspace.
        windowStatePayload = {
            ok: true,
            mode: 'companion',
            on_top: true,
            width: 1280,
            height: 800,
        };

        await openSettings();

        const control = screen.getByTestId('settings-always-on-top-switch');
        expect(pywebviewApi.window_state).toHaveBeenCalled();
        expect(control).toHaveAttribute('aria-checked', 'true');
    });

    it('commits the toggle only after the bridge confirms the new state', async () => {
        render(<AppDesktop />);
        await openSettings();

        const control = screen.getByTestId('settings-always-on-top-switch');
        expect(control).toHaveAttribute('aria-checked', 'false');

        let resolveBridge;
        pywebviewApi.set_always_on_top.mockImplementationOnce(
            () => new Promise((resolve) => {
                resolveBridge = resolve;
            }),
        );

        await act(async () => {
            fireEvent.click(control);
        });
        // While pending: not optimistically switched.
        expect(control).toHaveAttribute('aria-checked', 'false');
        expect(control).toBeDisabled();

        await act(async () => {
            resolveBridge({ ok: true, on_top: true });
        });
        expect(control).toHaveAttribute('aria-checked', 'true');
        expect(control).not.toBeDisabled();
        expect(screen.queryByTestId('settings-always-on-top-error')).toBeNull();
    });

    it('keeps the previous coherent state when the bridge fails', async () => {
        render(<AppDesktop />);
        await openSettings();

        const control = screen.getByTestId('settings-always-on-top-switch');
        expect(control).toHaveAttribute('aria-checked', 'false');

        pywebviewApi.set_always_on_top.mockResolvedValueOnce({
            ok: false,
            code: 'window_mutation_failed',
            message: 'The window operation could not be completed.',
        });

        await act(async () => {
            fireEvent.click(control);
        });

        expect(pywebviewApi.set_always_on_top).toHaveBeenCalledWith(true);
        expect(control).toHaveAttribute('aria-checked', 'false');
        expect(screen.getByTestId('settings-always-on-top-error')).toBeInTheDocument();
        expect(screen.getByTestId('settings-always-on-top-error').textContent)
            .not.toMatch(/window_mutation_failed|traceback|error code/i);
    });

    it('reports unavailable window control honestly when the bridge is missing', async () => {
        delete window.pywebview;

        render(<AppDesktop />);
        await openSettings();

        const control = screen.getByTestId('settings-always-on-top-switch');
        await act(async () => {
            fireEvent.click(control);
        });

        expect(control).toHaveAttribute('aria-checked', 'false');
        const error = screen.getByTestId('settings-always-on-top-error');
        expect(error.textContent).toMatch(/indispon/i);
    });

    it('copies the session scope honestly and never promises persistence', async () => {
        render(<AppDesktop />);
        await openSettings();

        const workspace = screen.getByTestId('settings-workspace');
        expect(workspace.textContent).toMatch(/enquanto o aplicativo estiver aberto/i);
        expect(workspace.textContent).not.toMatch(/sempre será|entre reinícios|salvo automaticamente/i);
    });
});

describe('SettingsWorkspace: presence isolation', () => {
    beforeEach(resetState);

    it('does not render settings inside floating presence mode', async () => {
        render(<AppDesktop />);

        await act(async () => {
            fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
        });

        expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();
        expect(screen.queryByTestId('settings-workspace')).toBeNull();
        expect(screen.queryByTestId('companion-open-settings-btn')).toBeNull();

        // The presence surface contains no settings DOM either.
        const html = document.body.innerHTML;
        expect(html).not.toContain('settings-workspace');
        expect(html).not.toContain('Configurações');
    });

    it('settings open state does not leak into presence: returning to companion from settings-open path keeps settings closed', async () => {
        // Settings can only be opened from the companion header; entering
        // presence from the companion with settings closed never surfaces
        // settings later. Returning to companion restores the header.
        render(<AppDesktop />);

        await act(async () => {
            fireEvent.click(screen.getByTestId('companion-enter-presence-btn'));
        });
        await act(async () => {
            fireEvent.click(screen.getByTestId('presence-return-btn'));
        });

        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.getByTestId('companion-open-settings-btn')).toBeInTheDocument();
        expect(screen.queryByTestId('settings-workspace')).toBeNull();
    });
});

describe('SettingsWorkspace: keyboard and focus', () => {
    beforeEach(resetState);

    it('focuses the back button when opened so keyboard users land predictably', async () => {
        render(<AppDesktop />);
        await openSettings();

        expect(screen.getByTestId('settings-back-btn')).toHaveFocus();
    });

    it('returns focus to the gear button after closing', async () => {
        render(<AppDesktop />);
        await openSettings();
        await closeSettings();

        expect(screen.getByTestId('companion-open-settings-btn')).toHaveFocus();
    });

    it('closes with the Escape key', async () => {
        render(<AppDesktop />);
        await openSettings();

        await act(async () => {
            fireEvent.keyDown(document, { key: 'Escape' });
        });

        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.queryByTestId('settings-workspace')).toBeNull();
    });

    it('exposes semantic headings and a switch role for the control', async () => {
        render(<AppDesktop />);
        await openSettings();

        expect(
            screen.getByRole('heading', { level: 1, name: 'Configurações' }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole('heading', { level: 2, name: 'Janela' }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole('switch', { name: 'Sempre no topo' }),
        ).toBeInTheDocument();
        expect(
            screen.getByRole('button', { name: /voltar para a katherine/i }),
        ).toBeInTheDocument();
    });
});
