/* global process */
process.env.NODE_ENV = 'test';
import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = resolve(__dirname, '..');
const EMOTION_PANEL_PATH = resolve(PROJECT_ROOT, 'src/features/chat/components/EmotionPanel.jsx');
const USE_CHAT_PATH = resolve(PROJECT_ROOT, 'src/features/chat/hooks/useChat.js');

// Verify the files exist before reading
if (!existsSync(EMOTION_PANEL_PATH)) {
    throw new Error(`EmotionPanel file not found at: ${EMOTION_PANEL_PATH}`);
}
if (!existsSync(USE_CHAT_PATH)) {
    throw new Error(`useChat file not found at: ${USE_CHAT_PATH}`);
}

const emotionPanelSource = readFileSync(EMOTION_PANEL_PATH, 'utf-8');
const useChatSource = readFileSync(USE_CHAT_PATH, 'utf-8');

// ─── Verify EmotionPanel doesn't reference forbidden fields ─────────────────

test('EmotionPanel does not reference acting_instruction', () => {
    const hasActingInstruction = emotionPanelSource.includes('acting_instruction');
    assert.strictEqual(hasActingInstruction, false,
        'EmotionPanel should not reference acting_instruction');
});

test('EmotionPanel does not reference coping_mode', () => {
    const hasCopingMode = emotionPanelSource.includes('coping_mode');
    assert.strictEqual(hasCopingMode, false,
        'EmotionPanel should not reference coping_mode');
});

test('EmotionPanel does not reference libido', () => {
    const hasLibido = emotionPanelSource.includes('libido');
    assert.strictEqual(hasLibido, false,
        'EmotionPanel should not reference libido');
});

test('EmotionPanel does not reference aggression', () => {
    const hasAggression = emotionPanelSource.includes('aggression');
    assert.strictEqual(hasAggression, false,
        'EmotionPanel should not reference aggression');
});

test('EmotionPanel uses dominant_emotions array instead of flat fields', () => {
    assert.ok(emotionPanelSource.includes('dominant_emotions'),
        'EmotionPanel should reference dominant_emotions');
    // The panel should read from dominant_emotions array, not flat fields like joy, sadness, etc.
    const forbiddenTopLevelEmotions = [
        'emotionState.joy', 'emotionState.sadness', 'emotionState.anger',
        'emotionState.fear', 'emotionState.disgust',
    ];
    for (const field of forbiddenTopLevelEmotions) {
        assert.strictEqual(emotionPanelSource.includes(field), false,
            `EmotionPanel should not reference '${field}' directly`);
    }
});

test('EmotionPanel reads PAD from nested pad object', () => {
    assert.ok(emotionPanelSource.includes('pad[') || emotionPanelSource.includes('.pad.'),
        'EmotionPanel should read PAD values from nested pad object');
});

test('EmotionPanel uses bipolarToPercent helper', () => {
    assert.ok(emotionPanelSource.includes('bipolarToPercent'),
        'EmotionPanel should use bipolarToPercent for PAD values');
});

test('EmotionPanel uses intensityToPercent helper', () => {
    assert.ok(emotionPanelSource.includes('intensityToPercent'),
        'EmotionPanel should use intensityToPercent for emotion intensities');
});

// ─── Behavioral: formatter functions (ARIA compliance) ──────────────────────

test('bipolarToPercent output is always between 0 and 100 (ARIA compliance)', () => {
    return import('../src/shared/utils/formatters.js').then(({ bipolarToPercent }) => {
        const testValues = [-2, -1, -0.5, 0, 0.5, 1, 2, NaN, Infinity, -Infinity, null, undefined, 'string'];
        for (const val of testValues) {
            const result = bipolarToPercent(val);
            assert.ok(result >= 0 && result <= 100,
                `bipolarToPercent(${val}) = ${result} should be in [0, 100]`);
        }
    });
});

test('intensityToPercent output is always between 0 and 100 (ARIA compliance)', () => {
    return import('../src/shared/utils/formatters.js').then(({ intensityToPercent }) => {
        const testValues = [-1, -0.5, 0, 0.5, 1, 1.5, NaN, Infinity, -Infinity, null, undefined, 'string'];
        for (const val of testValues) {
            const result = intensityToPercent(val);
            assert.ok(result >= 0 && result <= 100,
                `intensityToPercent(${val}) = ${result} should be in [0, 100]`);
        }
    });
});

