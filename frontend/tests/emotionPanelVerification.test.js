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

// ─── ARIA compliance ────────────────────────────────────────────────────────

test('bipolarToPercent output is always between 0 and 100 (ARIA compliance)', () => {
    // Dynamic import for ESM compatibility with Node 18
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

// ─── useChat invalidation policy (Requirement 37) ──────────────────────────

test('useChat calls validateEmotionState on every response', () => {
    assert.ok(useChatSource.includes('validateEmotionState'),
        'useChat should call validateEmotionState');
});

test('useChat sets null on invalid or missing emotion_state', () => {
    // Check that emotion_state is ALWAYS validated (not conditionally)
    // The validation result (null or validated) is always set
    const hasAlwaysValidation = useChatSource.includes('const validated = validateEmotionState(data.emotion_state);\n            setEmotionState(validated);');
    // Alternative: check that validateEmotionState and setEmotionState are used
    // Without being guarded by an `if (data.emotion_state)` check
    const guardedByIf = useChatSource.includes('if (data.emotion_state) {\n                const validated =');
    assert.strictEqual(guardedByIf, false,
        'useChat should not guard emotion_state validation with an if check - always validate');
    assert.ok(useChatSource.includes('setEmotionState(validated)'),
        'useChat should always set emotionState (even to null)');
});
