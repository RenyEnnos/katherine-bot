import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const faceProps = vi.hoisted(() => ({ current: null }));

vi.mock('../src/features/katherine-face/KatherineFace.jsx', () => ({
    default: (props) => {
        faceProps.current = props;
        return (
            <div
                data-testid="katherine-face"
                aria-hidden="true"
                className={props.className}
            />
        );
    },
}));

import KatherinePresence from '../src/features/katherine-face/KatherinePresence.jsx';

const makeEmotionState = () => ({
    schema_version: 1,
    mood_label: 'NEUTRA',
    pad: { pleasure: 0.1, arousal: 0, dominance: 0.1 },
    dominant_emotions: [{ name: 'gratitude', intensity: 0.7 }],
    timestamp: 1700000000,
});

describe('KatherinePresence Component', () => {
    beforeEach(() => {
        faceProps.current = null;
        document.body.innerHTML = '';
    });

    it('renders the minimal presence surface with face inside the pywebview drag handle', () => {
        const emotionState = makeEmotionState();
        render(
            <KatherinePresence
                emotionState={emotionState}
                isLoading={false}
                onReturnToCompanion={vi.fn()}
                onClose={vi.fn()}
                onMinimize={vi.fn()}
                onToggleAlwaysOnTop={vi.fn()}
                isAlwaysOnTop={false}
            />,
        );

        const surface = screen.getByTestId('katherine-presence-surface');
        expect(surface).toHaveAttribute('role', 'region');
        expect(surface).toHaveAttribute('aria-label', 'Presença flutuante da Katherine');

        const dragHandle = screen.getByTestId('katherine-presence-drag-handle');
        expect(dragHandle).toHaveClass('katherine-presence__drag-handle');
        expect(dragHandle).toHaveClass('pywebview-drag-region');

        const face = screen.getByTestId('katherine-face');
        expect(dragHandle).toContainElement(face);
        expect(faceProps.current).toEqual(
            expect.objectContaining({
                emotionState,
                isLoading: false,
                className: 'katherine-face--presence',
            }),
        );
    });

    it('renders ephemeral control buttons with proper accessible roles and labels', () => {
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

        const controls = screen.getByTestId('katherine-presence-controls');
        expect(controls).toHaveAttribute('role', 'toolbar');
        expect(controls).toHaveAttribute('aria-label', 'Controles da presença');

        const returnBtn = screen.getByTestId('presence-return-btn');
        expect(returnBtn).toHaveAttribute('aria-label', 'Voltar ao companion');

        const minimizeBtn = screen.getByTestId('presence-minimize-btn');
        expect(minimizeBtn).toHaveAttribute('aria-label', 'Minimizar');
        expect(minimizeBtn).toHaveAttribute('title', 'Minimizar');

        const pinBtn = screen.getByTestId('presence-pin-btn');
        expect(pinBtn).toHaveAttribute('aria-label', 'Manter no topo');
        expect(pinBtn).toHaveAttribute('aria-pressed', 'false');

        const closeBtn = screen.getByTestId('presence-close-btn');
        expect(closeBtn).toHaveAttribute('aria-label', 'Fechar');
    });

    it('reflects always-on-top state via aria-pressed and accessible title/label', () => {
        const { rerender } = render(
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

        const pinBtn = screen.getByTestId('presence-pin-btn');
        expect(pinBtn).toHaveAttribute('aria-pressed', 'false');
        expect(pinBtn).toHaveAttribute('aria-label', 'Manter no topo');
        expect(pinBtn).not.toHaveClass('katherine-presence__btn--active');

        rerender(
            <KatherinePresence
                emotionState={null}
                isLoading={false}
                onReturnToCompanion={vi.fn()}
                onClose={vi.fn()}
                onMinimize={vi.fn()}
                onToggleAlwaysOnTop={vi.fn()}
                isAlwaysOnTop={true}
            />,
        );

        expect(pinBtn).toHaveAttribute('aria-pressed', 'true');
        expect(pinBtn).toHaveAttribute('aria-label', 'Desafixar do topo');
        expect(pinBtn).toHaveClass('katherine-presence__btn--active');
    });

    it('triggers the corresponding action callbacks on control click', () => {
        const onReturn = vi.fn();
        const onMinimize = vi.fn();
        const onTogglePin = vi.fn();
        const onClose = vi.fn();

        render(
            <KatherinePresence
                emotionState={null}
                isLoading={false}
                onReturnToCompanion={onReturn}
                onClose={onClose}
                onMinimize={onMinimize}
                onToggleAlwaysOnTop={onTogglePin}
                isAlwaysOnTop={false}
            />,
        );

        fireEvent.click(screen.getByTestId('presence-return-btn'));
        expect(onReturn).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByTestId('presence-minimize-btn'));
        expect(onMinimize).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByTestId('presence-pin-btn'));
        expect(onTogglePin).toHaveBeenCalledTimes(1);

        fireEvent.click(screen.getByTestId('presence-close-btn'));
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('stops mousedown propagation on buttons to isolate clicks from pywebview dragging', () => {
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

        for (const testId of [
            'presence-return-btn',
            'presence-minimize-btn',
            'presence-pin-btn',
            'presence-close-btn',
        ]) {
            const btn = screen.getByTestId(testId);
            const mousedownEvent = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
            const stopPropagationSpy = vi.spyOn(mousedownEvent, 'stopPropagation');
            const stopImmediatePropagationSpy = vi.spyOn(mousedownEvent, 'stopImmediatePropagation');

            btn.dispatchEvent(mousedownEvent);

            expect(stopPropagationSpy).toHaveBeenCalled();
            expect(stopImmediatePropagationSpy).toHaveBeenCalled();
        }
    });

    it('strictly isolates privacy: zero chat history, zero composer, zero memory in the DOM', () => {
        render(
            <KatherinePresence
                emotionState={makeEmotionState()}
                isLoading={false}
                onReturnToCompanion={vi.fn()}
                onClose={vi.fn()}
                onMinimize={vi.fn()}
                onToggleAlwaysOnTop={vi.fn()}
                isAlwaysOnTop={false}
            />,
        );

        expect(screen.queryByRole('textbox')).toBeNull();
        expect(screen.queryByTestId('companion-history')).toBeNull();
        expect(screen.queryByTestId('companion-utilities')).toBeNull();
        expect(screen.queryByTestId('companion-emotion-details')).toBeNull();
        expect(screen.queryByTestId('companion-privacy-details')).toBeNull();
        expect(screen.queryByText(/privacidade|memória|histórico|sua mensagem/i)).toBeNull();
    });

    it('announces loading preparation to assistive tech without continuous polling', () => {
        const { rerender } = render(
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

        expect(screen.queryByRole('status')).toBeNull();

        rerender(
            <KatherinePresence
                emotionState={null}
                isLoading={true}
                onReturnToCompanion={vi.fn()}
                onClose={vi.fn()}
                onMinimize={vi.fn()}
                onToggleAlwaysOnTop={vi.fn()}
                isAlwaysOnTop={false}
            />,
        );

        const status = screen.getByRole('status');
        expect(status).toHaveTextContent('Preparando resposta…');
    });

    it('declares reduced-motion rules, 160ms ease-out transitions, and transparent background in CSS', () => {
        const cssPath = join(
            __dirname,
            '../src/features/katherine-face/KatherinePresence.css',
        );
        const css = readFileSync(cssPath, 'utf8');

        expect(css).toMatch(/background:\s*transparent/);
        expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
        expect(css).toMatch(/transition-duration:\s*0ms\s*!important/);
        expect(css).toMatch(/transform:\s*none\s*!important/);
        expect(css).toMatch(/cubic-bezier\(0\.23,\s*1,\s*0\.32,\s*1\)/);
        expect(css).toMatch(/-webkit-app-region:\s*drag/);
        expect(css).toMatch(/-webkit-app-region:\s*no-drag/);
    });
});
