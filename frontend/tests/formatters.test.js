/* global process */
process.env.NODE_ENV = 'test';
import { test } from 'node:test';
import assert from 'node:assert';
import {
    bipolarToPercent,
    intensityToPercent,
    validateEmotionState,
    getEmotionLabel,
} from '../src/shared/utils/formatters.js';

// ─── bipolarToPercent ───────────────────────────────────────────────────────

test('bipolarToPercent: -1 → 0', () => {
    assert.strictEqual(bipolarToPercent(-1), 0);
});

test('bipolarToPercent: 0 → 50', () => {
    assert.strictEqual(bipolarToPercent(0), 50);
});

test('bipolarToPercent: 1 → 100', () => {
    assert.strictEqual(bipolarToPercent(1), 100);
});

test('bipolarToPercent: 0.5 → 75', () => {
    assert.strictEqual(bipolarToPercent(0.5), 75);
});

test('bipolarToPercent: -0.5 → 25', () => {
    assert.strictEqual(bipolarToPercent(-0.5), 25);
});

test('bipolarToPercent: clamp below -1', () => {
    assert.strictEqual(bipolarToPercent(-2), 0);
});

test('bipolarToPercent: clamp above 1', () => {
    assert.strictEqual(bipolarToPercent(2), 100);
});

test('bipolarToPercent: NaN returns 50', () => {
    assert.strictEqual(bipolarToPercent(NaN), 50);
});

test('bipolarToPercent: Infinity returns 50', () => {
    assert.strictEqual(bipolarToPercent(Infinity), 50);
});

test('bipolarToPercent: -Infinity returns 50', () => {
    assert.strictEqual(bipolarToPercent(-Infinity), 50);
});

test('bipolarToPercent: string returns 50', () => {
    assert.strictEqual(bipolarToPercent('0.5'), 50);
});

test('bipolarToPercent: null returns 50', () => {
    assert.strictEqual(bipolarToPercent(null), 50);
});

test('bipolarToPercent: undefined returns 50', () => {
    assert.strictEqual(bipolarToPercent(undefined), 50);
});

// ─── intensityToPercent ─────────────────────────────────────────────────────

test('intensityToPercent: 0 → 0', () => {
    assert.strictEqual(intensityToPercent(0), 0);
});

test('intensityToPercent: 0.5 → 50', () => {
    assert.strictEqual(intensityToPercent(0.5), 50);
});

test('intensityToPercent: 1 → 100', () => {
    assert.strictEqual(intensityToPercent(1), 100);
});

test('intensityToPercent: 0.25 → 25', () => {
    assert.strictEqual(intensityToPercent(0.25), 25);
});

test('intensityToPercent: clamp below 0', () => {
    assert.strictEqual(intensityToPercent(-0.5), 0);
});

test('intensityToPercent: clamp above 1', () => {
    assert.strictEqual(intensityToPercent(1.5), 100);
});

test('intensityToPercent: NaN returns 0', () => {
    assert.strictEqual(intensityToPercent(NaN), 0);
});

test('intensityToPercent: Infinity returns 0', () => {
    assert.strictEqual(intensityToPercent(Infinity), 0);
});

test('intensityToPercent: null returns 0', () => {
    assert.strictEqual(intensityToPercent(null), 0);
});

// ─── validateEmotionState ───────────────────────────────────────────────────

test('validateEmotionState: valid payload returns validated', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'ALEGRE',
        pad: { pleasure: 0.5, arousal: 0.3, dominance: -0.2 },
        dominant_emotions: [{ name: 'joy', intensity: 0.8 }],
        timestamp: 1700000000,
    };
    const result = validateEmotionState(payload);
    assert(result !== null);
    assert.strictEqual(result.mood_label, 'ALEGRE');
    assert.strictEqual(result.pad.pleasure, 0.5);
    assert.strictEqual(result.dominant_emotions.length, 1);
});

test('validateEmotionState: null payload returns null', () => {
    assert.strictEqual(validateEmotionState(null), null);
});

test('validateEmotionState: undefined returns null', () => {
    assert.strictEqual(validateEmotionState(undefined), null);
});

test('validateEmotionState: array returns null', () => {
    assert.strictEqual(validateEmotionState([]), null);
});

test('validateEmotionState: schema_version absent returns null', () => {
    const payload = {
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: schema_version != 1 returns null', () => {
    const payload = {
        schema_version: 2,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: pad absent returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: pad with NaN returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: NaN, arousal: 0, dominance: 0 },
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: pad with Infinity returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: Infinity, dominance: 0 },
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotions absent returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotions not array returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: 'invalid',
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: empty dominant_emotions works', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [],
        timestamp: 1700000000,
    };
    const result = validateEmotionState(payload);
    assert(result !== null);
    assert.deepStrictEqual(result.dominant_emotions, []);
});

// ─── validateEmotionState: item-level dominant_emotions validation ─────────

test('validateEmotionState: dominant_emotion with NaN intensity returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [{ name: 'joy', intensity: NaN }],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotion with missing name returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [{ intensity: 0.5 }],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotion with empty name returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [{ name: '', intensity: 0.5 }],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotion with non-finite intensity returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: [{ name: 'joy', intensity: Infinity }],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

test('validateEmotionState: dominant_emotion item not an object returns null', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'NEUTRA',
        pad: { pleasure: 0, arousal: 0, dominance: 0 },
        dominant_emotions: ['invalid'],
        timestamp: 1700000000,
    };
    assert.strictEqual(validateEmotionState(payload), null);
});

// ─── getEmotionLabel ────────────────────────────────────────────────────────

test('getEmotionLabel: known emotion returns label', () => {
    assert.strictEqual(getEmotionLabel('joy'), 'Alegria');
});

test('getEmotionLabel: another known emotion', () => {
    assert.strictEqual(getEmotionLabel('anger'), 'Raiva');
});

test('getEmotionLabel: unknown emotion falls back to name', () => {
    assert.strictEqual(getEmotionLabel('unknown_emotion'), 'unknown_emotion');
});

test('getEmotionLabel: empty string', () => {
    assert.strictEqual(getEmotionLabel(''), '');
});
