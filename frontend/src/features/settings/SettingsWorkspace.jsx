/**
 * Katherine settings workspace (#347).
 *
 * A dedicated surface for "how Katherine should work", separate from
 * the companion ("how Katherine is right now") and from the #344 state
 * sidebar. The workspace is intentionally small: it only renders
 * categories whose capabilities exist as real, tested contracts in
 * `main` today.
 *
 * Honesty rules (mirroring #344/#342):
 * - Every visible control is backed by a real bridge operation that
 *   already exists (`desktopBridge.js` allowlist); no mock state, no
 *   fake save, no placeholder for future integrations.
 * - The single exposed capability is "Sempre no topo" (always-on-top):
 *   read via `getWindowState()` on mount and mutated via
 *   `setAlwaysOnTop()`. Both go through the validated pywebview bridge.
 * - The control is session state only. The window controller keeps the
 *   flag in memory for the lifetime of the window; nothing in the
 *   bridge contract persists it across restarts, so the copy must not
 *   promise persistence.
 * - Success is never optimistic: the UI only reflects the `on_top`
 *   value confirmed by the bridge payload. A failed mutation keeps the
 *   previous coherent state and surfaces a sanitized error message.
 * - No polling, no timers, no network. The single mount-time
 *   `getWindowState()` read mirrors the bounded one-shot sync already
 *   used by `AppDesktop`.
 *
 * Conversation preservation (#347 critical requirement):
 * this component is rendered by `AppDesktop` *below* `ChatWindow`, so
 * the single `useChat()` call (and its history/draft state) is never
 * remounted while the user opens, navigates, or closes settings.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, Pin, PinOff } from 'lucide-react';
import { getWindowState } from '../../lib/desktopBridge';
import './SettingsWorkspace.css';
const AOT_PENDING_MESSAGE = 'Aplicando…';

/**
 * Map a sanitized bridge failure payload to short, user-facing copy.
 * No raw codes, no internals, no retry loops — mirrors the honest
 * failure handling of the presence pin button.
 */
function alwaysOnTopFailureMessage(result) {
    if (result?.code === 'bridge_unavailable') {
        return 'Controle da janela indisponível neste ambiente.';
    }
    return 'Não foi possível alterar agora. A configuração permanece como estava.';
}

export default function SettingsWorkspace({ onReturn, isAlwaysOnTop = false, onToggleAlwaysOnTop, onSyncAlwaysOnTop }) {
    const headerRef = useRef(null);
    const [aotError, setAotError] = useState(null);
    const [aotPending, setAotPending] = useState(false);
    const pendingRef = useRef(false);

    // Bounded, one-shot sync on mount: the authoritative initial state
    // comes from the real bridge contract, never from an assumption.
    // No polling: this runs once per mount and aborts on unmount.
    useEffect(() => {
        let active = true;
        getWindowState().then((state) => {
            if (active && state?.ok && typeof state.on_top === 'boolean') {
                onSyncAlwaysOnTop?.(state.on_top);
            }
        });
        return () => {
            active = false;
        };
        // onSyncAlwaysOnTop is a stable callback from AppDesktop.
    }, []);

    // Give the back button focus on open so keyboard users land in a
    // predictable place (and the screen reader announces the surface).
    useEffect(() => {
        headerRef.current?.focus();
    }, []);

    // Escape closes the workspace and returns to the companion — same
    // gesture as the visible back button, no extra machinery.
    useEffect(() => {
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                onReturn();
            }
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [onReturn]);

    const handleToggle = useCallback(async () => {
        if (pendingRef.current) return;
        pendingRef.current = true;
        setAotPending(true);
        setAotError(null);
        try {
            // `onToggleAlwaysOnTop` (AppDesktop) performs the real bridge
            // call and only commits the confirmed `on_top` payload on
            // success. It returns the sanitized bridge result; a failure
            // keeps the previous coherent state and surfaces its message.
            const result = await onToggleAlwaysOnTop?.();
            if (result && result.applied !== true) {
                setAotError(alwaysOnTopFailureMessage(result));
            }
        } finally {
            pendingRef.current = false;
            setAotPending(false);
        }
    }, [onToggleAlwaysOnTop]);

    return (
        <section
            className="settings-workspace"
            aria-labelledby="settings-workspace-heading"
            data-testid="settings-workspace"
        >
            <div className="settings-workspace__frame">
                <header className="settings-workspace__header">
                    <button
                        ref={headerRef}
                        type="button"
                        className="settings-workspace__back"
                        onClick={onReturn}
                        aria-label="Voltar para a Katherine"
                        data-testid="settings-back-btn"
                    >
                        <ArrowLeft size={18} aria-hidden="true" />
                        <span>Katherine</span>
                    </button>
                    <h1 id="settings-workspace-heading" className="settings-workspace__title">
                        Configurações
                    </h1>
                </header>

                <div className="settings-workspace__content">
                    <section
                        className="settings-workspace__section"
                        aria-labelledby="settings-window-heading"
                        data-testid="settings-section-window"
                    >
                        <h2 id="settings-window-heading" className="settings-workspace__section-title">
                            Janela
                        </h2>

                        <div className="settings-workspace__control">
                            <div className="settings-workspace__control-text">
                                <label
                                    htmlFor="settings-always-on-top"
                                    className="settings-workspace__control-label"
                                >
                                    Sempre no topo
                                </label>
                                <p className="settings-workspace__control-hint">
                                    Mantém a janela da Katherine acima das outras nesta sessão.
                                </p>
                                <p className="settings-workspace__control-scope">
                                    Vale enquanto o aplicativo estiver aberto.
                                </p>
                                {aotError && (
                                    <p
                                        className="settings-workspace__control-error"
                                        data-testid="settings-always-on-top-error"
                                        role="alert"
                                    >
                                        {aotError}
                                    </p>
                                )}
                            </div>

                            <button
                                id="settings-always-on-top"
                                type="button"
                                role="switch"
                                aria-checked={isAlwaysOnTop}
                                disabled={aotPending}
                                onClick={handleToggle}
                                className={`settings-workspace__switch${
                                    isAlwaysOnTop ? ' settings-workspace__switch--on' : ''
                                }`}
                                data-testid="settings-always-on-top-switch"
                            >
                                <span className="settings-workspace__switch-knob" aria-hidden="true" />
                                <span className="settings-workspace__switch-icon" aria-hidden="true">
                                    {isAlwaysOnTop ? (
                                        <PinOff size={12} aria-hidden="true" />
                                    ) : (
                                        <Pin size={12} aria-hidden="true" />
                                    )}
                                </span>
                                <span className="settings-workspace__switch-text">
                                    {aotPending ? AOT_PENDING_MESSAGE : (isAlwaysOnTop ? 'Ativado' : 'Desativado')}
                                </span>
                            </button>
                        </div>
                    </section>
                </div>
            </div>
        </section>
    );
}
