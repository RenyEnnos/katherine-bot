import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [],
        input: '',
        setInput: vi.fn(),
        isLoading: false,
        emotionState: null,
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

const faceHarness = vi.hoisted(() => ({ current: null }));

vi.mock('../src/features/chat/hooks/useChat', () => ({
    useChat: () => {
        chatHarness.calls += 1;
        return chatHarness.model;
    },
}));

vi.mock('../src/features/katherine-face/KatherineFace.jsx', () => ({
    default: (props) => {
        faceHarness.current = props;
        return (
            <div
                data-testid="katherine-face"
                aria-hidden="true"
                className={props.className}
            />
        );
    },
}));

import AppDesktop from '../src/AppDesktop.jsx';

if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
    HTMLElement.prototype.scrollIntoView = () => {};
}

const validEmotionState = {
    schema_version: 1,
    mood_label: 'NEUTRA',
    pad: { pleasure: 0.2, arousal: 0.1, dominance: -0.1 },
    dominant_emotions: [{ name: 'gratitude', intensity: 0.8 }],
    timestamp: 1700000000,
};

function resetModel() {
    chatHarness.calls = 0;
    Object.assign(chatHarness.model, {
        messages: [],
        input: '',
        isLoading: false,
        emotionState: null,
    });
    faceHarness.current = null;
    document.body.innerHTML = '';
    delete window.pywebview;
}

describe('AppDesktop companion integration', () => {
    beforeEach(resetModel);

    it('uses one chat model and places the empty desktop conversation beside the dominant face', () => {
        render(<AppDesktop />);

        expect(chatHarness.calls).toBe(1);
        expect(screen.getByTestId('companion-layout')).toBeInTheDocument();
        expect(screen.getByTestId('companion-presence')).toContainElement(
            screen.getByTestId('katherine-face'),
        );
        expect(screen.getByTestId('katherine-face').closest('header')).toBeNull();
        expect(screen.getByText(/comece uma conversa com a katherine/i)).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toBeInTheDocument();
        expect(faceHarness.current).toEqual(expect.objectContaining({
            emotionState: null,
            isLoading: false,
        }));

        // Auxiliary slot mounts KatherineStateSidebar with unavailable state when emotionState is null
        const auxSlot = screen.getByTestId('companion-auxiliary-slot');
        const sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(auxSlot).toContainElement(sidebar);
        expect(sidebar).toHaveTextContent('Estado');
        expect(sidebar).toHaveTextContent('estado indisponível');
        expect(sidebar).not.toHaveTextContent('serena');
        expect(sidebar).not.toHaveTextContent('energia estável');
    });

    it('passes a valid emotion state and loading status through the existing desktop model', () => {
        chatHarness.model.emotionState = validEmotionState;
        chatHarness.model.isLoading = true;

        render(<AppDesktop />);

        expect(faceHarness.current).toEqual(expect.objectContaining({
            emotionState: validEmotionState,
            isLoading: true,
        }));
        expect(screen.getByRole('status')).toHaveTextContent('Preparando resposta…');
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toBeDisabled();

        // KatherineStateSidebar displays mapped state inside auxiliarySlot
        const auxSlot = screen.getByTestId('companion-auxiliary-slot');
        const sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(auxSlot).toContainElement(sidebar);
        expect(sidebar).toHaveTextContent('grata');
        expect(sidebar).toHaveTextContent('energia estável');
        expect(screen.queryByRole('progressbar')).toBeNull();
    });

    it('keeps history and technical error copy in the real desktop conversation rail', () => {
        chatHarness.model.messages = [
            { role: 'user', content: 'Mensagem anterior' },
            { role: 'system', content: 'Erro ao falar com a Katherine. Tente novamente.' },
        ];

        render(<AppDesktop />);

        const history = screen.getByTestId('companion-history');
        expect(history).toHaveTextContent('Mensagem anterior');
        expect(history).toHaveTextContent(/erro ao falar com a katherine/i);
    });

    it('renders KatherineStateSidebar inside companion-auxiliary-slot and preserves conversation state', () => {
        chatHarness.model.messages = [
            { role: 'user', content: 'Conversa em andamento' },
            { role: 'assistant', content: 'Estou aqui com você.' },
        ];
        chatHarness.model.input = 'Rascunho de mensagem não enviada';
        chatHarness.model.emotionState = {
            schema_version: 1,
            mood_label: 'TRANQUILA',
            pad: { pleasure: 0.3, arousal: -0.4, dominance: 0.1 },
            dominant_emotions: [
                { name: 'trust', intensity: 0.7 },
                { name: 'anticipation', intensity: 0.5 },
            ],
            timestamp: 1700000000,
        };

        const { rerender } = render(<AppDesktop />);

        // Face remains dominant presence
        const presence = screen.getByTestId('companion-presence');
        expect(presence).toContainElement(screen.getByTestId('katherine-face'));

        // History and composer preserved
        expect(screen.getByTestId('companion-history')).toHaveTextContent('Conversa em andamento');
        expect(screen.getByTestId('companion-history')).toHaveTextContent('Estou aqui com você.');
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue('Rascunho de mensagem não enviada');

        // Auxiliary slot has sidebar with mapped state
        const auxSlot = screen.getByTestId('companion-auxiliary-slot');
        const sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(auxSlot).toContainElement(sidebar);
        expect(sidebar).toHaveTextContent('tranquila · curiosa');
        expect(sidebar).toHaveTextContent('energia baixa');

        // Emotion update preserves conversation and updates sidebar
        chatHarness.model.emotionState = {
            schema_version: 1,
            mood_label: 'ALEGRE',
            pad: { pleasure: 0.8, arousal: 0.5, dominance: 0.3 },
            dominant_emotions: [{ name: 'joy', intensity: 0.9 }],
            timestamp: 1700000100,
        };
        rerender(<AppDesktop />);

        expect(screen.getByTestId('companion-history')).toHaveTextContent('Conversa em andamento');
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue('Rascunho de mensagem não enviada');
        expect(screen.getByTestId('katherine-state-sidebar')).toHaveTextContent('alegre');
        expect(screen.getByTestId('katherine-state-sidebar')).toHaveTextContent('energia alta');
    });
});
