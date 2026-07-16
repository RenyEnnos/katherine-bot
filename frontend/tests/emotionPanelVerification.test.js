/* global process */
process.env.NODE_ENV = 'test';
import { test } from 'node:test';
import assert from 'node:assert';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import EmotionPanel from '../src/features/chat/components/EmotionPanel.jsx';

// ─── Helpers ────────────────────────────────────────────────────────────────

const NEUTRAL_PAYLOAD = {
    schema_version: 1,
    mood_label: 'NEUTRA',
    pad: { pleasure: 0, arousal: 0, dominance: 0 },
    dominant_emotions: [],
    timestamp: 1700000000,
};

const renderPanel = (props = {}) => {
    return renderToStaticMarkup(React.createElement(EmotionPanel, props));
};

// ─── 1. Null payload ───────────────────────────────────────────────────────

test('null emotionState does not render the panel', () => {
    const html = renderPanel({ emotionState: null });
    assert.strictEqual(html, '');
});

test('undefined emotionState does not render the panel', () => {
    const html = renderPanel({ emotionState: undefined });
    assert.strictEqual(html, '');
});

test('emotionState without pad does not render the panel', () => {
    const html = renderPanel({ emotionState: { ...NEUTRAL_PAYLOAD, pad: null } });
    assert.strictEqual(html, '');
});

// ─── 2. Empty dominant_emotions ─────────────────────────────────────────────

test('empty dominant_emotions renders PAD without emotion badges', () => {
    const html = renderPanel({ emotionState: NEUTRAL_PAYLOAD });
    // Should contain progress bars
    assert.ok(html.includes('role="progressbar"'), 'Should render progress bars');
    // Should NOT contain emotion badge spans (text-gray-200 is unique to badges)
    assert.ok(!html.includes('text-gray-200'), 'Should not render emotion badges');
    // Should not contain percent values from badges (only from PAD labels)
    assert.ok(!html.includes('Alegria'), 'Should not render emotion labels');
});

// ─── 3. PAD -1, 0, 1 produces 0, 50, 100 percent ───────────────────────────

test('PAD -1 produces 0% for each dimension', () => {
    const html = renderPanel({
        emotionState: {
            ...NEUTRAL_PAYLOAD,
            pad: { pleasure: -1, arousal: -1, dominance: -1 },
        },
    });
    // aria-valuenow should be 0 for all PAD bars
    const nows = [...html.matchAll(/aria-valuenow="(\d+)"/g)].map(m => parseInt(m[1], 10));
    assert.ok(nows.every(v => v === 0), `All aria-valuenow should be 0, got ${nows}`);
});

test('PAD 0 produces 50% for each dimension', () => {
    const html = renderPanel({
        emotionState: {
            ...NEUTRAL_PAYLOAD,
            pad: { pleasure: 0, arousal: 0, dominance: 0 },
        },
    });
    const nows = [...html.matchAll(/aria-valuenow="(\d+)"/g)].map(m => parseInt(m[1], 10));
    assert.ok(nows.every(v => v === 50), `All aria-valuenow should be 50, got ${nows}`);
});

test('PAD 1 produces 100% for each dimension', () => {
    const html = renderPanel({
        emotionState: {
            ...NEUTRAL_PAYLOAD,
            pad: { pleasure: 1, arousal: 1, dominance: 1 },
        },
    });
    const nows = [...html.matchAll(/aria-valuenow="(\d+)"/g)].map(m => parseInt(m[1], 10));
    assert.ok(nows.every(v => v === 100), `All aria-valuenow should be 100, got ${nows}`);
});

// ─── 4. ARIA progress bar attributes ────────────────────────────────────────

test('progress bars have role="progressbar"', () => {
    const html = renderPanel({ emotionState: NEUTRAL_PAYLOAD });
    const bars = html.match(/role="progressbar"/g);
    assert.strictEqual(bars && bars.length, 3, 'Should have 3 progress bars');
});

test('progress bars have aria-valuemin="0"', () => {
    const html = renderPanel({ emotionState: NEUTRAL_PAYLOAD });
    const mins = html.match(/aria-valuemin="0"/g);
    assert.ok(mins && mins.length === 3, 'All 3 bars should have aria-valuemin="0"');
});

test('progress bars have aria-valuemax="100"', () => {
    const html = renderPanel({ emotionState: NEUTRAL_PAYLOAD });
    assert.ok(html.includes('aria-valuemax="100"'), 'Should have aria-valuemax="100"');
});

test('progress bars have aria-valuenow with correct value', () => {
    const html = renderPanel({
        emotionState: {
            ...NEUTRAL_PAYLOAD,
            pad: { pleasure: 0.5, arousal: -0.3, dominance: 0.8 },
        },
    });
    // pleasure 0.5 -> 75, arousal -0.3 -> 35, dominance 0.8 -> 90
    assert.ok(html.includes('aria-valuenow="75"'), 'pleasure=0.5 should show 75');
    assert.ok(html.includes('aria-valuenow="35"'), 'arousal=-0.3 should show 35');
    assert.ok(html.includes('aria-valuenow="90"'), 'dominance=0.8 should show 90');
});

test('progress bars are associated to a labelledby ID', () => {
    const html = renderPanel({ emotionState: NEUTRAL_PAYLOAD });
    // Each bar has aria-labelledby pointing to an ID
    assert.ok(html.includes('aria-labelledby="emotion-label-'), 'Should have aria-labelledby');
    // All IDs are present and referenced
    const labels = ['Prazer', 'Energia', 'Dominância'];
    for (const label of labels) {
        assert.ok(html.includes(label), `Should contain label "${label}"`);
    }
});

