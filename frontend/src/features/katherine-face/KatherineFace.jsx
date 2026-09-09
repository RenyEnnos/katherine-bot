import React from 'react';
import Face from '../../vendor/bfce/Face.jsx';
import { selectKatherineFaceState } from './faceState.js';
import './KatherineFace.css';

/**
 * Decorative presentation of the validated public emotion state.
 *
 * The wrapper deliberately accepts only the two state values needed by the
 * mapper and an optional styling class. Chat content, identity, transport,
 * memory, relationship, prompts, and response data never reach bfce.
 */
const KatherineFace = ({ emotionState, isLoading, className = '' }) => {
    const { expression } = selectKatherineFaceState({ emotionState, isLoading });

    return (
        <div
            className={`katherine-face ${className}`.trim()}
            data-testid="katherine-face"
            data-activity={isLoading === true ? 'busy' : 'idle'}
            aria-hidden="true"
        >
            <Face
                expression={expression}
                size="100%"
                mouth={true}
                pupils={false}
                track={false}
                blink={false}
                idle={false}
                className="katherine-face__vendor"
            />
            <svg
                className="katherine-face__activity"
                data-testid="katherine-activity-arc"
                viewBox="-58 -58 116 116"
                aria-hidden="true"
                focusable="false"
            >
                <path d="M 13.976 -52.160 A 54 54 0 0 1 48.941 -22.821" />
            </svg>
        </div>
    );
};

export default KatherineFace;
