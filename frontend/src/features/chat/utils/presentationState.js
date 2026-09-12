import { validateEmotionState } from '../../../shared/utils/formatters.js';

const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

/**
 * Finite allowlist mapping canonical emotion names to calm, lowercase Portuguese adjectives.
 * Sensitive relationship states (jealousy, guilt) are neutralized to prevent manipulative
 * or coercive copy (coordination with safety policy and Issue #344).
 * Null-prototype object to prevent prototype property resolution (e.g. toString, valueOf).
 */
export const SAFE_EMOTION_DESCRIPTORS = Object.freeze(
    Object.assign(Object.create(null), {
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
    }),
);

export const UNAVAILABLE_STATUS_TEXT = 'estado indisponível';
export const NO_DOMINANT_TENDENCY_DESCRIPTOR = 'sem tendência dominante';

/**
 * Immutable unavailable presentation state used when emotion state DTO is absent,
 * malformed, or contains an invalid schema/unknown emotion.
 * Honest: does not invent emotions ('serena', 'neutra') and does not derive energy.
 */
export const UNAVAILABLE_PRESENTATION_STATE = Object.freeze({
    isAvailable: false,
    statusText: UNAVAILABLE_STATUS_TEXT,
    descriptors: Object.freeze([]),
    descriptorsText: null,
    energyLabel: null,
});

const DESCRIPTOR_SEPARATOR = ' · ';

/**
 * Deterministically maps arousal to a calm, qualitative energy tier.
 * Never exposes raw numbers, percentages, or clinical telemetry.
 * Returns null if arousal is not a valid coordinate (-1.0 to +1.0).
 *
 * @param {number} arousal Bipolar arousal coordinate (-1.0 to +1.0)
 * @returns {string|null} Qualitative energy label ('energia baixa', 'energia alta', or 'energia estável'), or null if invalid
 */
export const selectEnergyLabel = (arousal) => {
    if (typeof arousal !== 'number' || !Number.isFinite(arousal) || arousal < -1 || arousal > 1) {
        return null;
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
 * 2. If DTO is absent or invalid (null, undefined, malformed, invalid schema, rejected emotion):
 *    returns UNAVAILABLE_PRESENTATION_STATE (honest unavailability, zero invented emotions, zero derived energy).
 * 3. If DTO is valid with dominant_emotions: []:
 *    distinguishes from unavailable state by presenting NO_DOMINANT_TENDENCY_DESCRIPTOR ('sem tendência dominante')
 *    and qualitative energy from validated PAD arousal.
 * 4. If DTO is valid with dominant emotions:
 *    uses finite allowlist SAFE_EMOTION_DESCRIPTORS (max 2 descriptors) and qualitative energy.
 * 5. Never renders raw mood_label (excludes clinical and alarmist backend strings).
 * 6. Never renders percentages, progress bars, or raw PAD dimensions.
 * 7. Never uses timestamp for elapsed time or user absence heuristics.
 * 8. Zero side effects, zero I/O, zero network calls, zero timers.
 * 9. Returns immutable, frozen objects.
 *
 * @param {Object} [options={}]
 * @param {Object|null} [options.emotionState] Public emotion state payload
 * @returns {{ isAvailable: boolean, statusText: string|null, descriptors: readonly string[], descriptorsText: string|null, energyLabel: string|null }}
 */
export const selectKatherinePresentationState = (options = {}) => {
    try {
        if (!options || typeof options !== 'object' || Array.isArray(options)) {
            return UNAVAILABLE_PRESENTATION_STATE;
        }

        const rawEmotionState = options.emotionState;
        const validated = validateEmotionState(rawEmotionState);
        if (!validated) {
            return UNAVAILABLE_PRESENTATION_STATE;
        }

        const energyLabel = selectEnergyLabel(validated.pad.arousal);

        // DTO válido com dominant_emotions: [] (sem tendência dominante)
        if (validated.dominant_emotions.length === 0) {
            return Object.freeze({
                isAvailable: true,
                statusText: null,
                descriptors: Object.freeze([]),
                descriptorsText: NO_DOMINANT_TENDENCY_DESCRIPTOR,
                energyLabel,
            });
        }

        // Verify that all dominant emotions are mapped to safe descriptors
        for (const emotion of validated.dominant_emotions) {
            const name = emotion?.name;
            if (!name || !hasOwn(SAFE_EMOTION_DESCRIPTORS, name) || typeof SAFE_EMOTION_DESCRIPTORS[name] !== 'string') {
                return UNAVAILABLE_PRESENTATION_STATE;
            }
        }

        // Sort dominant emotions descending by intensity, preserving original order on ties
        const sortedEmotions = [...validated.dominant_emotions].sort(
            (a, b) => b.intensity - a.intensity
        );

        // Select up to 2 unique presentation descriptors from the highest-intensity emotions
        const descriptors = [];
        for (const emotion of sortedEmotions) {
            const descriptor = SAFE_EMOTION_DESCRIPTORS[emotion.name];
            if (!descriptors.includes(descriptor)) {
                descriptors.push(descriptor);
            }
            if (descriptors.length === 2) {
                break;
            }
        }

        if (descriptors.length === 0) {
            return UNAVAILABLE_PRESENTATION_STATE;
        }

        return Object.freeze({
            isAvailable: true,
            statusText: null,
            descriptors: Object.freeze(descriptors),
            descriptorsText: descriptors.join(DESCRIPTOR_SEPARATOR),
            energyLabel,
        });
    } catch {
        return UNAVAILABLE_PRESENTATION_STATE;
    }
};