test('EmotionPanel has role="progressbar" ARIA attributes', () => {
    assert.ok(emotionPanelSource.includes('role="progressbar"'),
        'EmotionPanel should include role="progressbar"');
    assert.ok(emotionPanelSource.includes('aria-valuenow'),
        'EmotionPanel should include aria-valuenow');
    assert.ok(emotionPanelSource.includes('aria-valuemin'),
        'EmotionPanel should include aria-valuemin');
    assert.ok(emotionPanelSource.includes('aria-valuemax="100"'),
        'EmotionPanel should include aria-valuemax="100"');
});

// ─── Behavioral: validateEmotionState integration tests ─────────────────────

test('validateEmotionState is called on every response (source inspection)', () => {
    assert.ok(useChatSource.includes('validateEmotionState'),
        'useChat should call validateEmotionState');
});

test('useChat always sets emotionState (even to null) on response', () => {
    // Check that emotion_state is ALWAYS validated (not conditionally)
    const guardedByIf = useChatSource.includes('if (data.emotion_state) {');
    assert.strictEqual(guardedByIf, false,
        'useChat should not guard emotion_state validation with an if check - always validate');
    assert.ok(useChatSource.includes('setEmotionState(validated)'),
        'useChat should always set emotionState (even to null)');
});

// ─── Behavioral: validateEmotionState pure function (extracted hook logic) ──

test('validateEmotionState rejects invalid payload — pure function test', () => {
    return import('../src/shared/utils/formatters.js').then(({ validateEmotionState }) => {
        // Known invalid cases
        assert.strictEqual(validateEmotionState(null), null);
        assert.strictEqual(validateEmotionState(undefined), null);
        assert.strictEqual(validateEmotionState([]), null);
        assert.strictEqual(validateEmotionState({}), null);

        // Valid payload
        const valid = {
            schema_version: 1,
            mood_label: 'NEUTRA',
            pad: { pleasure: 0, arousal: 0, dominance: 0 },
            dominant_emotions: [],
            timestamp: 1700000000,
        };
        assert.notStrictEqual(validateEmotionState(valid), null);

        // Invalid: missing emotion_state (simulating missing backend data)
        assert.strictEqual(validateEmotionState(undefined), null,
            'undefined payload should return null — panel cleared');
    });
});

test('validateEmotionState with more than 3 emotions returns null', () => {
    return import('../src/shared/utils/formatters.js').then(({ validateEmotionState }) => {
        const payload = {
            schema_version: 1,
            mood_label: 'NEUTRA',
            pad: { pleasure: 0, arousal: 0, dominance: 0 },
            dominant_emotions: [
                { name: 'joy', intensity: 0.8 },
                { name: 'anger', intensity: 0.7 },
                { name: 'fear', intensity: 0.6 },
                { name: 'sadness', intensity: 0.5 },
            ],
            timestamp: 1700000000,
        };
        assert.strictEqual(validateEmotionState(payload), null,
            '>3 emotions should reject entire payload');
    });
});

test('validateEmotionState with unknown emotion name returns null', () => {
    return import('../src/shared/utils/formatters.js').then(({ validateEmotionState }) => {
        const payload = {
            schema_version: 1,
            mood_label: 'NEUTRA',
            pad: { pleasure: 0, arousal: 0, dominance: 0 },
            dominant_emotions: [{ name: 'invalid_emotion', intensity: 0.5 }],
            timestamp: 1700000000,
        };
        assert.strictEqual(validateEmotionState(payload), null,
            'unknown emotion name should reject entire payload');
    });
});

test('EmotionPanel getEmotionLabel exposes canonical name for known emotion', () => {
    return import('../src/shared/utils/formatters.js').then(({ getEmotionLabel, EMOTION_LABELS }) => {
        // All defined emotions should have a display label
        const knownEmotions = Object.keys(EMOTION_LABELS);
        assert.ok(knownEmotions.length > 0, 'EMOTION_LABELS should have entries');
        for (const name of knownEmotions) {
            const label = getEmotionLabel(name);
            assert.notStrictEqual(label, name,
                `Known emotion '${name}' should have a translated label`);
            assert.ok(label.length > 0, `Label for '${name}' should not be empty`);
        }
    });
});
