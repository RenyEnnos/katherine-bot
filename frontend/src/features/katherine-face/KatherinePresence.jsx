import React from 'react';
import { ArrowUpRight, Minus, Pin, PinOff, X } from 'lucide-react';
import KatherineFace from './KatherineFace.jsx';
import './KatherinePresence.css';

/**
 * Floating presence surface for Katherine desktop (#342).
 *
 * Minimal presence surface: face + ephemeral controls.
 * - Entire region is transparent.
 * - KatherineFace has pointer-events: none and is wrapped in .pywebview-drag-region,
 *   allowing grabbing the face to directly move the window.
 * - Ephemeral controls overlay discloses on hover or focus-within.
 * - Ephemeral control buttons stop mousedown propagation and specify
 *   -webkit-app-region: no-drag so clicks never trigger window moves.
 * - Zero chat history, zero composer, zero sidebar, zero memory rendered.
 */
export default function KatherinePresence({
    emotionState,
    isLoading,
    onReturnToCompanion,
    onClose,
    onToggleAlwaysOnTop,
    onMinimize,
    isAlwaysOnTop = false,
}) {
    const handleControlMouseDown = (e) => {
        e.stopPropagation();
        if (typeof e.nativeEvent?.stopImmediatePropagation === 'function') {
            e.nativeEvent.stopImmediatePropagation();
        }
    };

    return (
        <div
            className="katherine-presence"
            data-testid="katherine-presence-surface"
            role="region"
            aria-label="Presença flutuante da Katherine"
        >
            {/* Dedicated drag surface under and surrounding the face */}
            <div
                className="katherine-presence__drag-handle pywebview-drag-region"
                data-testid="katherine-presence-drag-handle"
                title="Arraste para mover Katherine"
            >
                <KatherineFace
                    emotionState={emotionState}
                    isLoading={isLoading}
                    className="katherine-face--presence"
                />
            </div>

            {/* Ephemeral Controls: revealed on hover or focus-within */}
            <div
                className="katherine-presence__controls"
                data-testid="katherine-presence-controls"
                role="toolbar"
                aria-label="Controles da presença"
            >
                <button
                    type="button"
                    className="katherine-presence__btn"
                    onClick={onReturnToCompanion}
                    onMouseDown={handleControlMouseDown}
                    title="Voltar ao companion (Expandir)"
                    aria-label="Voltar ao companion"
                    data-testid="presence-return-btn"
                >
                    <ArrowUpRight size={16} aria-hidden="true" />
                </button>

                <button
                    type="button"
                    className={`katherine-presence__btn ${isAlwaysOnTop ? 'katherine-presence__btn--active' : ''}`}
                    onClick={onToggleAlwaysOnTop}
                    onMouseDown={handleControlMouseDown}
                    title={isAlwaysOnTop ? 'Desafixar do topo' : 'Manter no topo'}
                    aria-label={isAlwaysOnTop ? 'Desafixar do topo' : 'Manter no topo'}
                    aria-pressed={isAlwaysOnTop}
                    data-testid="presence-pin-btn"
                >
                    {isAlwaysOnTop ? (
                        <PinOff size={16} aria-hidden="true" />
                    ) : (
                        <Pin size={16} aria-hidden="true" />
                    )}
                </button>

                <button
                    type="button"
                    className="katherine-presence__btn"
                    onClick={onMinimize}
                    onMouseDown={handleControlMouseDown}
                    title="Minimizar"
                    aria-label="Minimizar"
                    data-testid="presence-minimize-btn"
                >
                    <Minus size={16} aria-hidden="true" />
                </button>

                <button
                    type="button"
                    className="katherine-presence__btn katherine-presence__btn--danger"
                    onClick={onClose}
                    onMouseDown={handleControlMouseDown}
                    title="Fechar"
                    aria-label="Fechar"
                    data-testid="presence-close-btn"
                >
                    <X size={16} aria-hidden="true" />
                </button>
            </div>

            {/* Accessible screen-reader announcement for loading without continuous polling */}
            {isLoading && (
                <div role="status" className="sr-only">
                    Preparando resposta…
                </div>
            )}
        </div>
    );
}
