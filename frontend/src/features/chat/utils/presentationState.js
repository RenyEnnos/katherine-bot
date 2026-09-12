import { validateEmotionState } from '../../../shared/utils/formatters.js';

/**
 * Finite allowlist mapping canonical emotion names to calm, lowercase Portuguese adjectives.
 * Sensitive relationship states (jealousy, guilt) are neutralized to prevent manipulative
 * or coercive copy (coordination with safety policy and Issue #344).
 */
export const SAFE_EMOTION_DESCRIPTORS = Object.freeze({
    joy: 'alegre',
    trust: 'tranquila',
    anticipation: 'curiosa',
    gratitude: 'grata',
    tenderness: 'acolhedora',
    pride: 'satisfeita',
    surprise: 'surpresa',
    sadness: 'reflexiva',
    fear: 'atenta',
    anger: 'incomodada',
    disgust: 'reservada',
    jealousy: 'atenta',
    guilt: 'reflexiva',
});

/**
 * Immutable neutral fallback state used when emotion state is absent, malformed,
 * or contains zero valid dominant emotions.
 */
export const NEUTRAL_PRESENTATION_STATE = Object.freeze({
    descriptors: Object.freeze(['serena']),
    descriptorsText: 'serena',
    energyLabel: 'energia estável',
    isFallback: true,
});

const DESCRIPTOR_SEPARATOR = ' · ';

/**
 * Deterministically maps arousal to a calm, qualitative energy tier.
 * Never exposes raw numbers, percentages, or clinical telemetry.
 *
 * @param {number} arousal Bipolar arousal coordinate (-1.0 to +1.0)
 * @returns {string} Qualitative energy label ('energia baixa', 'energia alta', or 'energia estável')
 */
export const selectEnergyLabel = (arousal) => {
    if (typeof arousal !== 'number' || !Number.isFinite(arousal)) {
        return 'energia estável';
    }
    if (arousal < -0.2) {
        return 'energia baixa';
    }
    if (arousal > 0.2) {
        return 'energia alta';
    }
    return 'energia estável';
};

/**
 * Pure deterministic presentation mapper for Katherine companion mode.
 *
 * Requirements & Invariants:
 * 1. Consumes only validated public emotion state via validateEmotionState().
 * 2. Uses finite allowlist SAFE_EMOTION_DESCRIPTORS for descriptors.
 * 3. Never renders raw mood_label (excludes clinical and alarmist backend strings).
 * 4. Never renders percentages, progress bars, or PAD dimensions.
 * 5. Never uses timestamp for elapsed time or user absence heuristics.
 * 6. Zero side effects, zero I/O, zero network calls, zero timers.
 * 7. Returns immutable, frozen objects.
 *
 * @param {Object} [options={}]
 * @param {Object|null} [options.emotionState] Public emotion state payload
 * @returns {{ descriptors: readonly string[], descriptorsText: string, energyLabel: string, isFallback: boolean }}
 */
export const selectKatherinePresentationState = (options = {}) => {
    if (!options || typeof options !== 'object') {
        return NEUTRAL_PRESENTATION_STATE;
    }

    let rawEmotionState;
    try {
        rawEmotionState = options.emotionState;
    } catch {
        return NEUTRAL_PRESENTATION_STATE;
    }

    const validated = validateEmotionState(rawEmotionState);
    if (!validated || validated.dominant_emotions.length === 0) {
        return NEUTRAL_PRESENTATION_STATE;
    }

    // Sort dominant emotions descending by intensity, preserving original order on ties
    const sortedEmotions = [...validated.dominant_emotions].sort(
        (a, b) => b.intensity - a.intensity
    );

    // Select up to 2 unique presentation descriptors from the highest-intensity emotions
    const descriptors = [];
    for (const emotion of sortedEmotions) {
        const descriptor = SAFE_EMOTION_DESCRIPTORS[emotion.name];
        if (descriptor && !descriptors.includes(descriptor)) {
            descriptors.push(descriptor);
        }
        if (descriptors.length === 2) {
            break;
        }
    }

    if (descriptors.length === 0) {
        return NEUTRAL_PRESENTATION_STATE;
    }

    const energyLabel = selectEnergyLabel(validated.pad.arousal);

    return Object.freeze({
        descriptors: Object.freeze(descriptors),
        descriptorsText: descriptors.join(DESCRIPTOR_SEPARATOR),
        energyLabel,
        isFallback: false,
    });
};
