import React from 'react';
import { selectKatherinePresentationState } from '../utils/presentationState.js';
import './KatherineStateSidebar.css';

/**
 * Honest Katherine state presentation sidebar (#344).
 *
 * Displays a calm, qualitative explanation of Katherine's current validated state
 * without deceptive psychological telemetry, percentage dials, or progress bars.
 * Zero network requests, zero timers, zero side effects.
 */
export default function KatherineStateSidebar({ emotionState }) {
    const presentation = selectKatherinePresentationState({ emotionState });

    return (
        <aside
            className="katherine-state-sidebar"
            aria-labelledby="katherine-state-heading"
            data-testid="katherine-state-sidebar"
        >
            <h2 id="katherine-state-heading" className="katherine-state-sidebar__title">
                Estado
            </h2>
            <div className="katherine-state-sidebar__body">
                <p className="katherine-state-sidebar__descriptors">
                    {presentation.descriptorsText}
                </p>
                <p className="katherine-state-sidebar__energy">
                    {presentation.energyLabel}
                </p>
            </div>
        </aside>
    );
}