// ─── 5. Width clamping ─────────────────────────────────────────────────────

test('width percent is never below 0% or above 100%', () => {
    const extremePayload = {
        ...NEUTRAL_PAYLOAD,
        pad: { pleasure: -10, arousal: 10, dominance: -999 },
    };
    const html = renderPanel({ emotionState: extremePayload });
    const widths = [...html.matchAll(/style="width:\s*([\d.]+)%"/g)].map(m => parseFloat(m[1]));
    for (const w of widths) {
        assert.ok(w >= 0 && w <= 100, `Width ${w}% should be in [0, 100]`);
    }
});

// ─── 6. Emotions in received order ─────────────────────────────────────────

test('emotions appear in received order', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0.8 },
            { name: 'sadness', intensity: 0.5 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    const joyIndex = html.indexOf('Alegria');
    const sadnessIndex = html.indexOf('Tristeza');
    assert.ok(joyIndex >= 0, 'Should contain Alegria');
    assert.ok(sadnessIndex >= 0, 'Should contain Tristeza');
    assert.ok(joyIndex < sadnessIndex, 'Alegria should appear before Tristeza');
});

// ─── 7. At most 3 emotions rendered ────────────────────────────────────────

test('at most 3 emotions are rendered even if payload has 5', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0.9 },
            { name: 'anger', intensity: 0.8 },
            { name: 'sadness', intensity: 0.7 },
            { name: 'fear', intensity: 0.6 },
            { name: 'disgust', intensity: 0.5 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    // Count occurrences of known labels
    const labelCount = (html.match(/(Alegria|Raiva|Tristeza|Medo|Nojo)/g) || []).length;
    assert.strictEqual(labelCount, 3, 'Should render exactly 3 emotions');
});

test('exactly 3 emotions renders all 3', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0.9 },
            { name: 'anger', intensity: 0.8 },
            { name: 'sadness', intensity: 0.7 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    const labelCount = (html.match(/(Alegria|Raiva|Tristeza)/g) || []).length;
    assert.strictEqual(labelCount, 3, 'Should render all 3 emotions');
});

// ─── 8. Unknown emotion name not in HTML ───────────────────────────────────

test('unknown emotion name does not appear as raw text', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0.8 },
            { name: 'non_existent_emotion', intensity: 0.7 },
            { name: 'anger', intensity: 0.6 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    // Joy and Anger should be rendered
    assert.ok(html.includes('Alegria'), 'Should render known emotion');
    assert.ok(html.includes('Raiva'), 'Should render known emotion');
    // Unknown emotion name should NOT appear
    assert.ok(!html.includes('non_existent_emotion'), 'Unknown name should not appear');
});

// ─── 9. Forbidden fields not rendered ──────────────────────────────────────

test('acting_instruction does not appear in HTML even if present in adversarial object', () => {
    const adversarial = {
        ...NEUTRAL_PAYLOAD,
        acting_instruction: 'secret',
        coping_mode: 'MANIC',
        libido: 0.9,
        aggression: 0.8,
    };
    const html = renderPanel({ emotionState: adversarial });
    assert.ok(!html.includes('secret'), 'acting_instruction should not appear');
    assert.ok(!html.includes('MANIC'), 'coping_mode should not appear');
    assert.ok(!html.includes('libido'), 'libido should not appear');
    assert.ok(!html.includes('aggression'), 'aggression should not appear');
});

// ─── 10. Intensity converted 0..1 to 0..100 ────────────────────────────────

test('intensity 0 → 0% displayed', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    // Should be rendered with 0%
    assert.ok(html.includes('Alegria 0%'), 'Should show 0% for zero intensity');
});

test('intensity 0.5 → 50% displayed', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 0.5 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    assert.ok(html.includes('Alegria 50%'), 'Should show 50% for 0.5 intensity');
});

test('intensity 1 → 100% displayed', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 1 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    assert.ok(html.includes('Alegria 100%'), 'Should show 100% for max intensity');
});

test('intensity above 1 clamped to 100%', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: 1.5 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    // intensityToPercent clamps to 100
    assert.ok(html.includes('Alegria 100%'), 'Should clamp to 100%');
});

test('intensity below 0 clamped to 0%', () => {
    const payload = {
        ...NEUTRAL_PAYLOAD,
        dominant_emotions: [
            { name: 'joy', intensity: -0.5 },
        ],
    };
    const html = renderPanel({ emotionState: payload });
    assert.ok(html.includes('Alegria 0%'), 'Should clamp to 0%');
});

// ─── Integration: full valid payload rendering ──────────────────────────────

test('full valid payload renders correctly', () => {
    const payload = {
        schema_version: 1,
        mood_label: 'ALEGRE/EXCITADA',
        pad: { pleasure: 0.6, arousal: 0.7, dominance: 0.2 },
        dominant_emotions: [
            { name: 'joy', intensity: 0.9 },
            { name: 'trust', intensity: 0.6 },
        ],
        timestamp: 1700000000,
    };
    const html = renderPanel({ emotionState: payload });
    assert.ok(html.includes('ALEGRE/EXCITADA'), 'Should render mood label');
    assert.ok(html.includes('Alegria 90%'), 'Should render joy');
    assert.ok(html.includes('Confiança 60%'), 'Should render trust');
    assert.ok(html.includes('role="progressbar"'), 'Should have progress bars');
});
