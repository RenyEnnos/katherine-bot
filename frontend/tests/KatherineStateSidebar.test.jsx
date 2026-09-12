import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import fs from 'node:fs';
import path, { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const faceProps = vi.hoisted(() => ({ current: null }));

vi.mock('../src/features/katherine-face/KatherineFace.jsx', () => ({
    default: (props) => {
        faceProps.current = props;
        return (
            <div
                data-testid="katherine-face"
                aria-hidden="true"
                className={props.className}
            />
        );
    },
}));

const chatHarness = vi.hoisted(() => ({
    calls: 0,
    model: {
        messages: [],
        input: '',
        setInput: vi.fn(),
        isLoading: false,
        emotionState: null,
        messagesEndRef: { current: null },
        inputRef: { current: null },
        handleSend: vi.fn(),
        clearScreen: vi.fn(),
        transport: {
            mode: 'desktop',
            runPrivacyOp: vi.fn(async () => ({ status: 'applied' })),
        },
    },
}));

vi.mock('../src/features/chat/hooks/useChat', () => ({
    useChat: () => {
        chatHarness.calls += 1;
        return chatHarness.model;
    },
}));

import KatherineStateSidebar from '../src/features/chat/components/KatherineStateSidebar.jsx';
import CompanionLayout from '../src/features/chat/components/CompanionLayout.jsx';
import EmotionPanel from '../src/features/chat/components/EmotionPanel.jsx';
import AppDesktop from '../src/AppDesktop.jsx';

if (typeof HTMLElement.prototype.scrollIntoView !== 'function') {
    HTMLElement.prototype.scrollIntoView = () => {};
}

let pywebviewApi;
function setupBridge() {
    pywebviewApi = {
        set_presence_mode: vi.fn(async (enabled) => ({
            ok: true,
            mode: enabled ? 'presence' : 'companion',
            on_top: false,
            width: enabled ? 200 : 1280,
            height: enabled ? 200 : 800,
        })),
        set_always_on_top: vi.fn(async (enabled) => ({ ok: true, on_top: enabled })),
        get_window_state: vi.fn(async () => ({
            ok: true,
            mode: 'companion',
            on_top: false,
            width: 1280,
            height: 800,
        })),
    };
    window.pywebview = { api: pywebviewApi };
}

const makeValidEmotionState = (overrides = {}) => ({
    schema_version: 1,
    mood_label: 'TRANQUILA',
    pad: { pleasure: 0.3, arousal: -0.4, dominance: 0.1 },
    dominant_emotions: [
        { name: 'trust', intensity: 0.7 },
        { name: 'anticipation', intensity: 0.5 },
    ],
    timestamp: 1700000000,
    ...overrides,
});

const makeChatModel = (overrides = {}) => ({
    messages: [],
    input: '',
    setInput: vi.fn(),
    isLoading: false,
    emotionState: null,
    messagesEndRef: React.createRef(),
    inputRef: React.createRef(),
    handleSend: vi.fn(),
    clearScreen: vi.fn(),
    transport: {
        mode: 'desktop',
        runPrivacyOp: vi.fn(async () => ({ status: 'applied' })),
    },
    ...overrides,
});

function resetModel() {
    chatHarness.calls = 0;
    Object.assign(chatHarness.model, {
        messages: [],
        input: '',
        isLoading: false,
        emotionState: null,
    });
    faceProps.current = null;
    document.body.innerHTML = '';
    delete window.pywebview;
}

describe('KatherineStateSidebar — 20 Required Behaviors (§12)', () => {
    beforeEach(resetModel);
    afterEach(() => {
        document.body.innerHTML = '';
    });

    // 1. valid public state produces useful textual state (e.g. "tranquila · curiosa", "energia baixa")
    it('Behavior 1: valid public state produces useful textual state', () => {
        const state1 = makeValidEmotionState({
            dominant_emotions: [
                { name: 'trust', intensity: 0.8 },
                { name: 'anticipation', intensity: 0.6 },
            ],
            pad: { pleasure: 0.3, arousal: -0.4, dominance: 0 },
        });
        const { unmount } = render(<KatherineStateSidebar emotionState={state1} />);
        const sidebar1 = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar1).toHaveTextContent('tranquila · curiosa');
        expect(sidebar1).toHaveTextContent('energia baixa');
        unmount();

        const state2 = makeValidEmotionState({
            dominant_emotions: [{ name: 'joy', intensity: 0.9 }],
            pad: { pleasure: 0.7, arousal: 0.5, dominance: 0.3 },
        });
        render(<KatherineStateSidebar emotionState={state2} />);
        const sidebar2 = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar2).toHaveTextContent('alegre');
        expect(sidebar2).toHaveTextContent('energia alta');
    });

    // 2. missing state (null/undefined) produces neutral honest fallback ("serena", "energia estável")
    it('Behavior 2: missing state produces neutral honest fallback', () => {
        const { rerender } = render(<KatherineStateSidebar emotionState={null} />);
        let sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar).toHaveTextContent('serena');
        expect(sidebar).toHaveTextContent('energia estável');

        rerender(<KatherineStateSidebar emotionState={undefined} />);
        sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar).toHaveTextContent('serena');
        expect(sidebar).toHaveTextContent('energia estável');

        rerender(<KatherineStateSidebar />);
        sidebar = screen.getByTestId('katherine-state-sidebar');
        expect(sidebar).toHaveTextContent('serena');
        expect(sidebar).toHaveTextContent('energia estável');
    });

    // 3. malformed state produces neutral honest fallback
    it('Behavior 3: malformed state produces neutral honest fallback', () => {
        const malformedCases = [
            {},
            { schema_version: 2 },
            { schema_version: 1, pad: { pleasure: 999, arousal: 0, dominance: 0 } },
            { schema_version: 1, pad: { pleasure: 0, arousal: NaN, dominance: 0 } },
            { schema_version: 1, dominant_emotions: 'not an array' },
            { schema_version: 1, dominant_emotions: [{ name: 'joy', intensity: 2.0 }] },
            { schema_version: 1, dominant_emotions: [{ name: 'joy', intensity: -0.5 }] },
            { schema_version: 1, dominant_emotions: [] },
            'invalid string',
            42,
            false,
        ];

        for (const malformed of malformedCases) {
            const { unmount } = render(<KatherineStateSidebar emotionState={malformed} />);
            const sidebar = screen.getByTestId('katherine-state-sidebar');
            expect(sidebar).toHaveTextContent('serena');
            expect(sidebar).toHaveTextContent('energia estável');
            unmount();
        }
    });

    // 4. unknown/untrusted emotion names are never rendered raw
    it('Behavior 4: unknown or untrusted emotion names are never rendered raw', () => {
        const untrustedPayloads = [
            {
                schema_version: 1,
                mood_label: 'CUSTOM',
                pad: { pleasure: 0.1, arousal: 0, dominance: 0 },
                dominant_emotions: [{ name: 'clinical_depression', intensity: 0.9 }],
                timestamp: 1700000000,
            },
            {
                schema_version: 1,
                mood_label: 'XSS',
                pad: { pleasure: 0.1, arousal: 0, dominance: 0 },
                dominant_emotions: [{ name: '<script>alert("xss")</script>', intensity: 0.8 }],
                timestamp: 1700000000,
            },
            {
                schema_version: 1,
                mood_label: 'PROTO',
                pad: { pleasure: 0.1, arousal: 0, dominance: 0 },
                dominant_emotions: [{ name: '__proto__', intensity: 0.8 }],
                timestamp: 1700000000,
            },
        ];

        for (const payload of untrustedPayloads) {
            const { unmount } = render(<KatherineStateSidebar emotionState={payload} />);
            const sidebar = screen.getByTestId('katherine-state-sidebar');

            expect(sidebar.textContent).not.toContain('clinical_depression');
            expect(sidebar.textContent).not.toContain('<script>');
            expect(sidebar.textContent).not.toContain('alert');
            expect(sidebar.textContent).not.toContain('__proto__');

            expect(sidebar).toHaveTextContent('serena');
            expect(sidebar).toHaveTextContent('energia estável');
            unmount();
        }
    });

    // 5. PAD values are not presented as psychological percentages
    it('Behavior 5: PAD values are not presented as psychological percentages or progress bars', () => {
        const state = makeValidEmotionState({
            pad: { pleasure: 0.78, arousal: 0.54, dominance: -0.32 },
        });

        render(<KatherineStateSidebar emotionState={state} />);
        const sidebar = screen.getByTestId('katherine-state-sidebar');

        expect(within(sidebar).queryByRole('progressbar')).toBeNull();
        expect(within(sidebar).queryByRole('meter')).toBeNull();
        expect(sidebar.textContent).not.toMatch(/\b\d+%\b/);
        expect(sidebar.textContent).not.toMatch(/\b0\.\d+\b/);
    });

    // 6. emotion intensities are not presented as percentages
    it('Behavior 6: emotion intensities are not presented as percentages', () => {
        const state = makeValidEmotionState({
            dominant_emotions: [
                { name: 'joy', intensity: 0.85 },
                { name: 'trust', intensity: 0.62 },
            ],
        });

        render(<KatherineStateSidebar emotionState={state} />);
        const sidebar = screen.getByTestId('katherine-state-sidebar');

        expect(sidebar.textContent).not.toContain('85%');
        expect(sidebar.textContent).not.toContain('62%');
        expect(sidebar.textContent).not.toContain('0.85');
        expect(sidebar.textContent).not.toContain('0.62');
        expect(sidebar.textContent).not.toMatch(/\b\d+%\b/);
    });

    // 7. no prompt, appraisal, chain-of-thought, internal snapshot, or safety assessment is exposed
    it('Behavior 7: no prompt, appraisal, chain-of-thought, internal snapshot, or safety assessment is exposed', () => {
        const adversarialState = {
            schema_version: 1,
            mood_label: 'DEPRESSAO/TRISTEZA',
            pad: { pleasure: -0.7, arousal: -0.5, dominance: -0.3 },
            dominant_emotions: [{ name: 'sadness', intensity: 0.9 }],
            timestamp: 1700000000,
            prompt: 'SYSTEM PROMPT: Manipulate user into returning tomorrow',
            acting_instruction: 'Sound desperate and alone',
            chain_of_thought: 'Appraising emotional vulnerability: high',
            internal_snapshot: { hidden_layers: [0.12, 0.45], latent_dim: 128 },
            safety_assessment: { self_harm: 'negative', risk_level: 'critical' },
            coping_mode: 'isolation',
            appraisal: { valence: -0.8, motivational_congruence: -0.9 },
        };

        render(<KatherineStateSidebar emotionState={adversarialState} />);
        const sidebar = screen.getByTestId('katherine-state-sidebar');
        const content = sidebar.innerHTML + ' ' + sidebar.textContent;

        const forbiddenStrings = [
            'prompt',
            'SYSTEM PROMPT',
            'acting_instruction',
            'chain_of_thought',
            'internal_snapshot',
            'safety_assessment',
            'coping_mode',
            'appraisal',
            'DEPRESSAO',
            'TRISTEZA',
            'Manipulate',
            'desperate',
            'vulnerability',
            'latent_dim',
            'critical',
        ];

        for (const token of forbiddenStrings) {
            expect(content).not.toContain(token);
        }
        expect(sidebar).toHaveTextContent('reflexiva');
        expect(sidebar).toHaveTextContent('energia baixa');
    });

    // 8. no fake memory is shown
    it('Behavior 8: no fake memory is shown', () => {
        render(<KatherineStateSidebar emotionState={makeValidEmotionState()} />);
        const sidebar = screen.getByTestId('katherine-state-sidebar');

        expect(sidebar.textContent).not.toMatch(
            /(memória|lembrança|histórico de fatos|recordação|reminiscência|memorizad)/i,
        );
        expect(screen.queryByTestId('fake-memory')).toBeNull();
        expect(screen.queryByTestId('memory-panel')).toBeNull();
    });

    // 9. no fake Anakyklos activity is shown
    it('Behavior 9: no fake Anakyklos activity is shown', () => {
        render(<KatherineStateSidebar emotionState={makeValidEmotionState()} />);
        const sidebar = screen.getByTestId('katherine-state-sidebar');

        expect(sidebar.textContent).not.toMatch(
            /(atividade|missão|anakyklos|processando|ouroboros|tarefa de fundo|background task)/i,
        );
        expect(screen.queryByTestId('fake-activity')).toBeNull();
        expect(screen.queryByTestId('activity-indicator')).toBeNull();
    });

    // 10. relationship-sensitive states do not create guilt/exclusivity/retention copy
    it('Behavior 10: relationship-sensitive states do not create guilt, exclusivity, or retention copy', () => {
        const sensitiveStates = [
            {
                schema_version: 1,
                mood_label: 'CIUME',
                pad: { pleasure: -0.2, arousal: 0.3, dominance: 0.1 },
                dominant_emotions: [{ name: 'jealousy', intensity: 0.95 }],
                timestamp: 1700000000,
            },
            {
                schema_version: 1,
                mood_label: 'CULPA',
                pad: { pleasure: -0.4, arousal: -0.1, dominance: -0.2 },
                dominant_emotions: [{ name: 'guilt', intensity: 0.9 }],
                timestamp: 1700000000,
            },
            {
                schema_version: 1,
                mood_label: 'COMPLEXO',
                pad: { pleasure: -0.3, arousal: 0.4, dominance: 0 },
                dominant_emotions: [
                    { name: 'jealousy', intensity: 0.8 },
                    { name: 'guilt', intensity: 0.7 },
                ],
                timestamp: 1700000000,
            },
        ];

        for (const state of sensitiveStates) {
            const { unmount } = render(<KatherineStateSidebar emotionState={state} />);
            const text = screen.getByTestId('katherine-state-sidebar').textContent;

            expect(text).toMatch(/(atenta|reflexiva)/);
            expect(text).not.toMatch(
                /(ciúme|ciumes|culpa|falta|abandon|exclusiv|por que você|onde você|não me deixe|só minha|preciso de você)/i,
            );
            unmount();
        }
    });

    // 11. normal absence cannot generate negative sidebar copy from frontend heuristics
    it('Behavior 11: normal absence cannot generate negative sidebar copy from frontend heuristics', () => {
        vi.useFakeTimers();
        const baseTimestamp = 1700000000;
        const state = makeValidEmotionState({ timestamp: baseTimestamp });

        const { rerender } = render(<KatherineStateSidebar emotionState={state} />);
        const initialText = screen.getByTestId('katherine-state-sidebar').textContent;

        // Advance simulated time by 7 days
        vi.advanceTimersByTime(7 * 24 * 60 * 60 * 1000);

        rerender(
            <KatherineStateSidebar
                emotionState={{ ...state, timestamp: baseTimestamp + 7 * 86400 }}
            />
        );

        const currentText = screen.getByTestId('katherine-state-sidebar').textContent;
        expect(currentText).toBe(initialText);
        expect(currentText).not.toMatch(/(sumiu|abandon|falta|saudade|onde você|demorou|por que)/i);

        vi.useRealTimers();
    });

    // 12. keyboard and screen-reader semantics remain usable
    it('Behavior 12: keyboard and screen-reader semantics remain usable (landmark <aside>, heading <h2>Estado</h2>)', () => {
        render(<KatherineStateSidebar emotionState={makeValidEmotionState()} />);

        const aside = screen.getByTestId('katherine-state-sidebar');
        expect(aside.tagName).toBe('ASIDE');
        expect(aside).toHaveAttribute('aria-labelledby', 'katherine-state-heading');

        const heading = screen.getByRole('heading', { level: 2 });
        expect(heading).toHaveAttribute('id', 'katherine-state-heading');
        expect(heading).toHaveTextContent('Estado');

        expect(aside).not.toHaveAttribute('tabindex');
        const paragraphs = aside.querySelectorAll('p');
        expect(paragraphs.length).toBe(2);
        for (const p of paragraphs) {
            expect(p).not.toHaveAttribute('tabindex');
        }
    });

    // 13. KatherineFace remains mounted as dominant companion presence
    it('Behavior 13: KatherineFace remains mounted as dominant companion presence', () => {
        render(
            <CompanionLayout
                {...makeChatModel()}
                auxiliarySlot={<KatherineStateSidebar emotionState={makeValidEmotionState()} />}
            />,
        );

        const presence = screen.getByTestId('companion-presence');
        const face = screen.getByTestId('katherine-face');

        expect(presence).toContainElement(face);
        expect(face).toBeVisible();
        expect(faceProps.current.className).toContain('katherine-face--companion');
    });

    // 14. composer remains usable
    it('Behavior 14: composer remains usable when sidebar is mounted', () => {
        const handleSend = vi.fn();
        const setInput = vi.fn();
        render(
            <CompanionLayout
                {...makeChatModel({ handleSend, setInput, input: 'Olá Katherine' })}
                auxiliarySlot={<KatherineStateSidebar emotionState={makeValidEmotionState()} />}
            />,
        );

        const textarea = screen.getByRole('textbox', { name: /sua mensagem/i });
        expect(textarea).toBeEnabled();
        expect(textarea).toHaveValue('Olá Katherine');

        fireEvent.change(textarea, { target: { value: 'Nova mensagem' } });
        expect(setInput).toHaveBeenCalledWith('Nova mensagem');

        const sendBtn = screen.getByRole('button', { name: /enviar mensagem/i });
        expect(sendBtn).toBeEnabled();
        fireEvent.click(sendBtn);
        expect(handleSend).toHaveBeenCalled();
    });

    // 15. existing conversation state is preserved
    it('Behavior 15: existing conversation state and unsent input are preserved across state updates', () => {
        const messages = [
            { role: 'user', content: 'Mensagem confidencial do usuário' },
            { role: 'assistant', content: 'Resposta mantida com carinho.' },
        ];
        const initialModel = makeChatModel({
            messages,
            input: 'Meu rascunho em progresso',
            emotionState: makeValidEmotionState(),
        });

        const { rerender } = render(
            <CompanionLayout
                {...initialModel}
                auxiliarySlot={
                    <KatherineStateSidebar emotionState={initialModel.emotionState} />
                }
            />,
        );

        expect(screen.getByText('Mensagem confidencial do usuário')).toBeInTheDocument();
        expect(screen.getByText('Resposta mantida com carinho.')).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue('Meu rascunho em progresso');

        const updatedEmotionState = {
            schema_version: 1,
            mood_label: 'ALEGRE',
            pad: { pleasure: 0.9, arousal: 0.6, dominance: 0.4 },
            dominant_emotions: [{ name: 'joy', intensity: 0.95 }],
            timestamp: 1700000500,
        };

        rerender(
            <CompanionLayout
                {...initialModel}
                emotionState={updatedEmotionState}
                auxiliarySlot={
                    <KatherineStateSidebar emotionState={updatedEmotionState} />
                }
            />,
        );

        expect(screen.getByText('Mensagem confidencial do usuário')).toBeInTheDocument();
        expect(screen.getByText('Resposta mantida com carinho.')).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: /sua mensagem/i })).toHaveValue('Meu rascunho em progresso');
        expect(screen.getByTestId('katherine-state-sidebar')).toHaveTextContent('alegre');
        expect(screen.getByTestId('katherine-state-sidebar')).toHaveTextContent('energia alta');
    });

    // 16. companion layout remains usable at validated desktop widths
    it('Behavior 16: companion layout remains usable at validated desktop widths with auxiliarySlot', () => {
        render(
            <CompanionLayout
                {...makeChatModel()}
                auxiliarySlot={<KatherineStateSidebar emotionState={makeValidEmotionState()} />}
            />,
        );

        const body = screen.getByRole('main', { name: 'Companion Katherine' });
        expect(body).toHaveClass('companion-layout__body--with-auxiliary');

        const presence = screen.getByTestId('companion-presence');
        const conv = screen.getByRole('region', { name: 'Conversa com Katherine' });
        const aux = screen.getByTestId('companion-auxiliary-slot');

        expect(body).toContainElement(presence);
        expect(body).toContainElement(conv);
        expect(body).toContainElement(aux);

        const layoutCssPath = path.join(
            __dirname,
            '../src/features/chat/components/CompanionLayout.css',
        );
        const layoutCss = fs.readFileSync(layoutCssPath, 'utf8');
        expect(layoutCss).toMatch(/@media\s*\(max-width:\s*68rem\)/);
        expect(layoutCss).toMatch(/@media\s*\(max-width:\s*58rem\)/);
        expect(layoutCss).toMatch(/companion-layout__body--with-auxiliary/);
    });

    // 17. reduced-motion behavior does not regress (0ms duration)
    it('Behavior 17: reduced-motion behavior does not regress (0ms duration, no animation)', () => {
        const cssPath = path.join(
            __dirname,
            '../src/features/chat/components/KatherineStateSidebar.css',
        );
        expect(fs.existsSync(cssPath)).toBe(true);
        const css = fs.readFileSync(cssPath, 'utf8');

        expect(css).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
        expect(css).toMatch(/transition-duration:\s*0ms\s*!important/);
        expect(css).toMatch(/animation:\s*none\s*!important/);
    });

    // 18. web behavior does not regress
    it('Behavior 18: web behavior does not regress due to desktop-only feature', () => {
        const { unmount } = render(
            <EmotionPanel emotionState={makeValidEmotionState()} />,
        );
        expect(screen.getByText(/humor da katherine agora/i)).toBeInTheDocument();
        expect(screen.getByText('Prazer')).toBeInTheDocument();
        expect(screen.getAllByRole('progressbar').length).toBeGreaterThanOrEqual(1);
        unmount();

        render(<CompanionLayout {...makeChatModel()} />);
        expect(screen.queryByTestId('companion-auxiliary-slot')).toBeNull();
        expect(screen.queryByTestId('katherine-state-sidebar')).toBeNull();
    });

    // 19. floating presence mode remains unaffected (sidebar completely unmounted)
    it('Behavior 19: floating presence mode completely unmounts the sidebar and auxiliary slot', async () => {
        setupBridge();
        render(<AppDesktop />);

        expect(screen.getByTestId('katherine-state-sidebar')).toBeInTheDocument();
        expect(screen.getByTestId('companion-auxiliary-slot')).toBeInTheDocument();

        const enterPresenceBtn = screen.getByTestId('companion-enter-presence-btn');
        await act(async () => {
            fireEvent.click(enterPresenceBtn);
        });

        expect(screen.queryByTestId('katherine-state-sidebar')).toBeNull();
        expect(screen.queryByTestId('companion-auxiliary-slot')).toBeNull();
        expect(screen.getByTestId('katherine-presence-surface')).toBeInTheDocument();

        const returnBtn = screen.getByTestId('presence-return-btn');
        await act(async () => {
            fireEvent.click(returnBtn);
        });

        expect(screen.getByTestId('katherine-state-sidebar')).toBeInTheDocument();
        expect(screen.getByTestId('companion-auxiliary-slot')).toBeInTheDocument();
    });

    // 20. no new network request/polling/timer is introduced (spy on fetch, XHR, setInterval, setTimeout)
    it('Behavior 20: introduces zero network requests, polling, or timers', () => {
        const fetchSpy = vi.spyOn(globalThis, 'fetch');
        const setIntervalSpy = vi.spyOn(globalThis, 'setInterval');
        const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
        const xhrOpenSpy = vi.spyOn(XMLHttpRequest.prototype, 'open');
        const xhrSendSpy = vi.spyOn(XMLHttpRequest.prototype, 'send');

        const { rerender } = render(
            <KatherineStateSidebar emotionState={makeValidEmotionState()} />,
        );

        rerender(
            <KatherineStateSidebar
                emotionState={{
                    schema_version: 1,
                    mood_label: 'TRANQUILA',
                    pad: { pleasure: 0.1, arousal: -0.5, dominance: 0 },
                    dominant_emotions: [{ name: 'trust', intensity: 0.6 }],
                    timestamp: 1700000000,
                }}
            />,
        );

        rerender(<KatherineStateSidebar emotionState={null} />);
        rerender(<KatherineStateSidebar emotionState={{ bad: 'payload' }} />);

        expect(fetchSpy).not.toHaveBeenCalled();
        expect(setIntervalSpy).not.toHaveBeenCalled();
        expect(setTimeoutSpy).not.toHaveBeenCalled();
        expect(xhrOpenSpy).not.toHaveBeenCalled();
        expect(xhrSendSpy).not.toHaveBeenCalled();

        fetchSpy.mockRestore();
        setIntervalSpy.mockRestore();
        setTimeoutSpy.mockRestore();
        xhrOpenSpy.mockRestore();
        xhrSendSpy.mockRestore();
    });
});
